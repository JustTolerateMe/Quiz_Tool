from fastapi import APIRouter, HTTPException

from backend.models.db import get_job

router = APIRouter()


@router.get("/jobs/{job_id}")
async def get_job_status(job_id: str):
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")
    return job
