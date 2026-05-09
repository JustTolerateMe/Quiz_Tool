from fastapi import APIRouter, Header, HTTPException

from backend.models.db import get_job, get_jobs_for_user, get_queue_position

router = APIRouter()


@router.get("/jobs")
async def list_jobs(x_user_id: str = Header(None)):
    if not x_user_id:
        raise HTTPException(status_code=401, detail="Sign in to view your jobs.")
    return {"jobs": get_jobs_for_user(x_user_id)}


@router.get("/jobs/{job_id}")
async def get_job_status(job_id: str):
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")
    job["queue_position"] = get_queue_position(job_id)
    return job
