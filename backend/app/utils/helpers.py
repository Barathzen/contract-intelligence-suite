"""
helpers.py  — normalization utilities for extracted contract values
"""

from __future__ import annotations

import re
from typing import Optional


# ──────────────────────────────────────────────
# Text cleaning
# ──────────────────────────────────────────────

def sanitize_text(text: str) -> str:
    """Remove control characters and collapse whitespace."""
    # Drop non-printable chars (keep newlines)
    text = re.sub(r"[^\S\n]+", " ", text)
    text = re.sub(r"\x00", "", text)
    return text.strip()


# ──────────────────────────────────────────────
# Boolean normalization
# ──────────────────────────────────────────────

_TRUE_TOKENS = {"yes", "true", "present", "applicable", "exists", "included", "1"}
_FALSE_TOKENS = {"no", "false", "absent", "not applicable", "n/a", "none", "0"}


def normalize_boolean(value: object) -> bool:
    """Coerce a variety of truthy/falsy representations to bool."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _TRUE_TOKENS:
            return True
        if normalized in _FALSE_TOKENS:
            return False
    return False  # default conservative


# ──────────────────────────────────────────────
# Currency normalization
# ──────────────────────────────────────────────

def normalize_currency(value: Optional[str]) -> Optional[str]:
    """Standardize currency strings; return as-is if unparseable."""
    if not value:
        return None
    # Already structured — just clean whitespace
    value = value.strip()
    # Replace common unicode currency symbols for readability
    value = re.sub(r"\s+", " ", value)
    return value or None


# ──────────────────────────────────────────────
# Date normalization  (light-touch — keeps original if complex)
# ──────────────────────────────────────────────

_DATE_PATTERNS = [
    # 01 January 2024 / 1st Jan 2024
    (r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)[,\s]+(\d{4})", "%d %B %Y"),
    # January 01, 2024
    (r"([A-Za-z]+)\s+(\d{1,2})[,\s]+(\d{4})", "%B %d %Y"),
    # 2024-01-01
    (r"(\d{4})-(\d{2})-(\d{2})", "%Y-%m-%d"),
    # 01/01/2024
    (r"(\d{1,2})/(\d{1,2})/(\d{4})", "%d/%m/%Y"),
]


def normalize_date(value: Optional[str]) -> Optional[str]:
    """Attempt to return ISO date string; fall back to cleaned original."""
    if not value:
        return None
    value = value.strip()
    from datetime import datetime
    for pattern, _ in _DATE_PATTERNS:
        m = re.search(pattern, value, re.IGNORECASE)
        if m:
            # Try month-name based parse
            candidate = " ".join(m.groups())
            for fmt in [
                "%d %B %Y", "%d %b %Y",
                "%B %d %Y", "%b %d %Y",
                "%Y %m %d", "%d %m %Y",
            ]:
                try:
                    return datetime.strptime(candidate, fmt).date().isoformat()
                except ValueError:
                    continue
    return value  # return as-is if unparseable


# ──────────────────────────────────────────────
# General string cleanup
# ──────────────────────────────────────────────

def clean_string(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    value = value.strip().strip('"').strip("'")
    return value or None
