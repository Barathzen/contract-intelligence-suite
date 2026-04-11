"""
llm_processor.py — Two-stage extraction with RAG-retrieved context

Pipeline per contract:
  1. chunks indexed in ChromaDB (embedder.py)
  2. rag_retriever.retrieve_all_relevant() → context chunks
  3. classify_contract() → Groq → contract type hint
  4. Stage 1: LLM → simple JSON (text, page, status only)
  5. Stage 2: deterministic structuring → ContractOutput (schema v2)

Token budget:
  llama-3.3-70b-versatile context window = 128k tokens
  Free-tier daily quota is limited — we keep each call well under 4,000 input tokens.
  GROQ_MAX_CONTEXT_CHARS env var controls context window (default 6000 chars ≈ 1500 tokens).
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
from app.models.stage1_schema import parse_stage1
from app.services.stage2_structuring import build_contract_output_from_stage1

load_dotenv()

_client: Optional[Groq] = None

# ── Token budget controls ──────────────────────────────────────────────────
# ~4 chars per token. Keep total input well under 4k tokens to stay within
# free-tier daily quota even for large PDFs.
# Override via env: GROQ_MAX_CONTEXT_CHARS=8000 for paid plans.
_MAX_CONTEXT_CHARS = int(os.getenv("GROQ_MAX_CONTEXT_CHARS", "6000"))
_MAX_CLASSIFY_CHARS = int(os.getenv("GROQ_MAX_CLASSIFY_CHARS", "1500"))
# Max chars per individual chunk — prevents one giant chunk eating the whole budget
_MAX_CHUNK_CHARS = int(os.getenv("GROQ_MAX_CHUNK_CHARS", "600"))


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

_STAGE1_SYSTEM = (
    "You extract factual snippets from legal contract excerpts. "
    "Output ONLY valid JSON — no markdown, no commentary, no confidence scores, no risk analysis."
)

_STAGE1_PROMPT = """\
Read the excerpts below (each block has a Page marker). Extract a SINGLE flat JSON object with EXACTLY these keys:

{{
  "contract_type": "<one label: Service Agreement, IP Agreement, Lease Agreement, Supply Agreement, Employment Agreement, Non-Disclosure Agreement, License Agreement, Partnership Agreement, Loan Agreement, or Other>",
  "parties": [{{"name": "<string>", "role": "<string or 'unspecified'>"}}],
  "governing_law": {{"text": <string or null>, "page": <integer or null>, "status": "present"|"absent"|"uncertain"}},
  "audit_rights": {{"text": <string or null>, "page": <integer or null>, "status": "present"|"absent"|"uncertain"}},
  "non_compete": {{"text": <string or null>, "page": <integer or null>, "status": "present"|"absent"|"uncertain"}},
  "non_solicitation": {{"text": <string or null>, "page": <integer or null>, "status": "present"|"absent"|"uncertain"}},
  "jurisdiction": {{"text": <string or null>, "page": <integer or null>}},
  "payment_terms": {{"text": <string or null>, "page": <integer or null>}},
  "notice_period": {{"text": <string or null>, "page": <integer or null>}},
  "liability_cap": {{"text": <string or null>, "page": <integer or null>}}
}}

Rules:
1. Quote verbatim clause text when present; otherwise null.
2. For clause fields, use status "absent" if the clause is not in the excerpts; "uncertain" if weak/indirect.
3. page must match the [Page: N] line from the excerpt when the quote comes from that block; else null.
4. parties: include signatories named in the excerpts (may be empty array).
5. Do NOT add any other keys. Do NOT nest confidence, risk, or normalized structures.

Excerpts:
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
    max_tokens: int = 3000,
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
                max_tokens=max_tokens,
            )
            raw = response.choices[0].message.content or "{}"
            return _parse_json(raw)
        except json.JSONDecodeError as e:
            last_err = e
            time.sleep(1.0 * (attempt + 1))
        except Exception as e:
            last_err = e
            err_str = str(e)
            # Detect daily token limit (TPD) — retrying won't help, fail immediately
            if "rate_limit_exceeded" in err_str and "tokens per day" in err_str.lower():
                raise RuntimeError(
                    "[RATE LIMIT] Daily token quota (TPD) exceeded. "
                    "Wait until midnight UTC or upgrade your Groq plan. "
                    "Your contract was NOT processed."
                )
            # Detect per-minute rate limit — wait longer before retry
            if "rate_limit_exceeded" in err_str:
                wait = 30.0  # wait 30s for per-minute limits
                print(f"[LLM] Rate limited (attempt {attempt+1}). Waiting {wait}s...")
                time.sleep(wait)
            else:
                wait = 2.0 * (attempt + 1)
                print(f"[LLM] Attempt {attempt+1} failed: {err_str[:100]}. Retrying in {wait}s...")
                time.sleep(wait)

    raise RuntimeError(f"Groq call failed after {retries} attempts: {last_err}")


# ──────────────────────────────────────────────
# Format RAG-retrieved chunks into context
# ──────────────────────────────────────────────

def _format_context(chunks: List[Chunk], max_chars: int = _MAX_CONTEXT_CHARS) -> str:
    """
    Build a context string from retrieved chunks, respecting the token budget.
    Each chunk is truncated to _MAX_CHUNK_CHARS so no single chunk dominates.
    Stops adding chunks once max_chars is reached.
    """
    parts = []
    total = 0
    for c in chunks:
        # Truncate individual chunk text to avoid one huge chunk eating the budget
        chunk_text = c.text[:_MAX_CHUNK_CHARS]
        if len(c.text) > _MAX_CHUNK_CHARS:
            chunk_text += "… [truncated]"
        header = (
            f"[Section: {c.metadata.section_title or 'General'} | "
            f"Clause: {c.metadata.clause_number or '—'} | "
            f"Page: {c.metadata.page_number}]"
        )
        block = f"{header}\n{chunk_text}"
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
            user=_CLASSIFICATION_PROMPT.format(text=first_pages_text[:_MAX_CLASSIFY_CHARS]),
        )
        return str(result.get("contract_type", "Other"))
    except Exception as e:
        print(f"[LLM] Classification failed: {e}")
        return "Other"


def extract_fields_with_rag(
    source_file: str,
    contract_type: str,
    page_count: int,
    processing_time: float,
) -> ContractOutput:
    from app.services.rag_retriever import retrieve_all_relevant

    # Fewer chunks per field = fewer tokens. RAG + RRF means quality stays high.
    retrieved_chunks = retrieve_all_relevant(
        source_file=source_file,
        top_k_per_field=3,
        deduplicate=True,
    )

    context = _format_context(retrieved_chunks)
    estimated_tokens = len(context) // 4
    print(f"[LLM] Context: {len(context)} chars (~{estimated_tokens} tokens) from {len(retrieved_chunks)} chunks")

    raw_stage1: Dict[str, Any] = {}

    try:
        raw_stage1 = _llm_call(
            system=_STAGE1_SYSTEM,
            user=_STAGE1_PROMPT.format(context=context),
            max_tokens=1200,
        )
    except Exception as e:
        print(f"[LLM] Stage-1 extraction failed: {str(e)[:120]}")

    file_stem = source_file.split("/")[-1].split("\\")[-1]
    contract_id = f"CTR-{file_stem.replace('.pdf', '').replace('contract_', '')}"

    s1 = parse_stage1(raw_stage1)
    try:
        return build_contract_output_from_stage1(
            s1,
            contract_id=contract_id,
            file_stem=file_stem,
            page_count=page_count,
            processing_time_ms=int(processing_time * 1000),
            language="en",
            classified_fallback_type=contract_type,
        )
    except Exception as e:
        print(f"[Stage2] Structuring failed: {e}")
        s1 = parse_stage1({})
        return build_contract_output_from_stage1(
            s1,
            contract_id=contract_id,
            file_stem=file_stem,
            page_count=page_count,
            processing_time_ms=int(processing_time * 1000),
            language="en",
            classified_fallback_type=contract_type,
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
      4. Risk Evaluation (Rule Engine)
    """
    from app.services.embedder import index_document
    from app.services.risk_engine import evaluate_risk

    # Step 1: Index this document into ChromaDB
    n_indexed = index_document(source_file=source_file, chunks=chunks)
    print(f"[RAG] Indexed {n_indexed} chunks for '{source_file}'")

    # Step 2: Classify
    contract_type = classify_contract(doc.first_pages_text(3))
    print(f"[RAG] '{source_file}' -> {contract_type}")

    # Step 3: Extract via RAG
    elapsed = time.time() - start_time
    output = extract_fields_with_rag(
        source_file=source_file,
        contract_type=contract_type,
        page_count=doc.page_count,
        processing_time=elapsed,
    )

    # Step 4: Evaluate Risk Post-Processing
    output = evaluate_risk(output)

    return output
