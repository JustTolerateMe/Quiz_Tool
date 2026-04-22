import logging
import os
import textwrap

from fpdf import FPDF

from backend.config import EXPORTS_PATH

logger = logging.getLogger(__name__)

# A4 dimensions in mm
PAGE_W = 210
PAGE_H = 297
MARGIN = 12
CARD_H = (PAGE_H - MARGIN * 3) / 2  # two cards per page
IMG_MAX_H = 55
IMG_MAX_W = PAGE_W - MARGIN * 2


def build_pdf_export(results: list[dict], job_id: str, pdf_filename: str) -> str:
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=False)
    pdf.set_margins(MARGIN, MARGIN, MARGIN)

    cards = _collect_cards(results)
    if not cards:
        raise ValueError("No questions to export as PDF")

    pdf.set_title(f"Quiz Cards — {pdf_filename}")
    pdf.add_page()
    card_top = MARGIN
    slot = 0  # 0 = top half, 1 = bottom half

    for i, card in enumerate(cards):
        if slot == 2:
            pdf.add_page()
            slot = 0
            card_top = MARGIN

        y = card_top + slot * (CARD_H + MARGIN)
        _draw_card(pdf, card, x=MARGIN, y=y, w=PAGE_W - MARGIN * 2, h=CARD_H)
        slot += 1

    out_dir = os.path.join(EXPORTS_PATH, job_id)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "quiz_cards.pdf")
    pdf.output(out_path)
    logger.info("job %s: PDF export saved (%d cards) → %s", job_id, len(cards), out_path)
    return out_path


# ── helpers ────────────────────────────────────────────────────────────────

def _collect_cards(results: list[dict]) -> list[dict]:
    cards = []
    for item in results:
        questions = item.get("questions") or []
        if not questions:
            continue
        image_path = item.get("processed_path") or item.get("image_path")
        for q in questions:
            cards.append({"q": q, "image_path": image_path, "route": item.get("route", "")})
    return cards


def _draw_card(pdf: FPDF, card: dict, x: float, y: float, w: float, h: float):
    q = card["q"]
    image_path = card["image_path"]
    has_image = image_path and os.path.exists(str(image_path))

    # outer border
    pdf.set_draw_color(203, 213, 225)  # slate-300
    pdf.rect(x, y, w, h)

    cursor = y + 3

    # ── QUESTION HALF ──────────────────────────────────────────────────────
    # Question label
    pdf.set_font("Helvetica", "B", 7)
    pdf.set_text_color(99, 102, 241)   # indigo-500
    pdf.set_xy(x + 3, cursor)
    pdf.cell(w - 6, 4, "QUESTION", ln=True)
    cursor += 5

    # Image
    if has_image:
        try:
            img_y = cursor
            pdf.image(str(image_path), x=x + 3, y=img_y, w=min(IMG_MAX_W - 6, w - 6), h=0)
            # measure actual rendered height (fpdf scales proportionally when h=0)
            from PIL import Image as PILImage
            with PILImage.open(str(image_path)) as im:
                iw, ih = im.size
            scale = min((w - 6) / iw, IMG_MAX_H / ih)
            rendered_h = ih * scale
            cursor += rendered_h + 2
        except Exception as e:
            logger.warning("pdf_exporter: could not embed image %s: %s", image_path, e)

    # Question text
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(15, 23, 42)     # slate-900
    question_text = q.get("question", "")
    pdf.set_xy(x + 3, cursor)
    pdf.multi_cell(w - 6, 5, question_text)
    cursor = pdf.get_y() + 2

    # ── FOLD LINE ──────────────────────────────────────────────────────────
    fold_y = y + h / 2
    pdf.set_draw_color(148, 163, 184)  # slate-400
    pdf.dashed_line(x + 3, fold_y, x + w - 3, fold_y, dash_length=2, space_length=2)
    pdf.set_font("Helvetica", "", 6)
    pdf.set_text_color(148, 163, 184)
    pdf.set_xy(x + w - 20, fold_y - 3)
    pdf.cell(17, 3, "- - fold - -", align="R")

    # ── ANSWER HALF ────────────────────────────────────────────────────────
    cursor = fold_y + 3

    pdf.set_font("Helvetica", "B", 7)
    pdf.set_text_color(16, 185, 129)   # emerald-500
    pdf.set_xy(x + 3, cursor)
    pdf.cell(w - 6, 4, "ANSWER", ln=True)
    cursor += 5

    # Correct answer
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(5, 150, 105)    # emerald-600
    pdf.set_xy(x + 3, cursor)
    pdf.multi_cell(w - 6, 5, q.get("structure_name", ""))
    cursor = pdf.get_y() + 2

    # Distractors A/B/C
    distractors = q.get("distractors", [])
    labels = ["A", "B", "C", "D"]
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(100, 116, 139)  # slate-500
    for label, d in zip(labels, distractors):
        pdf.set_xy(x + 3, cursor)
        pdf.multi_cell(w - 6, 4, f"{label}. {d}")
        cursor = pdf.get_y()
        if cursor > y + h - 8:
            break

    # Explanation
    explanation = q.get("explanation", "")
    if explanation and cursor < y + h - 10:
        cursor += 2
        pdf.set_font("Helvetica", "I", 7)
        pdf.set_text_color(148, 163, 184)  # slate-400
        pdf.set_xy(x + 3, cursor)
        # truncate explanation so it doesn't overflow the card
        wrapped = textwrap.shorten(explanation, width=160, placeholder="…")
        pdf.multi_cell(w - 6, 3.5, wrapped)
