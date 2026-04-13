import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from the vqg/ root (one level up from backend/)
load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
GEMINI_FLASH_MODEL: str = os.getenv("GEMINI_FLASH_MODEL", "gemini-2.5-flash")
NANO_BANANA_MODEL: str = os.getenv("NANO_BANANA_MODEL", "gemini-3.1-flash-image-preview")
REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
STORAGE_PATH: str = os.getenv("STORAGE_PATH", "./storage")
DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./vqg.db")
MAX_IMAGES_PER_PDF: int = int(os.getenv("MAX_IMAGES_PER_PDF", "50"))
SSIM_PASS_THRESHOLD: float = float(os.getenv("SSIM_PASS_THRESHOLD", "0.82"))
# Scale factor for rendering PDF pages before diagram region detection.
# 2 → crisp enough for Gemini to read labels; crops are saved at this resolution.
PAGE_RENDER_SCALE: int = int(os.getenv("PAGE_RENDER_SCALE", "2"))

# Derived storage paths
UPLOADS_PATH = os.path.join(STORAGE_PATH, "uploads")
IMAGES_PATH = os.path.join(STORAGE_PATH, "images")
PROCESSED_PATH = os.path.join(STORAGE_PATH, "processed")
EXPORTS_PATH = os.path.join(STORAGE_PATH, "exports")

# SQLite DB path (strip sqlite:/// prefix)
DB_PATH: str = DATABASE_URL.replace("sqlite:///", "")
