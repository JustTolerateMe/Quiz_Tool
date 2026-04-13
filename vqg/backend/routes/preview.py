"""
preview.py — Browser-based card preview endpoints.

Two endpoints:
  GET /jobs/{job_id}/preview   — Returns quiz cards from processing_results.json
  GET /preview/image/{job_id}/{folder}/{filename} — Serves stored images safely
"""

import json
import logging
import os

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from backend.config import IMAGES_PATH, PROCESSED_PATH

logger = logging.getLogger(__name__)

router = APIRouter()

# Only these storage sub-folders may be served
_ALLOWED_FOLDERS = {"images", "processed"}


@router.get("/jobs/{job_id}/preview")
async def get_job_preview(job_id: str):
    """
    Return quiz cards for a completed job, ready to render in the browser.

    Reads processing_results.json and returns only LABEL_BLANK items that have
    questions. Each card includes the numbered image URL and its questions.
    """
    results_path = os.path.join(PROCESSED_PATH, job_id, "processing_results.json")

    if not os.path.isfile(results_path):
        raise HTTPException(status_code=404, detail="Preview not available — job not yet complete or not found")

    try:
        with open(results_path, encoding="utf-8") as f:
            results = json.load(f)
    except Exception as e:
        logger.error("preview: could not read results for job %s: %s", job_id, e)
        raise HTTPException(status_code=500, detail="Could not read processing results")

    cards = []
    for item in results:
        route = item.get("route")
        if route not in ("LABEL_BLANK", "CONTEXT_MCQ", "SEQUENCE_ORDER"):
            continue
        questions = item.get("questions") or []
        if not questions:
            continue

        processed_path = item.get("processed_path")
        original_path = item.get("image_path")

        # Build image URLs — numbered overlay for LABEL_BLANK, original for CONTEXT_MCQ
        numbered_image_url = None
        original_image_url = None

        if processed_path and os.path.isfile(processed_path):
            filename = os.path.basename(processed_path)
            numbered_image_url = f"/preview/image/{job_id}/processed/{filename}"

        # CONTEXT_MCQ cards are text-only — no image shown to the student
        # SEQUENCE_ORDER and LABEL_BLANK cards show the original/numbered image
        if route != "CONTEXT_MCQ" and original_path and os.path.isfile(original_path):
            filename = os.path.basename(original_path)
            original_image_url = f"/preview/image/{job_id}/images/{filename}"

        cards.append({
            "image_id": item.get("image_id"),
            "panel_description": item.get("panel_description", ""),
            "numbered_image_url": numbered_image_url,
            "original_image_url": original_image_url,
            "method": item.get("method"),
            "questions": questions,
        })

    return {"job_id": job_id, "card_count": len(cards), "cards": cards}


@router.get("/preview/image/{job_id}/{folder}/{filename}")
async def serve_image(job_id: str, folder: str, filename: str):
    """
    Serve a stored image file with path traversal protection.

    Only allows 'images' and 'processed' as folder values.
    job_id and filename must not contain path separators.
    """
    # Validate inputs — no path traversal
    if folder not in _ALLOWED_FOLDERS:
        raise HTTPException(status_code=400, detail="Invalid folder")
    if os.sep in job_id or "/" in job_id or ".." in job_id:
        raise HTTPException(status_code=400, detail="Invalid job_id")
    if os.sep in filename or "/" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    base = IMAGES_PATH if folder == "images" else PROCESSED_PATH
    file_path = os.path.join(base, job_id, filename)

    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="Image not found")

    # Infer media type from extension
    ext = os.path.splitext(filename)[1].lower()
    media_types = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
    media_type = media_types.get(ext, "image/png")

    return FileResponse(file_path, media_type=media_type)
