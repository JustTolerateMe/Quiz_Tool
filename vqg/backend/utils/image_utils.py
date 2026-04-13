"""
image_utils.py — PIL helpers, text extraction, SSIM, and fallback overlay.

Week 1: get_surrounding_text only.
Week 4+: SSIM comparison and numbered box overlay.
"""

import re


def get_surrounding_text(full_text: str, page_number: int) -> str:
    """
    Extract a snippet of text surrounding the image's page from the full parsed PDF text.

    marker-pdf embeds page markers in the output text. This helper finds the
    text block nearest to the image's page number. Returns up to 500 characters.
    """
    if not full_text:
        return ""

    # marker-pdf inserts page markers like "## Page N" or just separates by \n\n
    # Try to find a page-boundary marker for the given page number
    page_patterns = [
        rf"(?:page|##\s*page)\s*{page_number}\b",
        rf"\bpage\s+{page_number}\b",
    ]

    best_start = -1
    for pattern in page_patterns:
        match = re.search(pattern, full_text, re.IGNORECASE)
        if match:
            best_start = match.start()
            break

    if best_start == -1:
        # No page marker found — return a proportional slice of the full text
        total = len(full_text)
        if total == 0:
            return ""
        # Rough position: page_number / (page_number + 5) of document
        approx_pos = min(int((page_number / max(page_number + 5, 1)) * total), total - 1)
        return full_text[max(0, approx_pos - 250): approx_pos + 250].strip()

    return full_text[best_start: best_start + 500].strip()


# ---------------------------------------------------------------------------
# SSIM comparison
# ---------------------------------------------------------------------------

# approximate_location → (x_fraction, y_fraction) from top-left
_LOCATION_GRID: dict[str, tuple[float, float]] = {
    "TOP_LEFT":    (0.15, 0.15),
    "TOP_CENTER":  (0.50, 0.10),
    "TOP_RIGHT":   (0.85, 0.15),
    "MID_LEFT":    (0.10, 0.50),
    "CENTER":      (0.50, 0.50),
    "MID_RIGHT":   (0.90, 0.50),
    "BOT_LEFT":    (0.15, 0.85),
    "BOT_CENTER":  (0.50, 0.90),
    "BOT_RIGHT":   (0.85, 0.85),
}


def compute_ssim(original_path: str, processed_path: str) -> float:
    """
    Compute SSIM between the original and inpainted image.

    Both images are converted to grayscale. The processed image is resized
    to match the original dimensions before comparison.

    Returns a float in [0, 1]. Higher = more similar.
    """
    import numpy as np
    from PIL import Image
    from skimage.metrics import structural_similarity

    orig = Image.open(original_path).convert("L")
    proc = Image.open(processed_path).convert("L")

    if proc.size != orig.size:
        proc = proc.resize(orig.size, Image.LANCZOS)

    orig_arr = np.array(orig)
    proc_arr = np.array(proc)

    score, _ = structural_similarity(orig_arr, proc_arr, full=True)
    return float(score)


# ---------------------------------------------------------------------------
# Numbered box overlay
# ---------------------------------------------------------------------------

def draw_numbered_boxes(image, labels: list[dict]) -> tuple:
    """
    Draw numbered white boxes on an image at the approximate_location of each label.

    Args:
        image:  PIL.Image — the original (or a copy).
        labels: list of label dicts from label_extractor (each has approximate_location,
                meaning, id).

    Returns:
        (annotated_image, label_map)
        label_map: {1: "meaning text", 2: "meaning text", ...}  (1-indexed)
    """
    from PIL import ImageDraw, ImageFont

    img = image.copy()
    draw = ImageDraw.Draw(img)
    w, h = img.size

    # Box dimensions scaled to image size
    box_w = max(40, int(w * 0.07))
    box_h = max(20, int(h * 0.04))

    label_map: dict[int, str] = {}

    for number, label in enumerate(labels, start=1):
        loc = label.get("approximate_location", "CENTER")
        fx, fy = _LOCATION_GRID.get(loc, (0.5, 0.5))

        cx = int(fx * w)
        cy = int(fy * h)

        x0 = max(0, cx - box_w // 2)
        y0 = max(0, cy - box_h // 2)
        x1 = min(w, x0 + box_w)
        y1 = min(h, y0 + box_h)

        draw.rectangle([x0, y0, x1, y1], fill="white", outline="black", width=2)

        text = str(number)
        try:
            font = ImageFont.truetype("arial.ttf", size=max(12, box_h - 4))
        except OSError:
            font = ImageFont.load_default()

        bbox = draw.textbbox((0, 0), text, font=font)
        tx = x0 + (box_w - (bbox[2] - bbox[0])) // 2
        ty = y0 + (box_h - (bbox[3] - bbox[1])) // 2
        draw.text((tx, ty), text, fill="black", font=font)

        label_map[number] = label.get("meaning", label.get("text", f"Structure {number}"))

    return img, label_map


# ---------------------------------------------------------------------------
# Numbered overlay (primary path — replaces inpainting)
# ---------------------------------------------------------------------------

def draw_numbered_overlay(image, labels: list[dict]) -> tuple:
    """
    Draw small numbered badges over each label's text position, preserving the
    original callout arrows. Numbers sit exactly where the text was.

    Uses x,y coordinates from label_extractor (normalized 0.0–1.0). Falls back
    to the _LOCATION_GRID if x/y are missing.

    Args:
        image:  PIL.Image — the original diagram (not modified in place).
        labels: list of label dicts from label_extractor. Each should have:
                  x, y (float fractions), meaning, id.

    Returns:
        (annotated_image, label_map)
        label_map: {1: "meaning text", 2: "meaning text", ...}  (1-indexed)
    """
    from PIL import ImageDraw, ImageFont

    img = image.copy()
    draw = ImageDraw.Draw(img)
    w, h = img.size

    # Badge diameter: small enough not to cover adjacent structures
    diameter = max(24, int(min(w, h) * 0.025))
    radius = diameter // 2
    font_size = max(10, int(diameter * 0.55))

    try:
        font = ImageFont.truetype("arial.ttf", size=font_size)
    except OSError:
        font = ImageFont.load_default()

    label_map: dict[int, str] = {}

    for number, label in enumerate(labels, start=1):
        # Use precise coordinates if available, fall back to grid
        if "x" in label and "y" in label:
            cx = int(float(label["x"]) * w)
            cy = int(float(label["y"]) * h)
        else:
            loc = label.get("approximate_location", "CENTER")
            fx, fy = _LOCATION_GRID.get(loc, (0.5, 0.5))
            cx = int(fx * w)
            cy = int(fy * h)

        # Clamp center to image bounds with radius margin
        cx = max(radius, min(w - radius, cx))
        cy = max(radius, min(h - radius, cy))

        x0, y0 = cx - radius, cy - radius
        x1, y1 = cx + radius, cy + radius

        # Erase original text with a white rectangle before drawing the badge.
        # Sized to cover typical callout text in medical diagrams.
        erase_w = max(80, int(w * 0.14))
        erase_h = max(18, int(h * 0.028))
        ex0 = max(0, cx - erase_w // 2)
        ey0 = max(0, cy - erase_h // 2)
        ex1 = min(w, ex0 + erase_w)
        ey1 = min(h, ey0 + erase_h)
        draw.rectangle([ex0, ey0, ex1, ey1], fill="white")

        # Draw badge: yellow fill, dark border
        draw.ellipse([x0, y0, x1, y1], fill="#FFE066", outline="#333333", width=max(1, diameter // 12))

        # Center number text in badge
        text = str(number)
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        draw.text((cx - tw // 2, cy - th // 2), text, fill="#1a1a1a", font=font)

        label_map[number] = label.get("meaning", label.get("text", f"Structure {number}"))

    return img, label_map
