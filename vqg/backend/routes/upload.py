import os
import shutil
import uuid

from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from backend.config import UPLOADS_PATH
from backend.main import limiter
from backend.models.db import create_job
from backend.workers.celery_app import parse_and_triage_task

router = APIRouter()

ALLOWED_CONTENT_TYPES = {"application/pdf", "application/x-pdf"}
MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB


@router.post("/upload")
@limiter.limit("10/hour")
async def upload_pdf(request: Request, file: UploadFile = File(...)):
    if file.content_type not in ALLOWED_CONTENT_TYPES and not (
        file.filename and file.filename.lower().endswith(".pdf")
    ):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    job_id = str(uuid.uuid4())
    safe_filename = os.path.basename(file.filename or "upload.pdf")
    pdf_path = os.path.join(UPLOADS_PATH, f"{job_id}_{safe_filename}")

    os.makedirs(UPLOADS_PATH, exist_ok=True)

    with open(pdf_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    if os.path.getsize(pdf_path) > MAX_UPLOAD_BYTES:
        os.remove(pdf_path)
        raise HTTPException(status_code=413, detail="File too large. Maximum size is 50 MB.")

    create_job(job_id, safe_filename)
    parse_and_triage_task.delay(job_id, pdf_path)

    return {"job_id": job_id, "status": "QUEUED"}
