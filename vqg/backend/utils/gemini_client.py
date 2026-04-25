"""
gemini_client.py — Central Gemini API wrapper using the google-genai SDK.

ALL Gemini API calls in the project go through this module.
No other module should import from google.genai directly.

SDK: google-genai (official, GA as of May 2025)
  from google import genai
  from google.genai import types
  client = genai.Client(api_key=...)

Models:
  Flash (vision + text): gemini-3-flash-preview    (from config)
  Image editing:         gemini-3.1-flash-image-preview  (from config)
"""

import json
import os
import re
import threading
import time
import logging
from pathlib import Path

from google import genai
from google.genai import types

from backend.config import GEMINI_API_KEY, GEMINI_FLASH_MODEL

logger = logging.getLogger(__name__)

# Module-level client — instantiated once, reused across calls
_client = genai.Client(api_key=GEMINI_API_KEY)

# ---------------------------------------------------------------------------
# Rate limiter — thread-safe, reads RPM from env so it's tunable per worker.
# Default 30 RPM assumes 2 Celery worker processes sharing the 60 RPM free tier.
# ---------------------------------------------------------------------------
_RATE_LIMIT_RPM: int = int(os.getenv("GEMINI_RPM_PER_WORKER", "30"))
_MIN_INTERVAL: float = 60.0 / _RATE_LIMIT_RPM  # seconds between calls
_last_call_time: float = 0.0
_rate_lock = threading.Lock()


def _enforce_rate_limit() -> None:
    global _last_call_time
    with _rate_lock:
        elapsed = time.monotonic() - _last_call_time
        wait = _MIN_INTERVAL - elapsed
        if wait > 0:
            time.sleep(wait)
        _last_call_time = time.monotonic()


# ---------------------------------------------------------------------------
# JSON fence stripper
# ---------------------------------------------------------------------------
def strip_json_fences(text: str) -> str:
    """
    Strip markdown code fences from Gemini JSON responses.
    Handles:
      ```json\\n{...}\\n```
      ```\\n{...}\\n```
      {... raw JSON ...}
    """
    text = text.strip()
    # Remove opening fence (```json or ```)
    text = re.sub(r"^```(?:json)?\s*", "", text)
    # Remove closing fence
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Core vision + text call (returns JSON dict)
# ---------------------------------------------------------------------------
def call_vision_json(image_path: str, prompt: str) -> dict | list:
    """
    Send an image + prompt to Gemini Flash and parse the JSON response.

    Retries once on failure. Raises RuntimeError if both attempts fail.
    The caller is responsible for deciding whether to skip the image.
    """
    image_bytes = Path(image_path).read_bytes()
    mime_type = _infer_mime_type(image_path)

    last_error: Exception | None = None

    for attempt in range(2):
        try:
            _enforce_rate_limit()
            response = _client.models.generate_content(
                model=GEMINI_FLASH_MODEL,
                contents=[
                    types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                    prompt,
                ],
            )
            raw = response.text
            cleaned = strip_json_fences(raw)
            return json.loads(cleaned)

        except json.JSONDecodeError as e:
            last_error = e
            logger.warning(
                "call_vision_json: JSON parse failed (attempt %d/2) for %s: %s",
                attempt + 1, image_path, e,
            )
        except Exception as e:
            last_error = e
            logger.warning(
                "call_vision_json: API error (attempt %d/2) for %s: %s",
                attempt + 1, image_path, e,
            )

        if attempt == 0:
            time.sleep(2)  # brief pause before retry

    raise RuntimeError(
        f"call_vision_json failed after 2 attempts for {image_path}: {last_error}"
    )


# ---------------------------------------------------------------------------
# Core vision + text call (returns plain text)
# ---------------------------------------------------------------------------
def call_vision_text(image_path: str, prompt: str) -> str:
    """
    Send an image + prompt to Gemini Flash and return the raw text response.

    Retries once on failure. Raises RuntimeError if both attempts fail.
    """
    image_bytes = Path(image_path).read_bytes()
    mime_type = _infer_mime_type(image_path)

    last_error: Exception | None = None

    for attempt in range(2):
        try:
            _enforce_rate_limit()
            response = _client.models.generate_content(
                model=GEMINI_FLASH_MODEL,
                contents=[
                    types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                    prompt,
                ],
            )
            return response.text

        except Exception as e:
            last_error = e
            logger.warning(
                "call_vision_text: API error (attempt %d/2) for %s: %s",
                attempt + 1, image_path, e,
            )

        if attempt == 0:
            time.sleep(2)

    raise RuntimeError(
        f"call_vision_text failed after 2 attempts for {image_path}: {last_error}"
    )


# ---------------------------------------------------------------------------
# Text-only call (returns JSON dict/list — no image)
# ---------------------------------------------------------------------------
def call_text_json(prompt: str) -> dict | list:
    """
    Send a text-only prompt to Gemini Flash and parse the JSON response.

    Retries once on failure. Raises RuntimeError if both attempts fail.
    Uses the same rate limiter as vision calls.
    """
    last_error: Exception | None = None

    for attempt in range(2):
        try:
            _enforce_rate_limit()
            response = _client.models.generate_content(
                model=GEMINI_FLASH_MODEL,
                contents=[prompt],
            )
            raw = response.text
            cleaned = strip_json_fences(raw)
            return json.loads(cleaned)

        except json.JSONDecodeError as e:
            last_error = e
            logger.warning(
                "call_text_json: JSON parse failed (attempt %d/2): %s",
                attempt + 1, e,
            )
        except Exception as e:
            last_error = e
            logger.warning(
                "call_text_json: API error (attempt %d/2): %s",
                attempt + 1, e,
            )

        if attempt == 0:
            time.sleep(2)

    raise RuntimeError(f"call_text_json failed after 2 attempts: {last_error}")


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def _infer_mime_type(image_path: str) -> str:
    ext = Path(image_path).suffix.lower()
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
    }.get(ext, "image/png")
