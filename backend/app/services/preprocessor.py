"""
preprocessor.py — Advanced Preprocessing for Contracts
Handles Defined Term extraction and Cross-Reference resolution.

Layout / clause / OCR pipelines live in legal_preprocess.py (used by extractor + chunker).
"""

from __future__ import annotations

import re
from typing import Dict, List

# Regex to find definitions: e.g. (the "Company"), (hereinafter referred to as the "Service Provider")
# or ("Agreement")
_DEFINED_TERM_PATTERN = re.compile(
    r'\(\s*(?:hereinafter(?: referred to as)?\s+)?(?:the\s+)?["\']([A-Z][a-zA-Z\s]+)["\']\s*\)',
    re.IGNORECASE
)

# Regex to find cross-references: e.g. "Section 4.2", "Article III"
_CROSS_REF_PATTERN = re.compile(
    r'\b(Section|Article|Clause)\s+([\d\.]+|[IVXLCDM]+)\b',
    re.IGNORECASE
)

def extract_defined_terms(text: str) -> Dict[str, str]:
    """
    Finds capitalized defined terms declared in the text.
    Returns a dictionary of { "Term": "definition_context" }
    """
    terms = {}
    for match in _DEFINED_TERM_PATTERN.finditer(text):
        term = match.group(1).strip()
        # Grab a bit of surrounding context to define what the term means
        start_context = max(0, match.start() - 120)
        end_context = min(len(text), match.end() + 20)
        context = text[start_context:end_context].strip()
        terms[term] = context
    return terms

def annotate_cross_references(text: str) -> str:
    """
    Makes cross-references more explicit or tags them for the LLM.
    """
    def replacer(m):
        ref_type = m.group(1).capitalize()
        ref_num = m.group(2)
        return f'{ref_type} {ref_num} [CROSS_REF]'

    return _CROSS_REF_PATTERN.sub(replacer, text)

def apply_advanced_preprocessing(text: str) -> str:
    """
    Applies all advanced preprocessing routines to a block of text.
    Extracts terms and tags cross-references.
    """
    text = annotate_cross_references(text)
    return text
