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
from typing import List

from app.utils.helpers import sanitize_text

@dataclass
class PageContent:
    page_num: int
    text: str
    tables: List[str] = field(default_factory=list)

@dataclass
class DocumentContent:
    filepath: str
    pages: List[PageContent] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        return "\n\n".join(p.text for p in self.pages)

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

                    # 3. Table extraction
                    tables = []
                    plumber_page = plumber_pdf.pages[i]
                    for table in plumber_page.extract_tables():
                        table_str = "\n".join([" | ".join([cell if cell else "" for cell in row]) for row in table])
                        tables.append(table_str)
                        text += f"\n\n[TABLE DATA]:\n{table_str}\n"

                    if text:
                        doc.pages.append(PageContent(page_num=page_num, text=text, tables=tables))

    except Exception as exc:
        raise ValueError(f"Failed to extract PDF '{filepath.name}': {exc}") from exc

    if not doc.pages:
        raise ValueError(f"No text could be extracted from '{filepath.name}'.")

    return doc
