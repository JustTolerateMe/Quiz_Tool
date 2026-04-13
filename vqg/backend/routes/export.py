from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from backend.models.db import get_job

router = APIRouter()


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
            detail="Anki export is not yet implemented for this job. (Week 6 feature)",
        )
    return FileResponse(
        job["export_path"],
        filename=f"vqg_{job_id}.apkg",
        media_type="application/octet-stream",
    )
