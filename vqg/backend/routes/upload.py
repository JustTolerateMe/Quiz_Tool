import os
import shutil
import uuid

from fastapi import APIRouter, File, HTTPException, UploadFile

from backend.config import UPLOADS_PATH
from backend.models.db import create_job
from backend.workers.celery_app import parse_and_triage_task

router = APIRouter()

ALLOWED_CONTENT_TYPES = {"application/pdf", "application/x-pdf"}


@router.post("/upload")
async def upload_pdf(file: UploadFile = File(...)):
    # Validate file type
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

    create_job(job_id, safe_filename)
    parse_and_triage_task.delay(job_id, pdf_path)

    return {"job_id": job_id, "status": "QUEUED"}
