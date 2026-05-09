import os
import logging
import traceback
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from backend.config import EXPORTS_PATH
from backend.models.db import get_job

router = APIRouter()
logger = logging.getLogger(__name__)

_EXPORTS_ROOT = os.path.realpath(EXPORTS_PATH)


def _safe_export_path(raw_path: str) -> str:
    """Resolve path and ensure it's within the exports directory."""
    resolved = os.path.realpath(raw_path)
    if not resolved.startswith(_EXPORTS_ROOT + os.sep):
        raise HTTPException(status_code=403, detail="Access denied.")
    if not os.path.exists(resolved):
        raise HTTPException(status_code=404, detail="Export file missing on disk.")
    return resolved


@router.get("/export/{job_id}/anki")
async def download_anki(job_id: str):
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")
    if job["status"] != "COMPLETE":
        raise HTTPException(
            status_code=409,
            detail=f"Job is not complete yet. Current status: {job['status']}",
        )
    if not job.get("export_path"):
        raise HTTPException(status_code=501, detail="Anki export is not available for this job.")
    return FileResponse(
        _safe_export_path(job["export_path"]),
        filename=f"vqg_{job_id}.apkg",
        media_type="application/octet-stream",
    )


@router.get("/export/{job_id}/html")
async def download_html(job_id: str):
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] != "COMPLETE":
        raise HTTPException(status_code=409, detail="Job not complete")
    if not job.get("html_export_path"):
        raise HTTPException(status_code=404, detail="HTML export not available for this job.")
    try:
        return FileResponse(
            _safe_export_path(job["html_export_path"]),
            filename=f"study_guide_{job_id}.html",
            media_type="text/html",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("DOWNLOAD_HTML_CRASH: %s", e)
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/export/{job_id}/pdf")
async def download_pdf(job_id: str):
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] != "COMPLETE":
        raise HTTPException(status_code=409, detail="Job not complete")
    if not job.get("pdf_export_path"):
        raise HTTPException(status_code=404, detail="PDF export not available for this job.")
    return FileResponse(
        _safe_export_path(job["pdf_export_path"]),
        filename=f"quiz_cards_{job_id[:8]}.pdf",
        media_type="application/pdf",
    )
