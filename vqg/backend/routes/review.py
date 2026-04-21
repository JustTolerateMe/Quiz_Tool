import json
import os
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.config import PROCESSED_PATH
from backend.models.db import get_job, update_job
from backend.workers.celery_app import process_and_export_task

router = APIRouter()
logger = logging.getLogger(__name__)


class ConfirmRequest(BaseModel):
    selected_ids: list[str]


@router.get("/jobs/{job_id}/triage-review")
async def get_triage_review(job_id: str):
    """
    Return the list of triaged images for the user to review and select from.
    Available once job status is AWAITING_REVIEW.
    """
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] != "AWAITING_REVIEW":
        raise HTTPException(
            status_code=409,
            detail=f"Job is not awaiting review. Current status: {job['status']}",
        )

    triage_path = os.path.join(PROCESSED_PATH, job_id, "triage_results.json")
    if not os.path.exists(triage_path):
        raise HTTPException(status_code=404, detail="Triage results not found on disk")

    with open(triage_path, "r", encoding="utf-8") as f:
        triaged = json.load(f)

    images = []
    for item in triaged:
        image_id = item.get("image_id", "")
        triage = item.get("triage", {})
        images.append({
            "image_id": image_id,
            "thumbnail_url": f"/preview/image/{job_id}/images/{image_id}",
            "page_number": item.get("page_number"),
            "route": item.get("route"),
            "category": triage.get("category") if isinstance(triage, dict) else getattr(triage, "category", None),
            "description": item.get("region_description", ""),
        })

    return {"job_id": job_id, "total": len(images), "images": images}


@router.post("/jobs/{job_id}/confirm")
async def confirm_selection(job_id: str, body: ConfirmRequest):
    """
    User confirms their image selection. Fires Phase 2 (process + generate + export).
    """
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] != "AWAITING_REVIEW":
        raise HTTPException(
            status_code=409,
            detail=f"Job is not awaiting review. Current status: {job['status']}",
        )
    if not body.selected_ids:
        raise HTTPException(status_code=400, detail="No images selected")

    filename = job["pdf_filename"]

    update_job(job_id, status="PROCESSING")
    process_and_export_task.delay(job_id, filename, body.selected_ids)

    logger.info(
        "job %s: confirmed — %d images selected, Phase 2 enqueued",
        job_id, len(body.selected_ids),
    )
    return {"status": "processing", "selected": len(body.selected_ids)}
