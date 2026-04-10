"""
llm_processor.py — Groq LLM extraction with RAG-retrieved context

Pipeline per contract:
  1. chunks already indexed in ChromaDB (embedder.py)
  2. rag_retriever.retrieve_all_relevant() → top semantically-relevant chunks
  3. classify_contract()  → Groq  → contract_type
  4. extract_fields()     → Groq  → full structured JSON
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from groq import Groq

from app.models.schema import Chunk, ContractOutput
from app.utils.helpers import normalize_boolean, normalize_currency, clean_string

load_dotenv()

_client: Optional[Groq] = None


def _get_client() -> Groq:
    global _client
    if _client is None:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY is not set. Please configure your .env file.")
        _client = Groq(api_key=api_key)
    return _client


def _model() -> str:
    return os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")


# ──────────────────────────────────────────────
# Prompts
# ──────────────────────────────────────────────

_CLASSIFICATION_SYSTEM = (
    "You are a legal document classifier. Respond ONLY with a JSON object. "
    "No markdown, no explanation, just the JSON."
)

_CLASSIFICATION_PROMPT = """\
Identify the contract type from this text. Choose EXACTLY one:
"Service Agreement", "IP Agreement", "Lease Agreement", "Supply Agreement",
"Employment Agreement", "Non-Disclosure Agreement", "License Agreement",
"Partnership Agreement", "Loan Agreement", "Other"

Respond with: {{"contract_type": "<chosen type>"}}

Contract excerpt:
{text}
"""

_EXTRACTION_SYSTEM = (
    "You are a senior legal analyst with 20 years of experience. "
    "Extract structured information from the contract text provided. "
    "Respond ONLY with a valid JSON object — no markdown fences, no explanation."
)

_EXTRACTION_PROMPT = """\
Extract ALL of the requested fields from the retrieved contract sections below.
Your response MUST be a single valid JSON object exactly mirroring this structure and keys:

{{
  "contract_id": "CTR-001",
  "contract_type": {{
    "label": "<e.g., Service Agreement>",
    "confidence": 0.95,
    "alternate_labels": []
  }},
  "parties": [
    {{
      "name": "Party Name",
      "role": "Client/Provider etc.",
      "entity_type": "Organization/Person",
      "confidence": 0.95
    }}
  ],
  "clauses": {{
    "governing_law": {{
      "status": "present|absent",
      "raw_text": "...",
      "normalized_value": {{"state": "...", "country": "..."}},
      "confidence": 0.95,
      "risk_level": "low|medium|high",
      "evidence_ids": ["EV-GL-001"]
    }},
    "audit_rights": {{
      "status": "present|absent",
      "raw_text": "...",
      "normalized_value": null,
      "confidence": 0.95,
      "risk_level": "low|medium|high",
      "evidence_ids": ["EV-AUD-001"]
    }},
    "non_compete": {{
      "status": "present|absent",
      "raw_text": "...",
      "normalized_value": {{"duration_months": 12}},
      "confidence": 0.95,
      "risk_level": "low|medium|high",
      "evidence_ids": ["EV-NC-001"]
    }},
    "non_solicitation": {{
      "status": "present|absent",
      "raw_text": "...",
      "normalized_value": {{"duration_months": 12}},
      "confidence": 0.95,
      "risk_level": "low|medium|high",
      "evidence_ids": ["EV-NS-001"]
    }}
  }},
  "structured_fields": {{
    "jurisdiction": {{
      "raw_text": "...",
      "normalized_value": {{"state": "...", "country": "..."}},
      "confidence": 0.95,
      "risk_level": "low",
      "evidence_ids": ["EV-JUR-001"]
    }},
    "payment_terms": {{
      "raw_text": "...",
      "normalized_value": {{"amount": 5000, "currency": "USD", "frequency": "monthly", "due_days": 15}},
      "confidence": 0.95,
      "risk_level": "low",
      "evidence_ids": ["EV-PAY-001"]
    }},
    "notice_period": {{
      "raw_text": "...",
      "normalized_value": {{"days": 30, "type": "written"}},
      "confidence": 0.95,
      "risk_level": "low",
      "evidence_ids": ["EV-NOT-001"]
    }},
    "liability_cap": {{
      "raw_text": "...",
      "normalized_value": {{"type": "limited", "multiplier": 2}},
      "confidence": 0.95,
      "risk_level": "medium",
      "evidence_ids": ["EV-LIAB-001"]
    }}
  }},
  "risk_summary": {{
    "risk_score": 50,
    "risk_level": "medium",
    "issues": []
  }},
  "confidence_summary": {{
    "overall_confidence": 0.95,
    "low_confidence_fields": []
  }},
  "evidence_index": [
    {{
      "evidence_id": "EV-GL-001",
      "section_heading": "...",
      "text_span": "...",
      "page_no": 1,
      "char_start": 0,
      "char_end": 100
    }}
  ]
}}

RULES:
- `evidence_index`: MUST include every single piece of evidence referenced by `evidence_ids`.
- `text_span` MUST be the exact verbatim substring extracted from the context.
- Use `null` instead of missing keys if the data does not exist, but maintain the structure.

Retrieved contract sections:
{context}
"""


# ──────────────────────────────────────────────
# JSON extraction
# ──────────────────────────────────────────────

def _parse_json(raw: str) -> Dict[str, Any]:
    """Strip markdown fences and parse JSON; raise on failure."""
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"\s*```$", "", raw, flags=re.MULTILINE)
    # Try extracting JSON object if there's extra text
    m = re.search(r"\{[\s\S]+\}", raw)
    if m:
        raw = m.group(0)
    return json.loads(raw)


# ──────────────────────────────────────────────
# Groq LLM call with retry
# ──────────────────────────────────────────────

def _llm_call(
    system: str,
    user: str,
    retries: int = 3,
    temperature: float = 0.0,
) -> Dict[str, Any]:
    client = _get_client()
    last_err: Exception = RuntimeError("No attempts made")

    for attempt in range(retries):
        try:
            response = client.chat.completions.create(
                model=_model(),
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=temperature,
                response_format={"type": "json_object"},
                max_tokens=3000,
            )
            raw = response.choices[0].message.content or "{}"
            return _parse_json(raw)
        except json.JSONDecodeError as e:
            last_err = e
            time.sleep(1.0 * (attempt + 1))
        except Exception as e:
            last_err = e
            wait = 2.0 * (attempt + 1)
            print(f"[LLM] Attempt {attempt+1} failed: {e}. Retrying in {wait}s…")
            time.sleep(wait)

    raise RuntimeError(f"Groq call failed after {retries} attempts: {last_err}")


# ──────────────────────────────────────────────
# Format RAG-retrieved chunks into context
# ──────────────────────────────────────────────

def _format_context(chunks: List[Chunk], max_chars: int = 14000) -> str:
    parts = []
    total = 0
    for c in chunks:
        header = (
            f"[Section: {c.metadata.section_title or 'General'} | "
            f"Clause: {c.metadata.clause_number or '—'} | "
            f"Page: {c.metadata.page_number}]"
        )
        block = f"{header}\n{c.text}"
        if total + len(block) > max_chars:
            break
        parts.append(block)
        total += len(block)
    return "\n\n---\n\n".join(parts)


# ──────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────

def classify_contract(first_pages_text: str) -> str:
    """Classify contract type from first pages using Groq."""
    try:
        result = _llm_call(
            system=_CLASSIFICATION_SYSTEM,
            user=_CLASSIFICATION_PROMPT.format(text=first_pages_text[:3000]),
        )
        return str(result.get("contract_type", "Other"))
    except Exception as e:
        print(f"[LLM] Classification failed: {e}")
        return "Other"


import datetime

def extract_fields_with_rag(
    source_file: str,
    contract_type: str,
    page_count: int,
    processing_time: float,
) -> ContractOutput:
    from app.services.rag_retriever import retrieve_all_relevant

    retrieved_chunks = retrieve_all_relevant(
        source_file=source_file,
        top_k_per_field=4,
        deduplicate=True,
    )

    context = _format_context(retrieved_chunks)
    error_msg: Optional[str] = None
    raw: Dict[str, Any] = {}

    try:
        raw = _llm_call(
            system=_EXTRACTION_SYSTEM,
            user=_EXTRACTION_PROMPT.format(context=context),
        )
    except Exception as e:
        error_msg = str(e)
        
    contract_id = raw.get("contract_id", "CTR-001")

    # Construct Source Metadata
    source_metadata = {
        "file_name": source_file.split("/")[-1],
        "file_type": "pdf",
        "processed_at": datetime.datetime.now().isoformat() + "Z",
        "language": "en",
        "page_count": page_count,
        "ocr_used": False
    }
    
    # Construct Processing Metadata
    processing_metadata = {
        "schema_version": "contract_intelligence_v1",
        "pipeline_version": "v1",
        "model_used": "gpt-oss-120b",
        "processing_time_ms": int(processing_time * 1000)
    }

    raw["source_metadata"] = source_metadata
    raw["processing_metadata"] = processing_metadata
    
    if "contract_type" not in raw or not isinstance(raw["contract_type"], dict):
        raw["contract_type"] = {"label": contract_type, "confidence": 1.0, "alternate_labels": []}
        
    if "parties" not in raw: raw["parties"] = []
    
    empty_clause = {"status": "absent", "raw_text": None, "normalized_value": None, "confidence": 0.0, "risk_level": "low", "evidence_ids": []}
    if "clauses" not in raw:
        raw["clauses"] = {"governing_law": empty_clause, "audit_rights": empty_clause, "non_compete": empty_clause, "non_solicitation": empty_clause}

    empty_field = {"raw_text": "", "normalized_value": None, "confidence": 0.0, "risk_level": "low", "evidence_ids": []}
    if "structured_fields" not in raw:
        raw["structured_fields"] = {"jurisdiction": empty_field, "payment_terms": empty_field, "notice_period": empty_field, "liability_cap": empty_field}

    if "risk_summary" not in raw:
        raw["risk_summary"] = {"risk_score": 0, "risk_level": "low", "issues": []}

    if "confidence_summary" not in raw:
        raw["confidence_summary"] = {"overall_confidence": 0.0, "low_confidence_fields": []}
        
    if "evidence_index" not in raw:
        raw["evidence_index"] = []

    try:
        return ContractOutput(**raw)
    except Exception as e:
        print("[LLM Schema ValidationError]:", e)
        # return a generic version if pydantic map fails
        return ContractOutput(
            contract_id=contract_id,
            source_metadata=source_metadata,
            contract_type=raw["contract_type"],
            parties=raw["parties"],
            clauses=raw["clauses"],
            structured_fields=raw["structured_fields"],
            risk_summary=raw["risk_summary"],
            confidence_summary=raw["confidence_summary"],
            evidence_index=raw["evidence_index"],
            processing_metadata=processing_metadata
        )


# ──────────────────────────────────────────────
# Convenience: full RAG pipeline for one document
# ──────────────────────────────────────────────

def process_document_rag(
    doc,               # DocumentContent
    chunks: List[Chunk],
    source_file: str,
    start_time: float,
) -> ContractOutput:
    """
    Full pipeline:
      1. Index chunks into vector store
      2. Classify contract type (Groq on first pages)
      3. RAG-retrieve relevant chunks → Groq extract fields
    """
    from app.services.embedder import index_document

    # Step 1: Index this document into ChromaDB
    n_indexed = index_document(source_file=source_file, chunks=chunks)
    print(f"[RAG] Indexed {n_indexed} chunks for '{source_file}'")

    # Step 2: Classify
    contract_type = classify_contract(doc.first_pages_text(3))
    print(f"[RAG] '{source_file}' → {contract_type}")

    # Step 3: Extract via RAG
    elapsed = time.time() - start_time
    return extract_fields_with_rag(
        source_file=source_file,
        contract_type=contract_type,
        page_count=doc.page_count,
        processing_time=elapsed,
    )
