import os
import logging
import traceback
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from backend.models.db import get_job

router = APIRouter()
logger = logging.getLogger(__name__)


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
        raise HTTPException(
            status_code=501,
            detail="Anki export is not available for this job.",
        )
    return FileResponse(
        job["export_path"],
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

    try:
        path = os.path.normpath(job["html_export_path"])
        if not os.path.exists(path):
            logger.error(f"HTML Export Error: File not found at {path}")
            raise HTTPException(status_code=404, detail="HTML file missing on disk")
            
        return FileResponse(
            path,
            filename=f"study_guide_{job_id}.html",
            media_type="text/html",
        )
    except Exception as e:
        logger.error(f"DOWNLOAD_HTML_CRASH: {str(e)}")
        traceback.print_exc()
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/export/{job_id}/pdf")
async def download_pdf(job_id: str):
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] != "COMPLETE":
        raise HTTPException(status_code=409, detail="Job not complete")
    if not job.get("pdf_export_path"):
        raise HTTPException(status_code=404, detail="PDF export not available for this job")
    path = os.path.normpath(job["pdf_export_path"])
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="PDF file missing on disk")
    return FileResponse(
        path,
        filename=f"quiz_cards_{job_id[:8]}.pdf",
        media_type="application/pdf",
    )
