"""
chunker.py  — Advanced Recursive & Hierarchical text chunking
"""

from __future__ import annotations

import re
from typing import List, Tuple, Optional

from app.models.schema import Chunk, ChunkMetadata
from app.services.extractor import DocumentContent
from app.services.legal_preprocess import classify_heading

# ──────────────────────────────────────────────
# Hierarchy Levels
# ──────────────────────────────────────────────

_HIERARCHY_RE = [
    # Level 1: "ARTICLE IV", "ARTICLE 4"
    re.compile(r"^\s*ARTICLE\s+(?P<num>[IVXLCDM]+|\d+)[\.\s]+(?P<title>.+)$", re.MULTILINE),
    # Level 2: "Section 12", "SECTION 12.3", "Clause 5"
    re.compile(r"^\s*(?:Section|SECTION|Clause|CLAUSE)\s+(?P<num>[\d\.]+)[\.\s:—–-]+(?P<title>.*)$", re.MULTILINE),
    # Level 3: "1.2 Payment Terms"
    re.compile(r"^\s*(?P<num>\d+(?:\.\d+)*)\s*[.\)]\s+(?P<title>[A-Z][^\n]{2,60})$", re.MULTILINE),
]

_MIN_CHUNK_CHARS = 80
_MAX_CHUNK_CHARS = 3000
_OVERLAP_TOKENS = 0.15 # 15% overlap

def _chunk_text_with_sliding_window(text: str, max_chars: int = _MAX_CHUNK_CHARS) -> List[str]:
    """Split by sentences and use a sliding overlap window to preserve semantic continuity."""
    if len(text) <= max_chars:
        return [text]
    
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text)
    chunks = []
    current_sentences = []
    current_len = 0
    
    for sent in sentences:
        if current_len + len(sent) > max_chars and current_sentences:
            chunks.append(" ".join(current_sentences).strip())
            
            # Keep the last ~15% length of sentences for overlap context
            overlap_sentences = []
            overlap_len = 0
            for s in reversed(current_sentences):
                if overlap_len + len(s) < max_chars * _OVERLAP_TOKENS:
                    overlap_sentences.insert(0, s)
                    overlap_len += len(s)
                else:
                    break
                    
            current_sentences = overlap_sentences
            current_len = overlap_len
            
        current_sentences.append(sent)
        current_len += len(sent) + 1  # +1 for space
        
    if current_sentences:
        chunks.append(" ".join(current_sentences).strip())
        
    return chunks

def _build_page_map(doc: DocumentContent) -> List[tuple[int, int, int]]:
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
    return 1

def _recursive_chunk(
    text: str, 
    start_offset: int, 
    level: int, 
    hierarchy: List[str], 
    page_map: List[tuple[int, int, int]]
) -> List[Chunk]:
    chunks: List[Chunk] = []

    if level >= len(_HIERARCHY_RE):
        # Base case: Apply sliding window extraction
        if len(text.strip()) > _MIN_CHUNK_CHARS:
            for sub in _chunk_text_with_sliding_window(text.strip()):
                page_num = _page_for_char(start_offset, page_map)
                title = hierarchy[-1] if hierarchy else "Untitled Section"
                clause_num = title.split(" ")[0] if hierarchy else None
                
                chunks.append(Chunk(
                    text=sub,
                    metadata=ChunkMetadata(
                        clause_number=clause_num,
                        section_title=title,
                        parent_hierarchy=hierarchy,
                        page_number=page_num,
                        heading_type=classify_heading(title)
                    )
                ))
        return chunks

    pattern = _HIERARCHY_RE[level]
    matches = list(pattern.finditer(text))

    if not matches:
        return _recursive_chunk(text, start_offset, level + 1, hierarchy, page_map)

    # Process chunks delimited by this level's headers
    for i, match in enumerate(matches):
        match_start = match.start()
        match_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        
        # Capture any text before the first heading of this level
        if i == 0 and match_start > _MIN_CHUNK_CHARS:
            pre_text = text[:match_start]
            chunks.extend(
                _recursive_chunk(pre_text, start_offset, level + 1, hierarchy, page_map)
            )
            
        num = match.group("num").strip()
        title_text = match.group("title").strip()
        current_heading = f"[{level+1}] {num} - {title_text}"
        
        body = text[match_start:match_end]
        
        chunks.extend(
            _recursive_chunk(
                body, 
                start_offset + match_start, 
                level + 1, 
                hierarchy + [current_heading], 
                page_map
            )
        )

    return chunks

def chunk_document(doc: DocumentContent) -> List[Chunk]:
    """
    Split a DocumentContent hierarchically using Recursive RegExp sweeps.
    Injects precise parent layout history mapping to assist semantic LLM retrieval.
    """
    full_text = doc.full_text
    page_map = _build_page_map(doc)
    
    chunks = _recursive_chunk(full_text, 0, 0, [], page_map)
    
    # Fallback if no recursive hierarchy was found
    if not chunks:
        chunks.extend(_recursive_chunk(full_text, 0, len(_HIERARCHY_RE), [], page_map))
        
    return chunks
