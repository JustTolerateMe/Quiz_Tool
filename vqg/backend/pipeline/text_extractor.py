"""
text_extractor.py — Extract quiz-eligible text chunks from a PDF.

Runs page-by-page using PyMuPDF. Each page that passes the eligibility filter
becomes one chunk. Boilerplate lines (page numbers, copyright, pure headers)
are stripped before the word-count check.

Output per chunk:
  chunk_id     — "text_page_{NNN}" (zero-padded page number)
  page_number  — int (0-indexed, consistent with image pipeline)
  text         — cleaned text string
  word_count   — int (after cleaning)

Pages with fewer than MIN_WORDS words after cleaning are skipped.
"""

import logging
import re

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)

MIN_WORDS = 40  # pages below this threshold are skipped (title slides, transitions)

# Patterns for lines that are pure boilerplate — stripped before word count check.
# Matches: standalone page numbers, copyright lines, "www.example.com" URLs,
# bare slide-number markers like "Slide 4", and very short isolated lines (≤ 3 words).
_BOILERPLATE_LINE_RE = re.compile(
    r"^\s*("
    r"\d+"                                  # bare page/slide number
    r"|©.*"                                 # copyright line
    r"|Copyright.*"
    r"|www\.\S+"                            # standalone URL
    r"|https?://\S+"
    r"|Slide\s+\d+"                         # "Slide 4"
    r"|Page\s+\d+"                          # "Page 4"
    r"|\w[\w\s]{0,15}"                      # very short line (≤ ~3 words)
    r")\s*$",
    re.IGNORECASE,
)

# Lines that start with "Learning Objectives" or "Objectives" and have no body text
# after them on the same line — strip them (they're often slide headers).
_OBJECTIVES_RE = re.compile(r"^\s*(learning\s+)?objectives?\s*:?\s*$", re.IGNORECASE)


def _clean_page_text(raw: str) -> str:
    """
    Remove boilerplate lines from raw PyMuPDF page text.
    Returns the cleaned string (may be empty).
    """
    lines = raw.splitlines()
    kept = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if _OBJECTIVES_RE.match(stripped):
            continue
        if _BOILERPLATE_LINE_RE.match(stripped):
            # Only skip if the line is short (≤ 4 words) — avoids nuking real content
            if len(stripped.split()) <= 4:
                continue
        kept.append(stripped)
    return " ".join(kept)


def extract_text_chunks(pdf_path: str) -> list[dict]:
    """
    Extract and filter text chunks from every page of a PDF.

    Args:
        pdf_path: Absolute path to the PDF file.

    Returns:
        List of chunk dicts, one per eligible page, in page order.
        Pages below MIN_WORDS after cleaning are excluded.
    """
    chunks: list[dict] = []

    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        logger.error("extract_text_chunks: could not open PDF %s: %s", pdf_path, e)
        return []

    try:
        for page_num in range(len(doc)):
            try:
                page = doc[page_num]
                raw = page.get_text()
            except Exception as e:
                logger.warning("extract_text_chunks: page %d read error: %s", page_num, e)
                continue

            cleaned = _clean_page_text(raw)
            word_count = len(cleaned.split())

            if word_count < MIN_WORDS:
                logger.debug(
                    "extract_text_chunks: page %d skipped (%d words < %d min)",
                    page_num, word_count, MIN_WORDS,
                )
                continue

            chunks.append({
                "chunk_id": f"text_page_{page_num:03d}",
                "page_number": page_num,
                "text": cleaned,
                "word_count": word_count,
            })

    finally:
        doc.close()

    logger.info("extract_text_chunks: %d eligible pages from %d total", len(chunks), page_num + 1)
    return chunks
