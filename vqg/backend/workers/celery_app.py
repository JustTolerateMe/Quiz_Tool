"""
celery_app.py — THE pipeline orchestrator.

Two-phase design (added review step):
  Phase 1 — parse_and_triage_task:
    PARSING → TRIAGING → AWAITING_REVIEW  (pauses for user selection)

  Phase 2 — process_and_export_task  (triggered by POST /jobs/{id}/confirm):
    PROCESSING → GENERATING → EXPORTING → COMPLETE

Parallelism: each stage runs with ThreadPoolExecutor(max_workers=_STAGE_WORKERS).
The shared rate limiter in gemini_client.py (thread-safe via threading.Lock) caps
throughput to GEMINI_RPM_PER_WORKER.
"""

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor

from celery import Celery
from PIL import Image as PILImage

from backend.config import MAX_TEXT_QUESTIONS_TOTAL, PROCESSED_PATH, REDIS_URL, UPLOADS_PATH, IMAGES_PATH, EXPORTS_PATH
from backend.models.db import update_job, get_stale_jobs, get_jobs_for_cleanup, delete_job
from backend.pipeline.image_triage import route_image, triage_image
from backend.pipeline.label_extractor import extract_labels
from backend.pipeline.pdf_parser import parse_pdf
from backend.pipeline.text_extractor import extract_text_chunks
from backend.pipeline.text_mcq_generator import generate_text_mcq
from backend.pipeline.quiz_generator import generate_quiz
from backend.pipeline.context_mcq_generator import generate_context_mcq
from backend.pipeline.process_diagram_generator import generate_process_diagram_quiz
from backend.pipeline.anki_exporter import build_anki_deck
from backend.pipeline.html_exporter import build_html_export
from backend.pipeline.pdf_exporter import build_pdf_export
from backend.utils.image_utils import draw_numbered_overlay

logger = logging.getLogger(__name__)

app = Celery("vqg", broker=REDIS_URL)
app.conf.result_expires = 86400  # keep results in Redis 24h
app.conf.beat_schedule = {
    "watchdog-every-5-minutes": {
        "task": "backend.workers.celery_app.watchdog_task",
        "schedule": 300,  # seconds
    },
    "cleanup-daily-3am": {
        "task": "backend.workers.celery_app.cleanup_task",
        "schedule": 86400,  # seconds (first run ~24h after worker start)
    },
}
app.conf.timezone = "UTC"

_STAGE_WORKERS = 4
_BATCH_SIZE = 20


# ---------------------------------------------------------------------------
# Phase 1: Parse + Triage → pause at AWAITING_REVIEW
# ---------------------------------------------------------------------------

@app.task(bind=True, max_retries=0)
def parse_and_triage_task(self, job_id: str, pdf_path: str) -> None:
    """
    Phase 1: Parse PDF pages, triage each image with Gemini Vision.
    Saves triage_results.json and sets status to AWAITING_REVIEW.
    The frontend then shows the user all extracted images to select from.
    Phase 2 (process_and_export_task) is triggered by POST /jobs/{id}/confirm.
    """
    update_job(job_id, status="PARSING")

    try:
        # ----------------------------------------------------------------
        # Step 1: Parse PDF → extract/crop diagram regions to disk
        # ----------------------------------------------------------------
        def _parsing_progress(pages_processed: int, total_pages: int, images_extracted: int):
            update_job(
                job_id,
                status=f"PARSING (Page {pages_processed}/{total_pages})",
                total_images=images_extracted,
            )

        extracted_images = parse_pdf(pdf_path, job_id, progress_callback=_parsing_progress)
        update_job(job_id, total_images=len(extracted_images), status="TRIAGING")

        # ----------------------------------------------------------------
        # Step 2: Triage each image — BATCHED
        # ----------------------------------------------------------------
        def _triage_one(image_data):
            try:
                image_path = image_data["image_path"]
                triage = triage_image(image_path)
                if triage is None:
                    return None
                route = route_image(triage)
                if route == "SKIP":
                    return None
                return {**image_data, "triage": triage, "route": route}
            except Exception as e:
                logger.error("job %s: triage failed for %s: %s", job_id, image_data.get("image_id"), e)
                return None

        triaged: list[dict] = []
        skipped = 0

        for i in range(0, len(extracted_images), _BATCH_SIZE):
            batch = extracted_images[i : i + _BATCH_SIZE]
            with ThreadPoolExecutor(max_workers=_STAGE_WORKERS) as pool:
                for result in pool.map(_triage_one, batch):
                    if result is None:
                        skipped += 1
                    else:
                        triaged.append(result)
            update_job(job_id, total_images=len(triaged))

        # Save triage results for Phase 2 and for the review endpoint
        _save_triage_results(job_id, triaged)

        # ----------------------------------------------------------------
        # Step 3: Extract text chunks (parallel to image pipeline)
        # ----------------------------------------------------------------
        text_chunks = extract_text_chunks(pdf_path)
        _save_text_chunks(job_id, text_chunks)
        logger.info("job %s: %d eligible text pages saved", job_id, len(text_chunks))

        update_job(
            job_id,
            status="AWAITING_REVIEW",
            total_images=len(triaged),
            skipped_images=skipped,
        )
        logger.info(
            "job %s: AWAITING_REVIEW — %d images ready for selection (%d skipped)",
            job_id, len(triaged), skipped,
        )

    except Exception as exc:
        logger.exception("job %s: FAILED in Phase 1 — %s", job_id, exc)
        update_job(job_id, status="FAILED", error=str(exc))
        raise


# ---------------------------------------------------------------------------
# Phase 2: Process + Generate + Export (triggered by user confirmation)
# ---------------------------------------------------------------------------

@app.task(bind=True, max_retries=0)
def process_and_export_task(
    self, job_id: str, filename: str, selected_ids: list, include_text_questions: bool = True
) -> None:
    """
    Phase 2: Process and generate questions for user-selected images only.
    Called by POST /jobs/{id}/confirm after user reviews triage results.

    include_text_questions: if True, also generate MCQ from text chunks saved in Phase 1.
    """
    update_job(job_id, status="PROCESSING")

    try:
        # Load triage results and filter to selected images
        triage_path = os.path.join(PROCESSED_PATH, job_id, "triage_results.json")
        with open(triage_path, "r", encoding="utf-8") as f:
            all_triaged = json.load(f)

        selected_set = set(selected_ids)
        triaged = [item for item in all_triaged if item["image_id"] in selected_set]

        # Load text chunks written by Phase 1
        text_chunks = _load_text_chunks(job_id) if include_text_questions else []

        update_job(job_id, total_images=len(triaged), processed_images=0, generated_images=0, quiz_count=0)
        logger.info("job %s: Phase 2 starting — %d/%d images selected, %d text chunks",
                    job_id, len(triaged), len(all_triaged), len(text_chunks))

        # ----------------------------------------------------------------
        # Step 3: Process images — BATCHED
        # ----------------------------------------------------------------
        def _process_one(item):
            try:
                route = item["route"]
                if route == "LABEL_BLANK":
                    image_path = item["image_path"]
                    labels = extract_labels(image_path)

                    img = PILImage.open(image_path).convert("RGB")
                    all_labels = labels.get("labels", []) if labels else []
                    label_list = [lb for lb in all_labels if lb.get("label_type", "") != "INLINE_TEXT"]

                    annotated, label_map = draw_numbered_overlay(img, label_list)

                    stem = os.path.splitext(os.path.basename(image_path))[0]
                    numbered_filename = f"{stem}_numbered.png"
                    numbered_path = os.path.join(PROCESSED_PATH, job_id, numbered_filename)
                    os.makedirs(os.path.dirname(numbered_path), exist_ok=True)
                    annotated.save(numbered_path)
                    img.close()

                    return ({
                        **item,
                        "labels": labels,
                        "processed_path": numbered_path,
                        "method": "numbered_overlay",
                        "label_map": label_map,
                        "_numbered_label_ids": [lb["id"] for lb in label_list],
                    }, 1)

                elif route == "CONTEXT_MCQ":
                    return ({**item, "method": "context_mcq", "processed_path": None}, 0)
                elif route == "SEQUENCE_ORDER":
                    return ({**item, "method": "process_diagram", "processed_path": None}, 0)
                else:
                    return ({**item, "method": "passthrough", "processed_path": None}, 0)
            except Exception as e:
                logger.error("job %s: processing failed for %s: %s", job_id, item.get("image_id"), e)
                return (None, 0)

        results: list[dict] = []
        processed_count = 0

        for i in range(0, len(triaged), _BATCH_SIZE):
            batch = triaged[i : i + _BATCH_SIZE]
            with ThreadPoolExecutor(max_workers=_STAGE_WORKERS) as pool:
                for result_item, increment in pool.map(_process_one, batch):
                    if result_item:
                        results.append(result_item)
                        processed_count += increment
            update_job(job_id, processed_images=processed_count)

        update_job(job_id, status="GENERATING", processed_images=processed_count)

        # ----------------------------------------------------------------
        # Step 4: Generate quiz questions — BATCHED
        # ----------------------------------------------------------------
        def _generate_one(item):
            try:
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
                    if questions and item.get("_numbered_label_ids"):
                        id_to_box = {lid: idx + 1 for idx, lid in enumerate(item["_numbered_label_ids"])}
                        for q in questions:
                            box_num = id_to_box.get(q.get("label_id"))
                            if box_num:
                                q["question"] = f"What is structure #{box_num}?"
                    item["questions"] = questions
                    return item, len(questions)

                elif route == "CONTEXT_MCQ":
                    questions = generate_context_mcq(item["image_path"], item["triage"])
                    item["questions"] = questions
                    return item, len(questions)

                elif route == "SEQUENCE_ORDER":
                    questions = generate_process_diagram_quiz(
                        item["image_path"], item["triage"], item.get("surrounding_text", "")
                    )
                    item["questions"] = questions
                    return item, len(questions)

                return item, 0
            except Exception as e:
                logger.error("job %s: generation failed for %s: %s", job_id, item.get("image_id"), e)
                return item, 0

        enriched: list[dict] = []
        quiz_count = 0
        generated_count = 0

        for i in range(0, len(results), _BATCH_SIZE):
            batch = results[i : i + _BATCH_SIZE]
            with ThreadPoolExecutor(max_workers=_STAGE_WORKERS) as pool:
                batch_results = list(pool.map(_generate_one, batch))
            for res_item, q_count in batch_results:
                enriched.append(res_item)
                quiz_count += q_count
                if q_count > 0:
                    generated_count += 1
            update_job(job_id, generated_images=generated_count, quiz_count=quiz_count)

        # ----------------------------------------------------------------
        # Step 4b: Generate text-based MCQ from page text chunks
        # ----------------------------------------------------------------
        if text_chunks:
            update_job(job_id, status="GENERATING (text)")

            def _generate_text_one(chunk):
                try:
                    questions = generate_text_mcq(chunk)
                    if not questions:
                        return None
                    return {
                        "image_id": chunk["chunk_id"],
                        "image_path": None,
                        "processed_path": None,
                        "page_number": chunk["page_number"],
                        "route": "TEXT_MCQ",
                        "method": "text_mcq",
                        "questions": questions,
                    }
                except Exception as e:
                    logger.error("job %s: text generation failed for %s: %s",
                                 job_id, chunk.get("chunk_id"), e)
                    return None

            text_budget = MAX_TEXT_QUESTIONS_TOTAL
            for i in range(0, len(text_chunks), _BATCH_SIZE):
                if text_budget <= 0:
                    logger.info("job %s: text question cap reached (%d)", job_id, MAX_TEXT_QUESTIONS_TOTAL)
                    break
                batch = text_chunks[i : i + _BATCH_SIZE]
                with ThreadPoolExecutor(max_workers=_STAGE_WORKERS) as pool:
                    for text_item in pool.map(_generate_text_one, batch):
                        if text_item and text_item.get("questions"):
                            q_count = len(text_item["questions"])
                            if text_budget >= q_count:
                                enriched.append(text_item)
                                quiz_count += q_count
                                generated_count += 1
                                text_budget -= q_count
                            else:
                                # Partial: trim to remaining budget
                                text_item["questions"] = text_item["questions"][:text_budget]
                                if text_item["questions"]:
                                    enriched.append(text_item)
                                    quiz_count += len(text_item["questions"])
                                    generated_count += 1
                                text_budget = 0
                update_job(job_id, generated_images=generated_count, quiz_count=quiz_count)

        _save_processing_results(job_id, enriched)

        # ----------------------------------------------------------------
        # Step 5: Build Anki deck + HTML study guide
        # ----------------------------------------------------------------
        update_job(job_id, status="EXPORTING")
        try:
            export_path = build_anki_deck(enriched, job_id, filename)
            html_path = build_html_export(enriched, job_id, filename)
            pdf_path = build_pdf_export(enriched, job_id, filename)
            update_job(job_id, export_path=export_path, html_export_path=html_path, pdf_export_path=pdf_path)
        except ValueError as e:
            logger.warning("job %s: no cards to export — %s", job_id, e)

        update_job(job_id, status="COMPLETE")
        logger.info("job %s: COMPLETE — %d questions from %d images", job_id, quiz_count, len(triaged))

    except Exception as exc:
        logger.exception("job %s: FAILED in Phase 2 — %s", job_id, exc)
        update_job(job_id, status="FAILED", error=str(exc))
        raise


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _save_triage_results(job_id: str, triaged: list) -> None:
    job_dir = os.path.join(PROCESSED_PATH, job_id)
    os.makedirs(job_dir, exist_ok=True)
    path = os.path.join(job_dir, "triage_results.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(triaged, f, indent=2, default=str)
        logger.info("job %s: triage results saved (%d images)", job_id, len(triaged))
    except Exception as e:
        logger.warning("job %s: could not save triage results: %s", job_id, e)


def _save_processing_results(job_id: str, results: list) -> None:
    job_dir = os.path.join(PROCESSED_PATH, job_id)
    os.makedirs(job_dir, exist_ok=True)
    path = os.path.join(job_dir, "processing_results.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, default=str)
    except Exception as e:
        logger.warning("job %s: could not save processing results: %s", job_id, e)


def _save_text_chunks(job_id: str, chunks: list) -> None:
    job_dir = os.path.join(PROCESSED_PATH, job_id)
    os.makedirs(job_dir, exist_ok=True)
    path = os.path.join(job_dir, "text_chunks.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(chunks, f, indent=2, ensure_ascii=False)
        logger.info("job %s: text chunks saved (%d pages)", job_id, len(chunks))
    except Exception as e:
        logger.warning("job %s: could not save text chunks: %s", job_id, e)


def _load_text_chunks(job_id: str) -> list:
    path = os.path.join(PROCESSED_PATH, job_id, "text_chunks.json")
    if not os.path.isfile(path):
        logger.debug("job %s: no text_chunks.json found — skipping text questions", job_id)
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("job %s: could not load text chunks: %s", job_id, e)
        return []


def _delete_job_files(job_id: str) -> None:
    import shutil
    import glob
    # Remove per-job directories
    for base in (IMAGES_PATH, PROCESSED_PATH, EXPORTS_PATH):
        job_dir = os.path.join(base, job_id)
        if os.path.isdir(job_dir):
            shutil.rmtree(job_dir, ignore_errors=True)
    # Remove uploaded PDF (prefixed with job_id)
    for pdf in glob.glob(os.path.join(UPLOADS_PATH, f"{job_id}_*")):
        try:
            os.remove(pdf)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Periodic tasks (run by Celery Beat via -B flag on the worker)
# ---------------------------------------------------------------------------

@app.task
def watchdog_task() -> None:
    """Mark jobs stuck in active statuses for >30 min as FAILED."""
    stale = get_stale_jobs(
        statuses=("PARSING", "TRIAGING", "PROCESSING", "GENERATING", "EXPORTING"),
        older_than_minutes=30,
    )
    for job in stale:
        logger.warning("watchdog: job %s stuck in %s — marking FAILED", job["job_id"], job["status"])
        update_job(
            job["job_id"],
            status="FAILED",
            error="Timed out — worker likely crashed. Please re-upload.",
        )
    if stale:
        logger.info("watchdog: marked %d stale job(s) as FAILED", len(stale))


@app.task
def cleanup_task() -> None:
    """Delete files and DB rows for abandoned / expired jobs."""
    groups = get_jobs_for_cleanup()

    for job_id in groups["abandoned"]:
        logger.info("cleanup: AWAITING_REVIEW expired — deleting files for %s", job_id)
        _delete_job_files(job_id)
        update_job(job_id, status="FAILED", error="Expired — not confirmed within 24 hours.")

    for job_id in groups["expired"]:
        logger.info("cleanup: COMPLETE/FAILED >7d — removing %s", job_id)
        _delete_job_files(job_id)
        delete_job(job_id)

    for job_id in groups["lost"]:
        logger.info("cleanup: QUEUED >2h (task lost) — marking FAILED for %s", job_id)
        update_job(job_id, status="FAILED", error="Task message lost — please re-upload.")

    total = len(groups["abandoned"]) + len(groups["expired"]) + len(groups["lost"])
    if total:
        logger.info("cleanup: processed %d job(s) total", total)
