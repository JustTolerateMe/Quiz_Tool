"""
quiz_generator.py — Generate MCQ flashcard questions from labelled diagrams.

Only called for images routed to LABEL_BLANK that have labels extracted.
Takes the processed (inpainted/fallback) image + label data and asks Gemini
Flash to generate one MCQ per significant label, with 3 plausible distractors.

Returns a list of QuizQuestion-compatible dicts. Returns [] on any failure so
the Celery worker can continue — an image with no questions is not a fatal error.
"""

import logging
from backend.utils.gemini_client import call_vision_json

logger = logging.getLogger(__name__)

# Difficulty from triage label_density
_DIFFICULTY_MAP = {
    "HIGH": "HARD",
    "MEDIUM": "MEDIUM",
    "LOW": "EASY",
}

_REQUIRED_QUESTION_KEYS = {"label_id", "structure_name", "question", "distractors", "difficulty", "explanation"}


def _build_prompt(labels: dict, triage: dict, surrounding_text: str,
                  target_label_ids: list[str] | None = None) -> tuple[list[dict], str]:
    """
    Select target labels and build the batch quiz generation prompt.

    Args:
        target_label_ids: When provided, quiz exactly these label IDs in this order.
                          This should match the numbered badges drawn on the image.
                          When None, falls back to suggested_quiz_labels from extraction.

    Returns:
        (target_labels, prompt_string)
        target_labels — the subset of label dicts we asked questions about
    """
    all_labels: list[dict] = labels.get("labels", [])

    if target_label_ids is not None:
        # Use exactly the labels that were numbered on the image, preserving order
        id_to_label = {lb["id"]: lb for lb in all_labels}
        target_labels = [id_to_label[lid] for lid in target_label_ids if lid in id_to_label]
    else:
        suggested_ids: list[str] = labels.get("suggested_quiz_labels", [])
        if suggested_ids:
            target_labels = [lb for lb in all_labels if lb.get("id") in suggested_ids]
        else:
            target_labels = all_labels

    if not target_labels:
        return [], ""

    domain = triage.get("domain", "BIOLOGY")
    category = triage.get("category", "ANATOMICAL_DIAGRAM")

    context_snippet = surrounding_text[:300].strip() if surrounding_text else "No additional context."

    # Build label list for prompt
    label_lines = []
    for i, lb in enumerate(target_labels, start=1):
        text = lb.get("text", "")
        meaning = lb.get("meaning", "")
        label_id = lb.get("id", f"L{i}")
        label_lines.append(f'{i}. id="{label_id}", text="{text}", meaning="{meaning}"')
    label_block = "\n".join(label_lines)

    prompt = f"""You are generating MCQ flashcard questions for a {domain} student studying from a diagram.

DIAGRAM CONTEXT: {context_snippet}
IMAGE CATEGORY: {category}

For each label listed below, generate one MCQ question. Return ONLY a JSON array — no other text:

[
  {{
    "label_id": "<label id from the list>",
    "structure_name": "<exact label text — this is the correct answer>",
    "question": "<a clear, specific question the student sees — do NOT include the structure name in the question>",
    "distractors": ["<wrong answer 1>", "<wrong answer 2>", "<wrong answer 3>"],
    "difficulty": "<EASY|MEDIUM|HARD>",
    "explanation": "<1-2 sentences: what this structure is and why it matters clinically or scientifically>"
  }}
]

Labels to quiz:
{label_block}

Rules:
- question must NOT contain the structure_name — the student is identifying it from the diagram
- distractors must be anatomically/scientifically plausible for {domain} — real structures, not random words
- distractors must be structures NOT visible at that location in the image (plausible wrong answers)
- difficulty: calibrate individually per structure — EASY = any structure a first-year {domain} student knows by name (e.g. 'Frontal bone', 'Mitochondria'); MEDIUM = requires dedicated study (e.g. 'Lesser wing of sphenoid', 'Lamina papyracea'); HARD = clinical/functional nuance, rare structure, or easily confused pair (e.g. 'Crista galli', 'Superior orbital fissure')
- explanation should mention the structure's function, clinical relevance, or a memorable distinguishing feature
- Return exactly one JSON object per label in the same order. Return [] if you cannot generate valid questions."""

    return target_labels, prompt


def generate_quiz(
    image_path: str,
    labels: dict,
    surrounding_text: str,
    triage: dict,
    target_label_ids: list[str] | None = None,
) -> list[dict]:
    """
    Generate MCQ questions for the significant labels in a diagram.

    Args:
        image_path:      Path to the processed (inpainted or fallback) image.
        labels:          Label extraction result dict — must have "labels" and
                         "suggested_quiz_labels" keys.
        surrounding_text: Text from the PDF page — used as context for distractors.
        triage:          Triage result dict — provides domain, category, label_density.

    Returns:
        List of QuizQuestion-compatible dicts. May be empty if generation fails
        or all results fail validation. Caller should continue either way.
    """
    target_labels, prompt = _build_prompt(labels, triage, surrounding_text, target_label_ids)

    if not target_labels:
        logger.info("generate_quiz: no target labels for %s — skipping", image_path)
        return []

    try:
        raw_result = call_vision_json(image_path, prompt)
    except RuntimeError as e:
        logger.warning("generate_quiz: API failed for %s: %s", image_path, e)
        return []

    # The response should be a list. call_vision_json returns a dict, but the
    # prompt asks for an array — handle both wrapping patterns.
    if isinstance(raw_result, list):
        questions_raw = raw_result
    elif isinstance(raw_result, dict):
        # Gemini sometimes wraps arrays: {"questions": [...]} or {"data": [...]}
        for key in ("questions", "data", "items", "results"):
            if isinstance(raw_result.get(key), list):
                questions_raw = raw_result[key]
                break
        else:
            logger.warning(
                "generate_quiz: unexpected response shape for %s: %s",
                image_path, list(raw_result.keys()),
            )
            return []
    else:
        logger.warning("generate_quiz: non-list/dict response for %s", image_path)
        return []

    # Validate each question
    validated: list[dict] = []
    for q in questions_raw:
        if not isinstance(q, dict):
            continue
        missing = _REQUIRED_QUESTION_KEYS - set(q.keys())
        if missing:
            logger.debug("generate_quiz: question missing keys %s — dropped", missing)
            continue
        if not isinstance(q.get("distractors"), list) or len(q["distractors"]) != 3:
            logger.debug(
                "generate_quiz: question for %s has %d distractors (need 3) — dropped",
                q.get("label_id"), len(q.get("distractors", [])),
            )
            continue
        if not q.get("structure_name") or not q.get("question"):
            logger.debug("generate_quiz: question for %s has empty required fields — dropped", q.get("label_id"))
            continue
        validated.append(q)

    logger.info(
        "generate_quiz: %d/%d questions validated for %s",
        len(validated), len(questions_raw), image_path,
    )
    return validated
