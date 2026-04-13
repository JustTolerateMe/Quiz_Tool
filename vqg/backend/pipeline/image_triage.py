"""
image_triage.py — Classify each extracted image using Gemini Vision.

Decides: is this worth quizzing on? If so, what kind of quiz?
Returns a triage dict or None (skip this image).
"""

import logging
from typing import Optional

from backend.utils.gemini_client import call_vision_json

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Triage prompt — exact text from VQG Implementation Guide §5 Step 2
# ---------------------------------------------------------------------------
TRIAGE_PROMPT = """You are an educational image classifier for a quiz generation system.

Analyze this image and return ONLY a JSON object with no other text.

Return this exact structure:
{
  "category": "<one of: ANATOMICAL_DIAGRAM | CELLULAR_MOLECULAR | CHEMICAL_STRUCTURE | FLOWCHART_PROCESS | GEOGRAPHIC_MAP | ENGINEERING_SCHEMATIC | CLINICAL_PHOTO | HISTOLOGY_MICROSCOPY | DATA_VISUALIZATION | TABLE_IMAGE | PROCEDURAL_STEP | TIMELINE | COMPARATIVE_DIAGRAM | DECORATIVE | LOGO_WATERMARK_HEADER | PORTRAIT_PHOTO | SPLASH_IMAGE | ICON_LEGEND_ALONE | LOW_QUALITY>",
  "has_labels": <true|false>,
  "label_density": "<LOW|MEDIUM|HIGH>",
  "background_type": "<WHITE|LIGHT|DARK|PHOTOGRAPHIC|COMPLEX>",
  "domain": "<MEDICINE|BIOLOGY|CHEMISTRY|GEOGRAPHY|ENGINEERING|PHYSICS|HISTORY|OTHER>",
  "confidence": <0.0 to 1.0>,
  "worth_quizzing": <true|false>,
  "reason": "<one sentence explaining your classification>",
  "estimated_label_count": <integer>,
  "quiz_format": "<LABEL_BLANK | SEQUENCE_ORDER | DATA_READING | REGION_CLICK | CONTEXT_MCQ | SKIP>"
}

Rules:
- Set worth_quizzing=false if: purely decorative, logo, portrait photo, no educational content whatsoever
- Set worth_quizzing=true for: any diagram with labels, any process/flowchart, any clinical photo showing technique or positioning, any radiograph, any microscopy image
- Set confidence < 0.7 if image is ambiguous, heavily degraded, or you genuinely cannot tell what it shows
- quiz_format LABEL_BLANK = image has callout labels or arrows pointing to named structures → ask student to identify them
- quiz_format SEQUENCE_ORDER = image shows a process, mechanism, or sequence of steps (flowchart, procedural diagram, pathway) → ask about steps, order, and mechanisms
- quiz_format CONTEXT_MCQ = image has educational content but no callout labels to blank (clinical photos showing positioning/technique, equipment diagrams, X-ray technique diagrams) → generate MCQ from what is visible
- quiz_format DATA_READING = chart or graph with data values → ask student to read values
- quiz_format REGION_CLICK = geographic or regional map → ask to identify a region
- quiz_format SKIP = do not process this image at all
- CLINICAL_PHOTO of patient positioning, surgical technique, or equipment use → worth_quizzing=true, quiz_format=CONTEXT_MCQ
- FLOWCHART_PROCESS or PROCEDURAL_STEP with clear step sequence → worth_quizzing=true, quiz_format=SEQUENCE_ORDER"""

# Required keys that must be present in a valid triage response
_REQUIRED_KEYS = {
    "category", "has_labels", "label_density", "background_type",
    "domain", "confidence", "worth_quizzing", "reason",
    "estimated_label_count", "quiz_format",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def triage_image(image_path: str) -> Optional[dict]:
    """
    Classify a single image.

    Returns:
        dict  — triage result if classification succeeded and confidence >= 0.5
        None  — if the API failed, response was malformed, or confidence < 0.5
                (caller treats None as SKIP)
    """
    try:
        result = call_vision_json(image_path, TRIAGE_PROMPT)
    except RuntimeError as e:
        logger.warning("triage_image: skipping %s — API failed: %s", image_path, e)
        return None

    # Validate response structure
    missing = _REQUIRED_KEYS - set(result.keys())
    if missing:
        logger.warning(
            "triage_image: skipping %s — response missing keys: %s",
            image_path, missing,
        )
        return None

    # Drop images with very low confidence even before routing
    if result.get("confidence", 0) < 0.5:
        logger.info(
            "triage_image: skipping %s — confidence %.2f < 0.5 (%s)",
            image_path, result["confidence"], result.get("reason", ""),
        )
        return None

    return result


def route_image(triage: dict) -> str:
    """
    Map a triage result to an action string.

    Returns one of: LABEL_BLANK | SEQUENCE_ORDER | DATA_READING |
                    REGION_CLICK | CONTEXT_MCQ | SKIP
    """
    if not triage.get("worth_quizzing", False):
        return "SKIP"

    # MLP policy: skip anything below 0.7 confidence (no human review queue yet)
    if triage.get("confidence", 0) < 0.7:
        return "SKIP"

    return triage.get("quiz_format", "SKIP")
