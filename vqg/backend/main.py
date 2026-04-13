import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import EXPORTS_PATH, IMAGES_PATH, PROCESSED_PATH, UPLOADS_PATH
from backend.models.db import init_db
from backend.routes import export, jobs, preview, upload

app = FastAPI(
    title="VQG — Visual Quiz Generator",
    description="Upload a PDF, get an Anki deck with visual quiz cards.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(upload.router)
app.include_router(jobs.router)
app.include_router(export.router)
app.include_router(preview.router)


@app.on_event("startup")
def startup() -> None:
    # Create storage directories if they don't exist
    for path in (UPLOADS_PATH, IMAGES_PATH, PROCESSED_PATH, EXPORTS_PATH):
        os.makedirs(path, exist_ok=True)
    # Initialise SQLite schema
    init_db()


@app.get("/health")
async def health():
    return {"status": "ok"}
