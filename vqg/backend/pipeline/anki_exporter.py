"""
anki_exporter.py — Build an Anki .apkg deck from processed images and quiz questions.

Uses genanki to produce a valid .apkg file with embedded images.
One card per QuizQuestion: front = blanked diagram, back = answer + distractors + explanation.

genanki rules (from ARCHITECTURE.md):
- Package.media_files must contain ABSOLUTE file paths — relative paths = missing images in Anki
- Card front uses {{Image}} field — genanki copies it into the .apkg media bundle
"""

import logging
import os

import genanki

from backend.config import EXPORTS_PATH

logger = logging.getLogger(__name__)

# Stable model/deck IDs — generated once, never change (genanki requires consistency)
_MODEL_ID = 1_607_392_319
_DECK_ID  = 2_059_400_110

# Card CSS — clean white background, image centred, answer highlighted
_CARD_CSS = """
.card {
    font-family: Arial, sans-serif;
    font-size: 16px;
    text-align: center;
    color: #1a1a1a;
    background-color: #ffffff;
    padding: 20px;
}
.question { font-size: 18px; font-weight: bold; margin-bottom: 16px; }
.answer   { color: #2e7d32; font-size: 20px; font-weight: bold; margin: 8px 0; }
.distractors { color: #888; font-size: 14px; margin-top: 8px; }
.explanation { font-size: 14px; color: #555; margin-top: 16px; border-top: 1px solid #eee; padding-top: 12px; }
img { max-width: 100%; max-height: 400px; margin-bottom: 16px; }
"""

_FRONT_TEMPLATE = "{{Question}}<br>{{Image}}"

_BACK_TEMPLATE = """{{FrontSide}}
<hr>
<div class="answer">✓ {{CorrectAnswer}}</div>
<div class="distractors">Also consider: {{Distractors}}</div>
<div class="explanation">{{Explanation}}</div>
"""


def _make_model() -> genanki.Model:
    return genanki.Model(
        _MODEL_ID,
        "VQG Diagram MCQ",
        fields=[
            {"name": "Question"},
            {"name": "Image"},
            {"name": "CorrectAnswer"},
            {"name": "Distractors"},
            {"name": "Explanation"},
            {"name": "Difficulty"},
            {"name": "LabelId"},
        ],
        templates=[
            {
                "name": "VQG Card",
                "qfmt": _FRONT_TEMPLATE,
                "afmt": _BACK_TEMPLATE,
            }
        ],
        css=_CARD_CSS,
    )


def build_anki_deck(results: list[dict], job_id: str, pdf_filename: str) -> str:
    """
    Build a .apkg Anki deck from all processed images with questions.

    Args:
        results:      Full list of result dicts from the Celery pipeline.
                      Each item with route=LABEL_BLANK may have a "questions" list.
        job_id:       Used to name the output file and deck.
        pdf_filename: Shown as the deck name in Anki.

    Returns:
        Absolute path to the saved .apkg file.

    Raises:
        ValueError: if no questions are found across all results (nothing to export).
    """
    model = _make_model()
    deck_name = f"VQG — {os.path.splitext(pdf_filename)[0]}"
    deck = genanki.Deck(_DECK_ID, deck_name)

    media_files: list[str] = []
    card_count = 0

    for item in results:
        questions = item.get("questions")
        if not questions:
            continue

        # Text-only cards (CONTEXT_MCQ, TEXT_MCQ) carry no image
        if item.get("method") in ("context_mcq", "text_mcq"):
            image_tag = ""
        else:
            # Use processed image for the card front; fall back to original
            image_path = item.get("processed_path") or item.get("image_path")
            if not image_path or not os.path.isfile(image_path):
                logger.warning(
                    "build_anki_deck: image missing for item %s — skipping %d questions",
                    item.get("image_id", "?"), len(questions),
                )
                continue

            image_filename = os.path.basename(image_path)
            image_tag = f'<img src="{image_filename}">'

            # Register image for bundling (genanki needs absolute paths)
            if image_path not in media_files:
                media_files.append(os.path.abspath(image_path))

        for q in questions:
            structure_name = q.get("structure_name", "")
            question_text  = q.get("question", "")
            distractors    = q.get("distractors", [])
            difficulty     = q.get("difficulty", "MEDIUM")
            explanation    = q.get("explanation", "")
            label_id       = q.get("label_id", "")

            if not structure_name or not question_text:
                continue

            distractors_str = " | ".join(distractors)

            note = genanki.Note(
                model=model,
                fields=[
                    question_text,
                    image_tag,
                    structure_name,
                    distractors_str,
                    explanation,
                    difficulty,
                    label_id,
                ],
                # Stable GUID so re-importing the same PDF doesn't duplicate cards
                guid=genanki.guid_for(job_id, label_id, structure_name),
            )
            deck.add_note(note)
            card_count += 1

    if card_count == 0:
        raise ValueError(f"No quiz questions to export for job {job_id}")

    # Save .apkg
    job_exports_dir = os.path.join(EXPORTS_PATH, job_id)
    os.makedirs(job_exports_dir, exist_ok=True)
    output_path = os.path.abspath(os.path.join(job_exports_dir, "vqg_export.apkg"))

    package = genanki.Package(deck)
    package.media_files = media_files
    package.write_to_file(output_path)

    logger.info(
        "build_anki_deck: wrote %d cards to %s (%d images)",
        card_count, output_path, len(media_files),
    )
    return output_path
