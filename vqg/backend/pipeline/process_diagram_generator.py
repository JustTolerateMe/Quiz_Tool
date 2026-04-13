"""
process_diagram_generator.py — Generate MCQ questions from process/sequence diagrams.

Called for images routed to SEQUENCE_ORDER (flowcharts, biological pathways,
procedural step diagrams, mechanism diagrams).

Generates a mix of question types:
  - Step identification: "What happens at this stage?"
  - Mechanism: "Why does X occur here?"
  - Sequence: "What is the correct order of these events?"

Returns the same question dict shape as quiz_generator and context_mcq_generator
so anki_exporter and preview work unchanged.
"""

import logging

from backend.utils.gemini_client import call_vision_json

logger = logging.getLogger(__name__)

_REQUIRED_KEYS = {"label_id", "structure_name", "question", "distractors", "difficulty", "explanation"}

_PROMPT = """You are generating MCQ flashcard questions for a {domain} student.

This diagram shows a biological, scientific, or medical process — a sequence of steps,
a mechanism, or a pathway. Study it carefully: the arrows, labels, and order all carry meaning.

Generate 3-5 MCQ questions. Return ONLY a JSON array — no other text:

[
  {{
    "label_id": "<P1, P2, P3 ... in sequence>",
    "structure_name": "<the correct answer — a step name, molecule, enzyme, term, or event>",
    "question": "<a standalone question about WHAT happens, WHY it happens, or WHAT COMES NEXT — do NOT reference 'the diagram', 'this image', or 'according to'>",
    "distractors": ["<plausible wrong answer 1>", "<plausible wrong answer 2>", "<plausible wrong answer 3>"],
    "difficulty": "<EASY|MEDIUM|HARD>",
    "explanation": "<1-2 sentences: why this is correct and its biological/clinical significance>"
  }}
]

Rules:
- Mix question types across the set: some about WHAT a step involves, some about WHY it happens, some about ORDER
- Questions must be answerable from memory by a student who has studied the topic — do not reference the image
- Distractors must be plausible {domain} terms or concepts, not random words
- EASY = foundational concept any first-year student knows; MEDIUM = requires study; HARD = precise mechanism or easily confused detail
- Return [] if the image does not show a clear process or sequence"""


def generate_process_diagram_quiz(
    image_path: str,
    triage: dict,
    surrounding_text: str,
) -> list[dict]:
    """
    Generate sequence and mechanism MCQ questions from a process diagram.

    Args:
        image_path:      Path to the diagram image (original, unmodified).
        triage:          Triage result dict — provides domain for prompt calibration.
        surrounding_text: PDF text from the same page — not used in prompt but
                          kept for signature consistency with other generators.

    Returns:
        List of question dicts (same shape as quiz_generator output). May be empty.
    """
    domain = triage.get("domain", "BIOLOGY")
    prompt = _PROMPT.format(domain=domain)

    try:
        raw = call_vision_json(image_path, prompt)
    except RuntimeError as e:
        logger.warning("generate_process_diagram_quiz: API failed for %s: %s", image_path, e)
        return []

    if isinstance(raw, list):
        questions_raw = raw
    elif isinstance(raw, dict):
        for key in ("questions", "data", "items", "results"):
            if isinstance(raw.get(key), list):
                questions_raw = raw[key]
                break
        else:
            logger.warning("generate_process_diagram_quiz: unexpected response shape for %s: %s",
                           image_path, list(raw.keys()))
            return []
    else:
        logger.warning("generate_process_diagram_quiz: non-list/dict response for %s", image_path)
        return []

    validated = []
    for q in questions_raw:
        if not isinstance(q, dict):
            continue
        missing = _REQUIRED_KEYS - set(q.keys())
        if missing:
            logger.debug("generate_process_diagram_quiz: question missing keys %s — dropped", missing)
            continue
        if not isinstance(q.get("distractors"), list) or len(q["distractors"]) != 3:
            continue
        if not q.get("structure_name") or not q.get("question"):
            continue
        validated.append(q)

    logger.info("generate_process_diagram_quiz: %d/%d questions validated for %s",
                len(validated), len(questions_raw), image_path)
    return validated
