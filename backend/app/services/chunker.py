"""
chunker.py  — Section/clause-aware text chunking
"""

from __future__ import annotations

import re
from typing import List

from app.models.schema import Chunk, ChunkMetadata
from app.services.extractor import DocumentContent


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


# ──────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────

def chunk_document(doc: DocumentContent) -> List[Chunk]:
    """
    Split a DocumentContent into semantically meaningful Chunk objects,
    each tagged with clause number, section title, and page number.
    """
    full_text = doc.full_text
    page_map = _build_page_map(doc)
    sections = _find_sections(full_text)

    chunks: List[Chunk] = []

    if not sections:
        # Fallback: paragraph-level chunking
        paras = _split_into_paragraphs(full_text)
        for idx, para in enumerate(paras):
            if len(para) < _MIN_CHUNK_CHARS:
                continue
            for sub in _chunk_text(para):
                chunks.append(Chunk(
                    text=sub,
                    metadata=ChunkMetadata(
                        clause_number=None,
                        section_title=f"Paragraph {idx + 1}",
                        page_number=1,
                    )
                ))
        return chunks

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
            chunks.append(Chunk(
                text=sub,
                metadata=ChunkMetadata(
                    clause_number=clause_num or None,
                    section_title=title or "Untitled Section",
                    page_number=page_num,
                )
            ))

    return chunks
