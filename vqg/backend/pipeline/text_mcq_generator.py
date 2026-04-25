"""
text_mcq_generator.py — Generate MCQ flashcard questions from raw page text.

Called for text chunks extracted by text_extractor.py.
Returns the same question dict shape as quiz_generator / context_mcq_generator
so all three exporters (Anki, HTML, PDF) work without structural changes.

Question count is adaptive:
  word_count < 80  → max 3 questions  (sparse slide)
  word_count ≥ 80  → min(10, word_count // 40)  (denser textbook content)
"""

import logging

from backend.utils.gemini_client import call_text_json

logger = logging.getLogger(__name__)

_REQUIRED_KEYS = {"label_id", "structure_name", "question", "distractors", "difficulty", "explanation"}

_PROMPT_TEMPLATE = """You are generating MCQ flashcard questions for a {domain} student.

Below is text extracted from a PDF ({source_type}).
Identify the key facts, mechanisms, definitions, or clinical criteria that a {domain} student is expected to memorise.

Generate at most {max_q} questions — quality over quantity:
- Sparse slide text (< 80 words): 1–3 questions on the single most important fact
- Dense textbook text (≥ 80 words): up to {max_q} questions covering distinct, non-overlapping facts

Here are two examples of good questions:

Example 1 (slide text):
  TEXT: "ACE inhibitors block the conversion of angiotensin I to angiotensin II, reducing vasoconstriction and aldosterone secretion."
  OUTPUT:
  [{{"label_id":"T1","structure_name":"Angiotensin II","question":"Which molecule do ACE inhibitors prevent from being produced, thereby reducing vasoconstriction?","distractors":["Angiotensin I","Renin","Aldosterone"],"difficulty":"EASY","explanation":"ACE inhibitors block ACE, preventing angiotensin I → angiotensin II conversion. Angiotensin II is the vasoconstrictor; aldosterone secretion is a downstream effect."}}]

Example 2 (textbook text):
  TEXT: "The basal ganglia circuit involves the striatum receiving cortical input, projecting via the direct pathway (D1, facilitatory) and indirect pathway (D2, inhibitory) to the globus pallidus interna (GPi), which tonically inhibits the thalamus. Dopamine from the substantia nigra pars compacta activates D1 and inhibits D2, net effect: increased thalamo-cortical activity."
  OUTPUT:
  [{{"label_id":"T1","structure_name":"Direct pathway (D1)","question":"Which basal ganglia pathway, when activated by dopamine, facilitates movement by reducing GPi inhibition of the thalamus?","distractors":["Indirect pathway (D2)","Corticostriatal pathway","Nigrostriatal pathway"],"difficulty":"MEDIUM","explanation":"D1 activation by dopamine reduces GPi output, releasing thalamic inhibition and allowing movement."}},{{"label_id":"T2","structure_name":"Globus pallidus interna (GPi)","question":"Which structure tonically inhibits the thalamus in the basal ganglia circuit?","distractors":["Striatum","Subthalamic nucleus","Substantia nigra pars reticulata"],"difficulty":"MEDIUM","explanation":"The GPi provides the main output inhibition of the thalamus; reduced GPi activity allows thalamo-cortical facilitation of movement."}}]

Now generate questions from the following text.
Return ONLY a JSON array — no other text, no markdown fences.

Rules:
- Questions must stand alone — answerable from memory, not from reading this text
- NEVER start with "According to", "Based on the text", "In this passage", or similar
- Skip slide titles alone, copyright lines, presenter names, or pure formatting text
- Distractors must be plausible for a {domain} student — real terms, not random words
- Return [] if the text has no standalone testable facts

TEXT:
{text}"""


def _compute_max_q(word_count: int) -> int:
    if word_count < 80:
        return 3
    return min(10, word_count // 40)


def _infer_source_type(word_count: int) -> str:
    return "slide deck" if word_count < 80 else "textbook"


def generate_text_mcq(chunk: dict, domain: str = "MEDICINE") -> list[dict]:
    """
    Generate MCQ questions from a text chunk extracted by text_extractor.

    Args:
        chunk:  Dict with keys: chunk_id, page_number, text, word_count
        domain: Subject domain string for prompt calibration (default MEDICINE)

    Returns:
        List of question dicts (same schema as quiz_generator output). May be empty.
    """
    text = chunk.get("text", "").strip()
    word_count = chunk.get("word_count", len(text.split()))

    if not text:
        return []

    max_q = _compute_max_q(word_count)
    source_type = _infer_source_type(word_count)

    prompt = _PROMPT_TEMPLATE.format(
        domain=domain,
        source_type=source_type,
        max_q=max_q,
        text=text,
    )

    try:
        raw = call_text_json(prompt)
    except RuntimeError as e:
        logger.warning("generate_text_mcq: API failed for chunk %s: %s", chunk.get("chunk_id"), e)
        return []

    if isinstance(raw, list):
        questions_raw = raw
    elif isinstance(raw, dict):
        for key in ("questions", "data", "items", "results"):
            if isinstance(raw.get(key), list):
                questions_raw = raw[key]
                break
        else:
            logger.warning("generate_text_mcq: unexpected response shape for chunk %s: %s",
                           chunk.get("chunk_id"), list(raw.keys()))
            return []
    else:
        logger.warning("generate_text_mcq: non-list/dict response for chunk %s", chunk.get("chunk_id"))
        return []

    validated = []
    for q in questions_raw:
        if not isinstance(q, dict):
            continue
        missing = _REQUIRED_KEYS - set(q.keys())
        if missing:
            logger.debug("generate_text_mcq: question missing keys %s — dropped", missing)
            continue
        if not isinstance(q.get("distractors"), list) or len(q["distractors"]) != 3:
            continue
        if not q.get("structure_name") or not q.get("question"):
            continue
        validated.append(q)

    logger.info(
        "generate_text_mcq: %d/%d questions validated for chunk %s",
        len(validated), len(questions_raw), chunk.get("chunk_id"),
    )
    return validated
