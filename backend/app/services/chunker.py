"""
chunker.py  — Section/clause-aware text chunking
"""

from __future__ import annotations

import re
from typing import List, Optional

from difflib import SequenceMatcher

from app.models.schema import Chunk, ChunkMetadata
from app.services.extractor import DocumentContent
from app.services.legal_preprocess import (
    classify_heading,
    deduplicate_clauses,
    detect_clauses,
    filter_boilerplate,
)


# ──────────────────────────────────────────────
# Section heading patterns  (ordered by specificity)
# ──────────────────────────────────────────────

_SECTION_PATTERNS = [
    # "ARTICLE IV", "ARTICLE 4"
    r"^\s*ARTICLE\s+(?P<num>[IVXLCDM]+|\d+)[\.\s]+(?P<title>.+)$",
    # "Section 12.3", "SECTION 12", "Clause 5"
    r"^\s*(?:Section|SECTION|Clause|CLAUSE)\s+(?P<num>[\d\.]+)[\.\s:—–-]+(?P<title>.*)$",
    # Plain numbered: "1. Definitions", "1.1 Payment Terms"
    r"^\s*(?P<num>\d+(?:\.\d+)*)\s*[.\)]\s+(?P<title>[A-Z][^\n]{2,60})$",
    # ALL-CAPS headings with no number
    r"^\s*(?P<num>)(?P<title>[A-Z][A-Z\s]{5,60})$",
]

_SECTION_RE = [re.compile(p, re.MULTILINE) for p in _SECTION_PATTERNS]

# Min characters a chunk body should have to be retained
_MIN_CHUNK_CHARS = 80
# Max characters before we split a giant chunk further
_MAX_CHUNK_CHARS = 4000


def _document_body(doc: DocumentContent) -> str:
    """Structural text only (no defined-terms appendix)."""
    return "\n\n".join(p.text for p in doc.pages)


def _find_sections(text: str):
    """
    Return list of (start_char, clause_number, section_title) tuples
    for all section headings found in `text`.
    """
    hits = []
    for pattern in _SECTION_RE:
        for m in pattern.finditer(text):
            hits.append((m.start(), m.group("num").strip(), m.group("title").strip()))
    # Sort by position, deduplicate overlapping matches
    hits.sort(key=lambda x: x[0])
    deduped = []
    last_pos = -1
    for pos, num, title in hits:
        if pos > last_pos + 5:   # allow 5-char tolerance for duplicates
            deduped.append((pos, num, title))
            last_pos = pos
    return deduped


def _split_into_paragraphs(text: str) -> List[str]:
    """Fallback: split on double-newlines."""
    parts = re.split(r"\n{2,}", text)
    return [p.strip() for p in parts if p.strip()]


def _chunk_text(text: str, max_chars: int = _MAX_CHUNK_CHARS) -> List[str]:
    """Further split a large text block by sentences if it exceeds max_chars."""
    if len(text) <= max_chars:
        return [text]
    # Split on sentence boundaries
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks, current = [], ""
    for sent in sentences:
        if len(current) + len(sent) > max_chars and current:
            chunks.append(current.strip())
            current = sent
        else:
            current += " " + sent
    if current.strip():
        chunks.append(current.strip())
    return chunks if chunks else [text]


# ──────────────────────────────────────────────
# Page-number lookup helper
# ──────────────────────────────────────────────

def _build_page_map(doc: DocumentContent) -> List[tuple[int, int, int]]:
    """
    Returns list of (char_start, char_end, page_num) for the full document text.
    """
    mapping = []
    pos = 0
    full_sep = "\n\n"
    for page in doc.pages:
        start = pos
        end = pos + len(page.text)
        mapping.append((start, end, page.page_num))
        pos = end + len(full_sep)
    return mapping


def _page_for_char(char_pos: int, page_map) -> int:
    for start, end, page_num in page_map:
        if start <= char_pos <= end:
            return page_num
    return 1  # default


def _dedupe_similar_chunks(chunks: List[Chunk], threshold: float = 0.95) -> List[Chunk]:
    kept: List[Chunk] = []
    for c in chunks:
        if any(
            SequenceMatcher(None, (c.text or "")[:2000], (k.text or "")[:2000]).ratio() >= threshold
            for k in kept
        ):
            continue
        kept.append(c)
    return kept


def _make_chunk(
    text: str,
    clause_num: Optional[str],
    title: str,
    page_num: int,
) -> Chunk:
    ht = classify_heading(title or text[:120])
    return Chunk(
        text=text,
        metadata=ChunkMetadata(
            clause_number=clause_num,
            section_title=title or "Untitled Section",
            page_number=page_num,
            heading_type=ht,
        ),
    )


# ──────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────

def chunk_document(doc: DocumentContent) -> List[Chunk]:
    """
    Split a DocumentContent into semantically meaningful Chunk objects,
    each tagged with clause number, section title, page number, and heading_type.
    """
    full_text = _document_body(doc)
    page_map = _build_page_map(doc)
    sections = _find_sections(full_text)

    chunks: List[Chunk] = []

    if not sections:
        # Clause-boundary detection + boilerplate filter + dedupe, then chunk
        raw_clauses = detect_clauses(full_text)
        raw_clauses = filter_boilerplate(raw_clauses)
        raw_clauses = deduplicate_clauses(raw_clauses)
        if not raw_clauses:
            raw_clauses = [full_text] if full_text.strip() else []

        for ctext in raw_clauses:
            if len(ctext.strip()) < _MIN_CHUNK_CHARS:
                continue
            lines = [ln for ln in ctext.splitlines() if ln.strip()]
            title = (lines[0][:120] if lines else "Clause")[:120]
            for sub in _chunk_text(ctext):
                chunks.append(_make_chunk(sub, None, title, 1))

        return _dedupe_similar_chunks(chunks)

    # Section-based chunking
    for i, (pos, clause_num, title) in enumerate(sections):
        # Body runs from just after heading to start of next section (or end)
        body_start = pos
        body_end = sections[i + 1][0] if i + 1 < len(sections) else len(full_text)
        body = full_text[body_start:body_end].strip()

        if len(body) < _MIN_CHUNK_CHARS:
            continue

        page_num = _page_for_char(pos, page_map)

        for sub in _chunk_text(body):
            chunks.append(_make_chunk(sub, clause_num or None, title or "Untitled Section", page_num))

    return _dedupe_similar_chunks(chunks)
