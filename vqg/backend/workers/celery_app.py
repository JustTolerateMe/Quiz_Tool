"""
celery_app.py — THE pipeline orchestrator.

This is the only module that calls pipeline functions in sequence.
FastAPI routes enqueue tasks here; they never call pipeline functions directly.

Pipeline stages:
  PARSING → TRIAGING → PROCESSING → GENERATING → EXPORTING → COMPLETE

Parallelism: each stage runs with ThreadPoolExecutor(max_workers=4) so
Gemini I/O calls overlap. The shared rate limiter in gemini_client.py
(thread-safe via threading.Lock) caps throughput to GEMINI_RPM_PER_WORKER.
"""

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor

from celery import Celery
from PIL import Image as PILImage

from backend.config import PROCESSED_PATH, REDIS_URL
from backend.models.db import update_job
from backend.pipeline.image_triage import route_image, triage_image
from backend.pipeline.label_extractor import extract_labels
from backend.pipeline.pdf_parser import parse_pdf
from backend.pipeline.quiz_generator import generate_quiz
from backend.pipeline.context_mcq_generator import generate_context_mcq
from backend.pipeline.process_diagram_generator import generate_process_diagram_quiz
from backend.pipeline.anki_exporter import build_anki_deck
from backend.utils.image_utils import draw_numbered_overlay

logger = logging.getLogger(__name__)

app = Celery("vqg", broker=REDIS_URL)
app.conf.result_expires = 86400  # keep results in Redis 24h

# Number of threads per stage inside a single job. The shared rate limiter
# in gemini_client.py serialises actual API calls, so this only controls
# how many images are pre-queued concurrently — not raw throughput.
_STAGE_WORKERS = 4


@app.task(bind=True, max_retries=0)
def process_pdf_task(self, job_id: str, pdf_path: str, filename: str) -> None:
    """
    Full pipeline task for a single PDF upload.

    PARSING → TRIAGING → PROCESSING → GENERATING → EXPORTING → COMPLETE
    """
    update_job(job_id, status="PARSING")

    try:
        # ----------------------------------------------------------------
        # Step 1: Parse PDF → extract/crop diagram regions to disk
        # ----------------------------------------------------------------
        extracted_images = parse_pdf(pdf_path, job_id)

        update_job(job_id, total_images=len(extracted_images), status="TRIAGING")

        # ----------------------------------------------------------------
        # Step 2: Triage each image with Gemini Vision — PARALLEL
        # ----------------------------------------------------------------
        def _triage_one(image_data):
            image_path = image_data["image_path"]
            triage = triage_image(image_path)
            if triage is None:
                logger.info("job %s: skipped %s (triage returned None)", job_id, image_path)
                return None
            route = route_image(triage)
            if route == "SKIP":
                logger.info(
                    "job %s: skipped %s (route=SKIP, category=%s)",
                    job_id, os.path.basename(image_path), triage.get("category"),
                )
                return None
            logger.info(
                "job %s: triaged %s → %s (%s)",
                job_id, os.path.basename(image_path), route, triage.get("category"),
            )
            return {**image_data, "triage": triage, "route": route}

        triaged: list[dict] = []
        skipped = 0
        with ThreadPoolExecutor(max_workers=_STAGE_WORKERS) as pool:
            for result in pool.map(_triage_one, extracted_images):
                if result is None:
                    skipped += 1
                else:
                    triaged.append(result)

        update_job(job_id, status="PROCESSING")

        # ----------------------------------------------------------------
        # Step 3: Process images — LABEL_BLANK get numbered overlay;
        #         other routes pass through. Order preserved via pool.map().
        # ----------------------------------------------------------------
        def _process_one(item):
            route = item["route"]

            if route == "LABEL_BLANK":
                image_path = item["image_path"]

                labels = extract_labels(image_path)
                if labels:
                    logger.info(
                        "job %s: extracted %d labels from %s",
                        job_id, labels.get("total_labels", 0), os.path.basename(image_path),
                    )
                else:
                    logger.info(
                        "job %s: label extraction failed for %s — overlay will have no numbers",
                        job_id, os.path.basename(image_path),
                    )

                img = PILImage.open(image_path).convert("RGB")
                all_labels = labels.get("labels", []) if labels else []
                label_list = [
                    lb for lb in all_labels
                    if lb.get("label_type", "") != "INLINE_TEXT"
                ]
                annotated, label_map = draw_numbered_overlay(img, label_list)

                stem = os.path.splitext(os.path.basename(image_path))[0]
                numbered_filename = f"{stem}_numbered.png"
                numbered_path = os.path.join(PROCESSED_PATH, job_id, numbered_filename)
                os.makedirs(os.path.dirname(numbered_path), exist_ok=True)
                annotated.save(numbered_path)

                logger.info(
                    "job %s: numbered overlay saved for %s (%d labels)",
                    job_id, os.path.basename(image_path), len(label_list),
                )
                return ({
                    **item,
                    "labels": labels,
                    "processed_path": numbered_path,
                    "method": "numbered_overlay",
                    "ssim": None,
                    "label_map": label_map,
                    "_numbered_label_ids": [lb["id"] for lb in label_list],
                }, 1)

            elif route == "CONTEXT_MCQ":
                logger.info(
                    "job %s: CONTEXT_MCQ passthrough for %s",
                    job_id, os.path.basename(item["image_path"]),
                )
                return ({**item, "method": "context_mcq", "processed_path": None}, 0)

            elif route == "SEQUENCE_ORDER":
                logger.info(
                    "job %s: SEQUENCE_ORDER passthrough for %s",
                    job_id, os.path.basename(item["image_path"]),
                )
                return ({**item, "method": "process_diagram", "processed_path": None}, 0)

            else:
                return ({**item, "method": "passthrough", "processed_path": None}, 0)

        results: list[dict] = []
        processed_count = 0
        with ThreadPoolExecutor(max_workers=_STAGE_WORKERS) as pool:
            for result_item, increment in pool.map(_process_one, triaged):
                results.append(result_item)
                processed_count += increment
        # Single update after processing completes (avoids per-image SQLite writes)
        update_job(job_id, processed_images=processed_count, status="GENERATING")

        # ----------------------------------------------------------------
        # Step 4: Generate quiz questions — PARALLEL
        # ----------------------------------------------------------------
        def _generate_one(item):
            route = item["route"]

            if route == "LABEL_BLANK":
                if not item.get("labels"):
                    return item, 0

                quiz_image_path = item.get("processed_path") or item["image_path"]
                questions = generate_quiz(
                    image_path=quiz_image_path,
                    labels=item["labels"],
                    surrounding_text=item.get("surrounding_text", ""),
                    triage=item["triage"],
                    target_label_ids=item.get("_numbered_label_ids"),
                )

                # Rephrase to reference badge number on the diagram
                if questions and item.get("_numbered_label_ids"):
                    id_to_box = {
                        lid: i + 1
                        for i, lid in enumerate(item["_numbered_label_ids"])
                    }
                    for q in questions:
                        box_num = id_to_box.get(q.get("label_id"))
                        if box_num:
                            q["question"] = f"What is structure #{box_num}?"

                item["questions"] = questions
                logger.info(
                    "job %s: generated %d questions for %s",
                    job_id, len(questions), os.path.basename(quiz_image_path),
                )
                return item, len(questions)

            elif route == "CONTEXT_MCQ":
                questions = generate_context_mcq(item["image_path"], item["triage"])
                item["questions"] = questions
                logger.info(
                    "job %s: generated %d context MCQ questions for %s",
                    job_id, len(questions), os.path.basename(item["image_path"]),
                )
                return item, len(questions)

            elif route == "SEQUENCE_ORDER":
                questions = generate_process_diagram_quiz(
                    item["image_path"],
                    item["triage"],
                    item.get("surrounding_text", ""),
                )
                item["questions"] = questions
                logger.info(
                    "job %s: generated %d process diagram questions for %s",
                    job_id, len(questions), os.path.basename(item["image_path"]),
                )
                return item, len(questions)

            return item, 0

        quiz_count = 0
        generated_count = 0
        with ThreadPoolExecutor(max_workers=_STAGE_WORKERS) as pool:
            enriched = list(pool.map(_generate_one, results))

        results = []
        for result_item, q_count in enriched:
            results.append(result_item)
            quiz_count += q_count
            if q_count > 0:
                generated_count += 1

        update_job(job_id, generated_images=generated_count, quiz_count=quiz_count)

        # ----------------------------------------------------------------
        # Save full processing results (now includes questions)
        # ----------------------------------------------------------------
        _save_processing_results(job_id, results)

        # ----------------------------------------------------------------
        # Step 5: Build Anki .apkg deck
        # ----------------------------------------------------------------
        update_job(job_id, status="EXPORTING")

        try:
            export_path = build_anki_deck(results, job_id, filename)
            update_job(job_id, export_path=export_path)
        except ValueError as e:
            # No questions generated — still complete, just no deck
            logger.warning("job %s: no cards to export — %s", job_id, e)
            export_path = None

        update_job(
            job_id,
            status="COMPLETE",
            processed_images=processed_count,
            skipped_images=skipped,
            quiz_count=quiz_count,
        )
        logger.info(
            "job %s: COMPLETE — %d processed, %d skipped, %d questions, export=%s",
            job_id, processed_count, skipped, quiz_count,
            os.path.basename(export_path) if export_path else "none",
        )

    except Exception as exc:
        logger.exception("job %s: FAILED — %s", job_id, exc)
        update_job(job_id, status="FAILED", error=str(exc))
        raise


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _save_processing_results(job_id: str, results: list) -> None:
    """
    Persist full processing results as JSON.
    Saved to storage/processed/{job_id}/processing_results.json
    """
    job_processed_dir = os.path.join(PROCESSED_PATH, job_id)
    os.makedirs(job_processed_dir, exist_ok=True)
    output_path = os.path.join(job_processed_dir, "processing_results.json")
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, default=str)
        logger.info("job %s: processing results saved to %s", job_id, output_path)
    except Exception as e:
        logger.warning("job %s: could not save processing results: %s", job_id, e)
