"""
inpainter.py — Remove text labels from educational diagrams using Nano Banana 2.

Only called for images routed to LABEL_BLANK.
Returns {success, output_path} so the caller can decide whether to run the
quality check or fall straight to the numbered box fallback.
"""

import logging
import os

from backend.config import PROCESSED_PATH
from backend.utils.gemini_client import call_image_edit

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Category-specific inpainting prompts (from Implementation Guide §5 Step 4)
# ---------------------------------------------------------------------------

_PROMPTS: dict[str, str] = {
    "ANATOMICAL_DIAGRAM": (
        "This is an anatomical diagram used for medical education. "
        "Remove ALL text labels, callout lines, numbered pointers, and annotation arrows. "
        "Keep all organ shapes, body structures, shading, and colour exactly as they are. "
        "Fill erased areas with the background colour or surrounding tissue colour so the "
        "diagram looks clean and unlabelled. Do not alter the anatomy itself in any way."
    ),
    "CELLULAR_MOLECULAR": (
        "This is a cellular or molecular biology diagram used for education. "
        "Remove ALL text labels and annotation arrows that point to specific structures. "
        "Preserve all membranes, organelles, pathway arrows (flow arrows), and molecular "
        "shapes exactly as they are. Fill erased areas seamlessly with the surrounding "
        "background colour."
    ),
    "CHEMICAL_STRUCTURE": (
        "This is a chemical structure diagram. "
        "Remove ONLY the atom/group text labels (e.g. 'CH3', 'OH', 'NH2', element symbols). "
        "PRESERVE every bond line, ring structure, stereochemistry wedge, and dashed bond "
        "exactly as drawn — do not touch the structural skeleton. "
        "Fill erased text areas with the background colour only."
    ),
    "ENGINEERING_SCHEMATIC": (
        "This is an engineering or physics schematic diagram. "
        "Remove component labels and dimension annotations only. "
        "PRESERVE all force arrows, velocity vectors, structural lines, and component shapes "
        "exactly as drawn. Fill erased label areas with the background colour."
    ),
    "FLOWCHART_PROCESS": (
        "This is a flowchart or process diagram used for education. "
        "Blank out the text INSIDE each box or decision diamond, replacing it with white fill. "
        "Keep all boxes, arrows, flow lines, and the overall structure completely intact. "
        "Do not remove or alter any shapes or connectors."
    ),
    "HISTOLOGY_MICROSCOPY": (
        "This is a histology or microscopy image with annotation overlays. "
        "Remove ONLY the annotation text labels and pointer lines that have been overlaid on "
        "the photograph. Preserve the underlying photographic image with all its tissue "
        "detail exactly as it is."
    ),
    "CLINICAL_PHOTO": (
        "This is a clinical photograph with annotation overlays. "
        "Remove ONLY the annotation text labels and pointer lines overlaid on the image. "
        "Preserve the underlying clinical photograph completely unchanged."
    ),
}

_DEFAULT_PROMPT = (
    "This is an educational diagram. "
    "Remove ALL visible text labels, callout lines, and annotation arrows. "
    "Keep the underlying diagram structure, shapes, and colours intact. "
    "Fill erased areas with the surrounding background colour so the image looks clean."
)


def _build_inpaint_prompt(triage: dict, labels: dict | None) -> str:
    """Select the category-specific prompt and optionally append label hints."""
    category = triage.get("category", "")
    base_prompt = _PROMPTS.get(category, _DEFAULT_PROMPT)

    if labels and labels.get("labels"):
        label_texts = [lb.get("text", "") for lb in labels["labels"] if lb.get("text")]
        if label_texts:
            hint = "Labels to remove include: " + ", ".join(f'"{t}"' for t in label_texts[:10])
            base_prompt = base_prompt + "\n\n" + hint

    return base_prompt


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def inpaint_labels(image_path: str, triage: dict, labels: dict | None, job_id: str) -> dict:
    """
    Remove text labels from a diagram using Nano Banana 2.

    Args:
        image_path: Absolute path to the source image.
        triage:     Triage result dict — used to select the category-specific prompt.
        labels:     Label extraction result (may be None if extraction failed).
        job_id:     Job ID — output saved under PROCESSED_PATH/{job_id}/

    Returns:
        {
            "success": True,
            "output_path": "<absolute path to the saved processed image>"
        }
        or
        {
            "success": False,
            "output_path": None
        }
    """
    prompt = _build_inpaint_prompt(triage, labels)

    try:
        pil_image = call_image_edit(image_path, prompt)
    except Exception as e:
        logger.warning("inpaint_labels: call_image_edit raised for %s: %s", image_path, e)
        return {"success": False, "output_path": None}

    if pil_image is None:
        logger.warning("inpaint_labels: Nano Banana 2 returned no image for %s", image_path)
        return {"success": False, "output_path": None}

    # Save to PROCESSED_PATH/{job_id}/
    job_processed_dir = os.path.join(PROCESSED_PATH, job_id)
    os.makedirs(job_processed_dir, exist_ok=True)

    original_filename = os.path.basename(image_path)
    output_path = os.path.join(job_processed_dir, original_filename)

    try:
        # Convert to RGB before saving as JPEG in case model returned RGBA
        if pil_image.mode in ("RGBA", "P"):
            pil_image = pil_image.convert("RGB")
        pil_image.save(output_path)
    except Exception as e:
        logger.warning("inpaint_labels: could not save processed image %s: %s", output_path, e)
        return {"success": False, "output_path": None}

    logger.info("inpaint_labels: saved processed image to %s", output_path)
    return {"success": True, "output_path": output_path}
