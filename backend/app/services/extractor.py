"""
extractor.py  — PDF text extraction using pdfplumber
"""

from __future__ import annotations

import re
import fitz  # PyMuPDF
import pdfplumber
import pytesseract
from PIL import Image
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict

from app.utils.helpers import sanitize_text
from app.services.preprocessor import apply_advanced_preprocessing, extract_defined_terms
from app.services.legal_preprocess import (
    apply_page_text_pipeline,
    fingerprint_page_text,
    detect_language,
)

@dataclass
class PageContent:
    page_num: int
    text: str
    tables: List[str] = field(default_factory=list)

@dataclass
class DocumentContent:
    filepath: str
    pages: List[PageContent] = field(default_factory=list)
    defined_terms: Dict[str, str] = field(default_factory=dict)
    detected_language: str = "unknown"

    @property
    def full_text(self) -> str:
        body = "\n\n".join(p.text for p in self.pages)
        if self.defined_terms:
            defs_block = "\n\n[GLOBAL DEFINED TERMS]:\n"
            for term, context in self.defined_terms.items():
                defs_block += f"- {term} (Context: {context})\n"
            body += defs_block
        return body

    @property
    def page_count(self) -> int:
        return len(self.pages)

    def first_pages_text(self, n: int = 3) -> str:
        return "\n\n".join(p.text for p in self.pages[:n])

_HEADER_FOOTER_PATTERNS = [
    r"^Page\s+\d+\s+of\s+\d+$",
    r"^\d+\s*$",
    r"^confidential\s*$",
    r"^EXECUTION COPY\s*$",
    r"^\s*Signature Page\s*$"
]
_HF_RE = re.compile("|".join(_HEADER_FOOTER_PATTERNS), re.IGNORECASE | re.MULTILINE)

def _strip_headers_footers(text: str) -> str:
    return _HF_RE.sub("", text).strip()

def _ocr_page(page: fitz.Page) -> str:
    pix = page.get_pixmap()
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    return pytesseract.image_to_string(img)

def extract_pdf(filepath: str | Path) -> DocumentContent:
    """
    Extract text using PyMuPDF (fitz) for layout, OCR fallback, and pdfplumber for tables.
    """
    filepath = Path(filepath)
    if not filepath.exists():
        raise ValueError(f"File not found: {filepath}")

    doc = DocumentContent(filepath=str(filepath))

    try:
        # PyMuPDF for text
        with fitz.open(str(filepath)) as fitz_pdf:
            # pdfplumber for tables
            with pdfplumber.open(filepath) as plumber_pdf:
                for i in range(len(fitz_pdf)):
                    page_num = i + 1
                    
                    # 1. Text extraction preserving layout structure
                    fitz_page = fitz_pdf[i]
                    text = fitz_page.get_text("text")

                    # 2. OCR fallback if page is an image
                    if len(text.strip()) < 50:
                        text = _ocr_page(fitz_page)

                    text = _strip_headers_footers(text)
                    text = sanitize_text(text)
                    text = apply_advanced_preprocessing(text)
                    text = apply_page_text_pipeline(text)

                    # 3. Table extraction
                    tables = []
                    plumber_page = plumber_pdf.pages[i]
                    for table in plumber_page.extract_tables():
                        table_str = "\n".join([" | ".join([cell if cell else "" for cell in row]) for row in table])
                        tables.append(table_str)
                        text += f"\n\n[TABLE DATA]:\n{table_str}\n"

                    if text:
                        doc.pages.append(PageContent(page_num=page_num, text=text, tables=tables))

        # Drop exact-duplicate pages (common in PDF export artifacts)
        _seen_fp: set = set()
        deduped_pages: List[PageContent] = []
        for p in doc.pages:
            fp = fingerprint_page_text(p.text)
            if fp in _seen_fp:
                continue
            _seen_fp.add(fp)
            deduped_pages.append(
                PageContent(page_num=len(deduped_pages) + 1, text=p.text, tables=p.tables)
            )
        doc.pages = deduped_pages

        body_for_terms = "\n".join(p.text for p in doc.pages) if doc.pages else ""

        # Global definitions extraction
        doc.defined_terms = extract_defined_terms(body_for_terms)
        if doc.pages:
            doc.detected_language = detect_language(body_for_terms)

    except Exception as exc:
        raise ValueError(f"Failed to extract PDF '{filepath.name}': {exc}") from exc

    if not doc.pages:
        raise ValueError(f"No text could be extracted from '{filepath.name}'.")

    return doc
