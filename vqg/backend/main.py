import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from backend.config import EXPORTS_PATH, IMAGES_PATH, PROCESSED_PATH, UPLOADS_PATH
from backend.models.db import init_db
from backend.routes import export, jobs, preview, review, upload

_ALLOWED_ORIGINS = os.getenv(
    "ALLOWED_ORIGINS", "http://localhost:3000"
).split(",")

limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="VQG — Visual Quiz Generator",
    description="Upload a PDF, get an Anki deck with visual quiz cards.",
    version="0.1.0",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(upload.router)
app.include_router(jobs.router)
app.include_router(export.router)
app.include_router(preview.router)
app.include_router(review.router)


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
