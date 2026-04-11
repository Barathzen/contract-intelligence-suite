"""
legal_preprocess.py — Contract document preprocessing (layout, OCR cleanup, clauses,
heading classification, deduplication, language hints). Merged into extractor + chunker.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import List, Optional, Set

# ──────────────────────────────────────────────
# Layout normalization
# ──────────────────────────────────────────────


def fix_hyphenated_words(text: str) -> str:
    """Join words split across lines: pay-\\nment → payment."""
    return re.sub(r"-\s*\n\s*", "", text)


def merge_columns(text: str) -> str:
    """Collapse wide gaps / tabs typical of two-column PDF extraction."""
    text = re.sub(r"\t+", " ", text)
    text = re.sub(r" {3,}", " ", text)
    return text


def remove_line_breaks_inside_sentences(text: str) -> str:
    """Merge soft line wraps; keep paragraph breaks (blank lines)."""
    paragraphs = re.split(r"\n\s*\n", text)
    fixed_paras = []
    for para in paragraphs:
        lines = [ln.strip() for ln in para.splitlines() if ln.strip()]
        if not lines:
            fixed_paras.append("")
            continue
        merged: List[str] = []
        buf = lines[0]
        for ln in lines[1:]:
            if not buf:
                buf = ln
                continue
            if buf.endswith((".", "!", "?", ":", "—", "-")) or ln[:1].isupper() and len(buf) < 8:
                merged.append(buf)
                buf = ln
            else:
                buf = f"{buf} {ln}"
        merged.append(buf)
        fixed_paras.append("\n".join(merged))
    return "\n\n".join(p for p in fixed_paras if p)


def normalize_layout(text: str) -> str:
    text = fix_hyphenated_words(text)
    text = merge_columns(text)
    text = remove_line_breaks_inside_sentences(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ──────────────────────────────────────────────
# OCR noise cleaning
# ──────────────────────────────────────────────

_OCR_CONFUSIONS = (
    (r"\bl\b(?=\d)", "1"),  # l before digit in numbers (narrow)
    (r"(?<=\d)\s*[oO]\s*(?=\d)", "0"),
)


def remove_special_characters(text: str) -> str:
    """Remove control chars; keep printable + common legal punctuation."""
    return "".join(c for c in text if c.isprintable() or c in "\n\t")


def fix_spacing(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n +", "\n", text)
    return text


def correct_common_ocr_errors(text: str) -> str:
    for pat, repl in _OCR_CONFUSIONS:
        text = re.sub(pat, repl, text)
    return text


def clean_ocr(text: str) -> str:
    text = remove_special_characters(text)
    text = fix_spacing(text)
    text = correct_common_ocr_errors(text)
    return text


# ──────────────────────────────────────────────
# Duplicate page removal
# ──────────────────────────────────────────────


def deduplicate_pages(page_texts: List[str]) -> List[str]:
    """Drop pages whose full text duplicates a prior page (exact hash)."""
    seen: Set[str] = set()
    out: List[str] = []
    for t in page_texts:
        key = hashlib.sha256(t.strip().encode("utf-8", errors="ignore")).hexdigest()
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out


# ──────────────────────────────────────────────
# Clause boundary detection (line-based)
# ──────────────────────────────────────────────

_CLAUSE_HEAD = re.compile(
    r"^\s*("
    r"(?:Section|Clause|Article)\s+[\w\d\.]+[^\n]*"
    r"|[\d]+(?:\.[\d]+)*[\.\)]\s*\S"  # 1. Title / 1.1 Something
    r")",
    re.IGNORECASE,
)


def detect_clauses(document_text: str) -> List[str]:
    """
    Split document into clause blocks when a line looks like a section heading.
    Returns list of clause strings (heading line included in each block).
    """
    lines = document_text.splitlines()
    clauses: List[str] = []
    current: List[str] = []

    def flush() -> None:
        nonlocal current
        if current:
            block = "\n".join(current).strip()
            if block:
                clauses.append(block)
            current = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if current:
                current.append("")
            continue
        if _CLAUSE_HEAD.match(stripped) and current:
            flush()
            current = [stripped]
        elif _CLAUSE_HEAD.match(stripped) and not current:
            current = [stripped]
        else:
            if not current:
                current = [stripped]
            else:
                current.append(stripped)
    flush()
    return clauses if clauses else ([document_text.strip()] if document_text.strip() else [])


def _similar(a: str, b: str, threshold: float = 0.92) -> bool:
    if not a or not b:
        return False
    return SequenceMatcher(None, a[:2000], b[:2000]).ratio() >= threshold


def deduplicate_clauses(clauses: List[str], threshold: float = 0.92) -> List[str]:
    unique: List[str] = []
    for c in clauses:
        if not any(_similar(c, u, threshold) for u in unique):
            unique.append(c)
    return unique


# ──────────────────────────────────────────────
# Section heading classification
# ──────────────────────────────────────────────


def classify_heading(heading_text: str) -> str:
    h = heading_text.lower()
    if "governing law" in h or "choice of law" in h:
        return "governing_law"
    if "liability" in h or "limitation of liability" in h or "cap on liability" in h:
        return "liability_cap"
    if "payment" in h or "fees" in h or "compensation" in h:
        return "payment_terms"
    if "termination" in h or "notice" in h and "period" in h:
        return "notice_period"
    if "non-compete" in h or "noncompete" in h:
        return "non_compete"
    if "non-solicit" in h:
        return "non_solicitation"
    if "audit" in h and "right" in h:
        return "audit_rights"
    if "confidential" in h:
        return "confidentiality"
    return "other"


# ──────────────────────────────────────────────
# Sentence segmentation
# ──────────────────────────────────────────────


def split_sentences(text: str) -> List[str]:
    if not text.strip():
        return []
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z(\"\'])", text)
    if len(parts) == 1:
        parts = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if p.strip()]


# ──────────────────────────────────────────────
# Stopword-aware cleaning (optional; can hurt legal retrieval — use sparingly)
# ──────────────────────────────────────────────

_STOP = frozenset(
    "the a an is are was were be been being at which of to in for on by with from as or if".split()
)
_LEGAL_HINTS = frozenset(
    "shall hereby party parties agreement indemnification warrant liability termination".split()
)


def is_legal_term(word: str) -> bool:
    w = word.lower().strip(".,;:\"'()")
    return w in _LEGAL_HINTS or len(w) > 12


def clean_stopwords(text: str) -> str:
    """Remove common stopwords unless they look like legal vocabulary."""
    words = re.findall(r"\S+|\s+", text)
    out: List[str] = []
    for w in words:
        if not w.strip():
            out.append(w)
            continue
        core = w.strip(".,;:\"'()").lower()
        if core in _STOP and not is_legal_term(w):
            continue
        out.append(w)
    return "".join(out).strip()


# ──────────────────────────────────────────────
# Legal entity normalization (party names)
# ──────────────────────────────────────────────

_SUFFIXES = (
    " pvt ltd",
    " pvt. ltd.",
    " private limited",
    " ltd.",
    " ltd",
    " inc.",
    " inc",
    " llc",
    " l.l.c.",
    " llp",
    " plc",
    " corp.",
    " corporation",
)


def normalize_entity_name(name: str) -> str:
    n = name.strip()
    low = n.lower()
    for suf in _SUFFIXES:
        if low.endswith(suf):
            n = n[: -len(suf)].strip(" ,")
            low = n.lower()
    return n


def normalize_entities(names: List[str]) -> List[str]:
    return [normalize_entity_name(n) for n in names]


# ──────────────────────────────────────────────
# Language detection (lightweight)
# ──────────────────────────────────────────────

_EN_HINT = frozenset(
    "the and shall hereby party agreement section article clause".split()
)


def detect_language(text: str) -> str:
    sample = text[:4000].lower()
    hits = sum(1 for w in _EN_HINT if re.search(rf"\b{re.escape(w)}\b", sample))
    if hits >= 4:
        return "en"
    if re.search(r"[àáâãäåèéêëìíîïòóôõöùúûü]", sample):
        return "unknown"
    return "en" if len(sample) > 50 else "unknown"


# ──────────────────────────────────────────────
# Boilerplate filtering
# ──────────────────────────────────────────────

_BOILER = re.compile(
    r"^\s*(recital|whereas|witnesseth|definitions?\s*$|table of contents)",
    re.IGNORECASE | re.MULTILINE,
)


def filter_boilerplate(clauses: List[str]) -> List[str]:
    """Drop clauses that are mostly boilerplate headers (conservative)."""
    kept: List[str] = []
    for c in clauses:
        first = c.strip().split("\n", 1)[0][:120].lower()
        if _BOILER.search(first):
            continue
        kept.append(c)
    return kept if kept else clauses


# ──────────────────────────────────────────────
# Section tag from chunk text (no PDF bbox in this pipeline)
# ──────────────────────────────────────────────


def detect_section_hint(text: str) -> str:
    """First line or heading-like prefix as section label."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return lines[0][:120] if lines else ""


# ──────────────────────────────────────────────
# Document-level pipeline applied inside extractor
# ──────────────────────────────────────────────


def fingerprint_page_text(text: str) -> str:
    """Return a SHA-256 hex digest of the stripped page text for deduplication."""
    return hashlib.sha256(text.strip().encode("utf-8", errors="ignore")).hexdigest()


def apply_page_text_pipeline(raw_page_text: str) -> str:
    """Per-page chain: layout normalize + OCR cleanup + existing cross-refs handled elsewhere."""
    t = raw_page_text
    t = normalize_layout(t)
    t = clean_ocr(t)
    return t


def apply_full_text_pipeline(full_text: str) -> str:
    """Second pass on concatenated document (soft dedupe of layout artifacts)."""
    t = normalize_layout(full_text)
    t = clean_ocr(t)
    return t


@dataclass
class ClauseBlock:
    """Structured clause for optional downstream use."""

    text: str
    heading_line: str = ""
    heading_type: str = "other"
    sentences: List[str] = field(default_factory=list)
    page_no: int = 1


def clauses_to_blocks(clauses: List[str], default_page: int = 1) -> List[ClauseBlock]:
    blocks: List[ClauseBlock] = []
    for c in clauses:
        lines = [ln for ln in c.splitlines() if ln.strip()]
        head = lines[0][:200] if lines else ""
        ht = classify_heading(head)
        blocks.append(
            ClauseBlock(
                text=c,
                heading_line=head,
                heading_type=ht,
                sentences=split_sentences(c),
                page_no=default_page,
            )
        )
    return blocks
