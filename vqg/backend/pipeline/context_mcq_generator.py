"""
context_mcq_generator.py — Generate MCQ questions from text-heavy slide images.

Called for images routed to CONTEXT_MCQ (lecture slides, text overlays, etc.)
Gemini Vision reads the visible text on the slide and generates factual MCQs.
Returns the same question dict shape as quiz_generator so anki_exporter works unchanged.
"""

import logging

from backend.utils.gemini_client import call_vision_json

logger = logging.getLogger(__name__)

_REQUIRED_KEYS = {"label_id", "structure_name", "question", "distractors", "difficulty", "explanation"}

_PROMPT = """You are generating MCQ flashcard questions for a {domain} student.

This image is a lecture slide. Read all the text visible in it carefully.

Generate 3-5 MCQ flashcard questions that test whether a student actually knows the facts — not whether they can read a slide.
Return ONLY a JSON array — no other text:

[
  {{
    "label_id": "<C1, C2, C3, ... in sequence>",
    "structure_name": "<the correct answer — a specific fact, term, value, or name>",
    "question": "<a standalone question a student could answer from memory — do NOT reference 'the slide', 'this image', 'according to', or any similar phrasing>",
    "distractors": ["<plausible wrong answer 1>", "<plausible wrong answer 2>", "<plausible wrong answer 3>"],
    "difficulty": "<EASY|MEDIUM|HARD>",
    "explanation": "<1-2 sentences: why this is correct and why it matters clinically or scientifically>"
  }}
]

Rules:
- Questions must stand alone — a student answering from memory should not need to see the slide
- NEVER start a question with "According to", "Based on the slide", "In this image", or similar — these are reading tests, not knowledge tests
- Only test facts that a {domain} student is expected to memorise (definitions, mechanisms, classifications, clinical relevance)
- Distractors must be plausible for a {domain} student — real terms or values, not random words
- Do NOT generate questions about slide formatting, titles alone, or presenter names
- difficulty: EASY = widely known foundational fact; MEDIUM = requires dedicated study; HARD = precise detail or easily confused nuance
- Return [] if the slide has no standalone testable facts (e.g. pure title slide, decorative, blank)"""


def generate_context_mcq(image_path: str, triage: dict) -> list[dict]:
    """
    Generate factual MCQ questions by having Gemini read the text in a slide image.

    Args:
        image_path: Path to the original (unmodified) slide image.
        triage:     Triage result dict — provides domain for prompt calibration.

    Returns:
        List of question dicts (same shape as quiz_generator output). May be empty.
    """
    domain = triage.get("domain", "BIOLOGY")
    prompt = _PROMPT.format(domain=domain)

    try:
        raw = call_vision_json(image_path, prompt)
    except RuntimeError as e:
        logger.warning("generate_context_mcq: API failed for %s: %s", image_path, e)
        return []

    if isinstance(raw, list):
        questions_raw = raw
    elif isinstance(raw, dict):
        for key in ("questions", "data", "items", "results"):
            if isinstance(raw.get(key), list):
                questions_raw = raw[key]
                break
        else:
            logger.warning("generate_context_mcq: unexpected response shape for %s: %s",
                           image_path, list(raw.keys()))
            return []
    else:
        logger.warning("generate_context_mcq: non-list/dict response for %s", image_path)
        return []

    validated = []
    for q in questions_raw:
        if not isinstance(q, dict):
            continue
        missing = _REQUIRED_KEYS - set(q.keys())
        if missing:
            logger.debug("generate_context_mcq: question missing keys %s — dropped", missing)
            continue
        if not isinstance(q.get("distractors"), list) or len(q["distractors"]) != 3:
            continue
        if not q.get("structure_name") or not q.get("question"):
            continue
        validated.append(q)

    logger.info("generate_context_mcq: %d/%d questions validated for %s",
                len(validated), len(questions_raw), image_path)
    return validated
