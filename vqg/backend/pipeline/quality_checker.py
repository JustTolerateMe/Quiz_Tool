"""
quality_checker.py — SSIM-based quality gate for inpainted images.

Checks whether Nano Banana 2 actually changed the image (SSIM not too high)
and didn't destroy it (SSIM not too low). Falls back to numbered boxes on failure.
"""

import logging
import os

from backend.config import PROCESSED_PATH, SSIM_PASS_THRESHOLD
from backend.utils.image_utils import compute_ssim, draw_numbered_boxes

logger = logging.getLogger(__name__)

# Hard SSIM bounds (independent of SSIM_PASS_THRESHOLD)
_SSIM_TOO_LOW = 0.60   # inpainting destroyed the image
_SSIM_TOO_HIGH = 0.98  # inpainting did nothing


def check_inpaint_quality(original_path: str, processed_path: str) -> dict:
    """
    Compare original and inpainted image with SSIM.

    Returns:
        {
            "pass": bool,
            "ssim": float,
            "reason": str | None   # set only when failing
        }

    Fails if:
      - SSIM < 0.60  — inpainting altered the image too aggressively
      - SSIM > 0.98  — inpainting changed nothing (model did nothing useful)

    SSIM_PASS_THRESHOLD (0.82) from config is used for logging only — it's
    the target range centre, not an additional hard cutoff.
    """
    try:
        ssim = compute_ssim(original_path, processed_path)
    except Exception as e:
        logger.warning(
            "check_inpaint_quality: SSIM computation failed (%s vs %s): %s",
            original_path, processed_path, e,
        )
        return {"pass": False, "ssim": 0.0, "reason": f"ssim_error: {e}"}

    logger.info(
        "check_inpaint_quality: SSIM=%.4f (target ~%.2f) for %s",
        ssim, SSIM_PASS_THRESHOLD, os.path.basename(processed_path),
    )

    if ssim < _SSIM_TOO_LOW:
        reason = f"ssim_too_low ({ssim:.4f} < {_SSIM_TOO_LOW})"
        logger.warning("check_inpaint_quality: FAIL — %s", reason)
        return {"pass": False, "ssim": ssim, "reason": reason}

    if ssim > _SSIM_TOO_HIGH:
        reason = f"ssim_too_high ({ssim:.4f} > {_SSIM_TOO_HIGH}) — inpainting did nothing"
        logger.warning("check_inpaint_quality: FAIL — %s", reason)
        return {"pass": False, "ssim": ssim, "reason": reason}

    return {"pass": True, "ssim": ssim, "reason": None}


def apply_numbered_box_fallback(
    image_path: str, labels: dict | None, job_id: str
) -> tuple[str, dict]:
    """
    Draw numbered white boxes over the original image at label positions.

    Args:
        image_path: Absolute path to the original (unlabelled source) image.
        labels:     Label extraction result (may be None if extraction failed).
        job_id:     Job ID — output saved under PROCESSED_PATH/{job_id}/

    Returns:
        (output_path, label_map)
        label_map: {1: "meaning", 2: "meaning", ...}
        If labels is None, returns a single centred box with "?" and an empty map.
    """
    from PIL import Image

    img = Image.open(image_path)
    original_filename = os.path.basename(image_path)

    if labels and labels.get("labels"):
        label_list = labels["labels"]
        annotated, label_map = draw_numbered_boxes(img, label_list)
    else:
        # Extraction failed entirely — draw a single "?" box at centre
        annotated, label_map = draw_numbered_boxes(img, [
            {"approximate_location": "CENTER", "meaning": "Unknown structure", "text": "?"}
        ])
        label_map = {}  # no meaningful data to pass to quiz generator

    job_processed_dir = os.path.join(PROCESSED_PATH, job_id)
    os.makedirs(job_processed_dir, exist_ok=True)

    output_path = os.path.join(job_processed_dir, f"fallback_{original_filename}")

    # Ensure RGB before saving
    if annotated.mode in ("RGBA", "P"):
        annotated = annotated.convert("RGB")
    annotated.save(output_path)

    logger.info(
        "apply_numbered_box_fallback: saved fallback image to %s (%d labels)",
        output_path, len(label_map),
    )
    return output_path, label_map
