"""
label_extractor.py — Extract text labels from an educational diagram using Gemini Vision.

Only called for images routed to LABEL_BLANK.
Returns label positions and meanings so the inpainter knows what to remove
and the quiz generator knows what to ask about.
"""

import logging
from typing import Optional

from backend.utils.gemini_client import call_vision_json

logger = logging.getLogger(__name__)

# Exact prompt from VQG Implementation Guide §5 Step 3
LABEL_EXTRACTION_PROMPT = """You are analyzing an educational diagram to extract all text labels for a quiz system.

Look at this image carefully. Return ONLY a JSON object:

{
  "labels": [
    {
      "id": "L1",
      "text": "<exact text of the label as it appears>",
      "meaning": "<what this structure/component actually is, in plain English>",
      "approximate_location": "<TOP_LEFT|TOP_CENTER|TOP_RIGHT|MID_LEFT|CENTER|MID_RIGHT|BOT_LEFT|BOT_CENTER|BOT_RIGHT>",
      "label_type": "<CALLOUT_TEXT|NUMBERED_POINTER|INLINE_TEXT|ARROW_LABEL>",
      "x": <float 0.0-1.0, horizontal center of this label text as fraction of image width>,
      "y": <float 0.0-1.0, vertical center of this label text as fraction of image height>
    }
  ],
  "total_labels": <integer>,
  "suggested_quiz_labels": ["L1", "L3", "L5"],
  "notes": "<any special processing notes, e.g. 'labels overlap heavily near center'>"
}

Rules:
- Extract ALL visible text labels, not just prominent ones
- suggested_quiz_labels: pick the 3-6 most educationally significant labels to blank out
- Do not include axis labels on charts (those are processed differently)
- Do not include copyright notices or page numbers
- meaning should be a full anatomical/scientific name if applicable (e.g. "Mitral Valve" not just "valve")
- x and y are the center of the label TEXT itself (not where the arrow points to) — fraction of image width/height (0.0=left/top, 1.0=right/bottom)
- If you cannot determine the exact position, use your best estimate based on where the text visually appears"""

_REQUIRED_KEYS = {"labels", "total_labels", "suggested_quiz_labels"}


def extract_labels(image_path: str) -> Optional[dict]:
    """
    Extract all text labels from a diagram.

    Returns:
        dict  — label extraction result with labels[], total_labels, suggested_quiz_labels
        None  — if API failed or response was malformed (caller uses numbered box fallback)
    """
    try:
        result = call_vision_json(image_path, LABEL_EXTRACTION_PROMPT)
    except RuntimeError as e:
        logger.warning("extract_labels: API failed for %s: %s", image_path, e)
        return None

    missing = _REQUIRED_KEYS - set(result.keys())
    if missing:
        logger.warning("extract_labels: response missing keys %s for %s", missing, image_path)
        return None

    if not isinstance(result.get("labels"), list):
        logger.warning("extract_labels: labels field is not a list for %s", image_path)
        return None

    label_count = len(result["labels"])
    logger.info("extract_labels: found %d labels in %s", label_count, image_path)

    # Ensure every label has x,y coordinates — fall back to grid position if Gemini omitted them
    _GRID_FALLBACK: dict[str, tuple[float, float]] = {
        "TOP_LEFT": (0.15, 0.15), "TOP_CENTER": (0.50, 0.10), "TOP_RIGHT": (0.85, 0.15),
        "MID_LEFT": (0.10, 0.50), "CENTER": (0.50, 0.50), "MID_RIGHT": (0.90, 0.50),
        "BOT_LEFT": (0.15, 0.85), "BOT_CENTER": (0.50, 0.90), "BOT_RIGHT": (0.85, 0.85),
    }
    for lb in result["labels"]:
        if "x" not in lb or "y" not in lb:
            loc = lb.get("approximate_location", "CENTER")
            fx, fy = _GRID_FALLBACK.get(loc, (0.50, 0.50))
            lb.setdefault("x", fx)
            lb.setdefault("y", fy)

    # Filter INLINE_TEXT labels out of suggested_quiz_labels — these are titles,
    # headings, and captions, not structures worth quizzing.
    inline_ids = {
        lb["id"] for lb in result["labels"]
        if lb.get("label_type") == "INLINE_TEXT"
    }
    if inline_ids:
        before = len(result["suggested_quiz_labels"])
        result["suggested_quiz_labels"] = [
            lid for lid in result["suggested_quiz_labels"]
            if lid not in inline_ids
        ]
        removed = before - len(result["suggested_quiz_labels"])
        if removed:
            logger.info(
                "extract_labels: removed %d INLINE_TEXT label(s) from suggested list for %s",
                removed, image_path,
            )

    return result
