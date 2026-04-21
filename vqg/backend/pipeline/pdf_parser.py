"""
pdf_parser.py — Universal PDF image extractor.

Every page is rendered at PAGE_RENDER_SCALE and sent to Gemini Vision, which
returns bounding boxes for every quiz-worthy diagram or figure on the page.
Each region is cropped and saved independently, then passed to the rest of the
pipeline unchanged.

This replaces the two-path heuristic approach (slide vs embedded image) and the
separate panel_splitter module. Any PDF type — textbook, slide deck, scanned —
is handled identically. Panel layouts (side-by-side, stacked, grid) are
detected automatically from the bounding boxes.

Output filenames: page{N:03d}_region{M}.png  (1-indexed M per page)
Fallback (Gemini failure or empty page): page{N:03d}_region0.png (full page)
"""

import concurrent.futures
import logging
import os

import fitz  # PyMuPDF
from PIL import Image

from backend.config import IMAGES_PATH, MAX_IMAGES_PER_PDF, PAGE_RENDER_SCALE
from backend.utils.gemini_client import call_vision_json

logger = logging.getLogger(__name__)

# Margin added around each crop so callout lines at the diagram edge aren't clipped.
_CROP_MARGIN = 0.01  # fraction of image dimension

_REGION_DETECT_PROMPT = """Look at this page carefully.

Identify every distinct diagram, figure, or illustration that would be worth quizzing a student on.
Include: anatomical diagrams, process/flowchart diagrams, scientific figures, clinical photos showing technique or positioning, radiographs, microscopy images.
Do NOT include: body text paragraphs, page numbers, running headers/footers, captions alone, decorative borders.

Return ONLY a JSON array — no other text:
[
  {
    "x0": <float 0.0-1.0, left edge as fraction of image width>,
    "y0": <float 0.0-1.0, top edge as fraction of image height>,
    "x1": <float 0.0-1.0, right edge as fraction of image width>,
    "y1": <float 0.0-1.0, bottom edge as fraction of image height>,
    "description": "<one sentence: what this figure shows>",
    "has_labels": <true if the figure has callout labels or arrows pointing to structures, false otherwise>
  }
]

Rules:
- Each distinct figure gets its own entry — a page with two side-by-side diagrams returns two entries
- If the diagram spans the full page (e.g. a slide), return one entry covering the full page
- Return [] if the page has no quizzable figures (e.g. pure text page, title page)
- Coordinates origin is top-left; x goes left→right, y goes top→bottom"""


def parse_pdf(pdf_path: str, job_id: str, progress_callback=None) -> list[dict]:
    """
    Parse a PDF and extract all quiz-worthy diagram regions, parallelised.
    
    Args:
        pdf_path: Absolute path to the uploaded PDF file.
        job_id:   Unique job identifier — images saved under IMAGES_PATH/{job_id}/
        progress_callback: Optional callable(pages_processed, total_pages, extracted_count)
    """
    job_images_dir = os.path.join(IMAGES_PATH, job_id)
    os.makedirs(job_images_dir, exist_ok=True)

    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    doc.close()

    logger.info("Opened PDF '%s' — %d pages (job %s)", os.path.basename(pdf_path), total_pages, job_id)

    extracted_by_page = {}
    pages_processed = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        batch_size = 10
        for i in range(0, total_pages, batch_size):
            batch_pages = list(range(i, min(i + batch_size, total_pages)))

            future_to_page = {
                pool.submit(_process_single_page, pdf_path, p, job_id, job_images_dir): p
                for p in batch_pages
            }

            for future in concurrent.futures.as_completed(future_to_page):
                page_num = future_to_page[future]
                pages_processed += 1
                try:
                    page_results = future.result()
                    extracted_by_page[page_num] = page_results
                except Exception as e:
                    logger.error("job %s: error processing page %d: %s", job_id, page_num, e)
                    extracted_by_page[page_num] = []

                if progress_callback:
                    current_images = sum(len(res) for res in extracted_by_page.values())
                    progress_callback(pages_processed, total_pages, current_images)

            # Check limit after each batch
            current_images = sum(len(res) for res in extracted_by_page.values())
            if current_images >= MAX_IMAGES_PER_PDF:
                logger.info("job %s: hit MAX_IMAGES_PER_PDF cap (%d)", job_id, MAX_IMAGES_PER_PDF)
                break

    # Reassemble in exact page order
    extracted = []
    for p in range(total_pages):
        if p in extracted_by_page:
            extracted.extend(extracted_by_page[p])
            if len(extracted) >= MAX_IMAGES_PER_PDF:
                extracted = extracted[:MAX_IMAGES_PER_PDF]
                break

    logger.info("job %s: extracted %d regions total", job_id, len(extracted))
    return extracted


def _process_single_page(pdf_path: str, page_num: int, job_id: str, job_images_dir: str) -> list[dict]:
    # Need to reopen doc inside worker thread (PyMuPDF `doc` is not thread-safe)
    doc = fitz.open(pdf_path)
    try:
        page = doc[page_num]
        surrounding_text = page.get_text()[:500]

        mat = fitz.Matrix(PAGE_RENDER_SCALE, PAGE_RENDER_SCALE)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        pil_page = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        w, h = pil_page.size
    except Exception as e:
        logger.warning("job %s: pixmap→PIL failed for page %d: %s", job_id, page_num, e)
        return []
    finally:
        doc.close()

    temp_path = os.path.join(job_images_dir, f"_tmp_page{page_num:03d}.png")
    try:
        pil_page.save(temp_path)
    except Exception as e:
        logger.warning("job %s: could not save temp render for page %d: %s", job_id, page_num, e)
        return []

    regions = _detect_regions(temp_path, page_num, job_id)

    try:
        os.remove(temp_path)
    except OSError:
        pass

    if not regions:
        logger.debug("job %s: page %d — no quizzable regions detected", job_id, page_num)
        return []

    extracted_for_page = []
    for region_idx, region in enumerate(regions, start=1):
        crop = _crop_region(pil_page, region, w, h)
        if crop is None:
            continue

        img_filename = f"page{page_num:03d}_region{region_idx}.png"
        img_path = os.path.join(job_images_dir, img_filename)

        try:
            crop.save(img_path)
            extracted_for_page.append({
                "image_id": img_filename,
                "image_path": img_path,
                "page_number": page_num,
                "surrounding_text": surrounding_text,
                "region_description": region.get("description", ""),
                "has_labels": region.get("has_labels", False),
            })
            logger.debug(
                "job %s: page %d region %d saved → %s (%dx%d)",
                job_id, page_num, region_idx, img_filename, w, h
            )
        except Exception as e:
            logger.warning("job %s: could not save crop for page %d region %d: %s",
                           job_id, page_num, region_idx, e)

    # Free memory
    pil_page.close()
    return extracted_for_page


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _detect_regions(image_path: str, page_num: int, job_id: str) -> list[dict]:
    """
    Call Gemini Vision to detect quiz-worthy diagram regions on a rendered page.

    Returns a list of region dicts with x0,y0,x1,y1 (0.0–1.0) and description.
    Returns [] if Gemini fails or detects no diagrams (text-only page).
    """
    try:
        result = call_vision_json(image_path, _REGION_DETECT_PROMPT)
    except RuntimeError as e:
        logger.warning("job %s: region detection failed for page %d: %s — using full page fallback",
                       job_id, page_num, e)
        return _full_page_fallback()

    if isinstance(result, list):
        regions = result
    elif isinstance(result, dict):
        # Gemini sometimes wraps: {"regions": [...]}
        for key in ("regions", "figures", "diagrams", "data"):
            if isinstance(result.get(key), list):
                regions = result[key]
                break
        else:
            logger.warning("job %s: unexpected region detection response shape for page %d",
                           job_id, page_num)
            return _full_page_fallback()
    else:
        return _full_page_fallback()

    # Validate each region has required coordinate fields
    valid = []
    for r in regions:
        if not isinstance(r, dict):
            continue
        if not all(k in r for k in ("x0", "y0", "x1", "y1")):
            logger.debug("job %s: page %d — region missing bbox keys, skipped", job_id, page_num)
            continue
        valid.append(r)

    return valid


def _full_page_fallback() -> list[dict]:
    """Return a single region covering the full page (used when Gemini fails)."""
    return [{"x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0,
             "description": "full page (Gemini detection unavailable)",
             "has_labels": False}]


def _crop_region(image: Image.Image, region: dict, w: int, h: int) -> Image.Image | None:
    """
    Crop a region from the full-page image with a small margin.

    Coordinates in region are normalized 0.0–1.0. Returns None if the
    computed bbox is invalid after clamping.
    """
    margin_x = int(w * _CROP_MARGIN)
    margin_y = int(h * _CROP_MARGIN)

    x0 = max(0, int(region["x0"] * w) - margin_x)
    y0 = max(0, int(region["y0"] * h) - margin_y)
    x1 = min(w, int(region["x1"] * w) + margin_x)
    y1 = min(h, int(region["y1"] * h) + margin_y)

    if x1 <= x0 or y1 <= y0:
        logger.debug("Invalid crop bbox (%d,%d)-(%d,%d) — skipped", x0, y0, x1, y1)
        return None

    return image.crop((x0, y0, x1, y1))
