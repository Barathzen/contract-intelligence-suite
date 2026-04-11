"""
stage2_structuring.py — Deterministic post-processing: Stage1 simple JSON → ContractOutput.
Validation, normalization, evidence mapping, confidence, metadata (risk via evaluate_risk caller).
"""

from __future__ import annotations

import datetime
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from app.models.schema import (
    BaseClause,
    ConfidenceSummary,
    ContractOutput,
    ContractType,
    EvidenceItem,
    Party,
    ProcessingMetadata,
    RiskSummary,
    SourceMetadata,
    StructuredField,
    Clauses,
    StructuredFields,
)
from app.models.stage1_schema import Stage1Extraction


def _map_clause_status(raw: str) -> str:
    x = (raw or "").lower().strip()
    if x in ("present", "uncertain", "not_found"):
        return x
    if x == "absent":
        return "not_found"
    return "not_found"


def _structured_status(text: Optional[str]) -> str:
    if text and str(text).strip():
        return "present"
    return "not_found"


def _base_confidence(clause_status: str, has_text: bool) -> float:
    st = _map_clause_status(clause_status) if clause_status in ("present", "absent", "uncertain", "not_found") else "not_found"
    if st == "present" and has_text:
        return 0.90
    if st == "uncertain" and has_text:
        return 0.52
    return 0.28


def _sf_confidence(status: str, has_text: bool) -> float:
    if status == "present" and has_text:
        return 0.89
    if status == "uncertain":
        return 0.48
    return 0.27


# ── Normalization heuristics (deterministic) ──────────────────────────────


def _norm_governing_law(text: Optional[str]) -> Optional[Dict[str, Any]]:
    if not text or not str(text).strip():
        return None
    t = text.strip()
    m = re.search(
        r"laws?\s+of\s+(?:the\s+)?(?:State\s+of\s+)?([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
        t,
        re.IGNORECASE,
    )
    state = m.group(1) if m else None
    if not state:
        m2 = re.search(r"governed\s+by\s+([^.;\n]+)", t, re.IGNORECASE)
        state = (m2.group(1).strip() if m2 else None)
    country = "USA" if state and len(state) < 30 else None
    if state:
        return {"jurisdiction_name": f"State of {state}" if "State" not in state else state, "country": country or "USA"}
    return {"jurisdiction_name": t[:120], "country": "USA"}


def _norm_jurisdiction(text: Optional[str]) -> Optional[Dict[str, Any]]:
    if not text or not str(text).strip():
        return None
    g = _norm_governing_law(text)
    if not g:
        return None
    return {"state": g.get("jurisdiction_name", "").replace("State of ", ""), "country": g.get("country")}


def _norm_payment(text: Optional[str]) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    t = text
    amt = None
    cur = "USD"
    m = re.search(r"\$[\d,]+(?:\.\d+)?", t)
    if m:
        amt = float(m.group().replace("$", "").replace(",", ""))
    if re.search(r"euro|€|eur", t, re.I):
        cur = "EUR"
    freq = "monthly" if re.search(r"monthly|per\s+month", t, re.I) else None
    due = None
    m2 = re.search(r"(\d+)\s*days?", t, re.I)
    if m2:
        due = int(m2.group(1))
    out: Dict[str, Any] = {}
    if amt is not None:
        out["amount"] = amt
    out["currency"] = cur
    if freq:
        out["frequency"] = freq
    if due is not None:
        out["due_days"] = due
    return out if out else {"raw": t[:200]}


def _norm_notice(text: Optional[str]) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    m = re.search(r"(\d+)\s*(?:days?|calendar\s+days?)", text, re.I)
    days = int(m.group(1)) if m else None
    typ = "written" if re.search(r"written", text, re.I) else "any"
    if days is None:
        return {"type": typ, "raw": text[:200]}
    return {"days": days, "type": typ}


def _norm_non_compete_solicit(text: Optional[str]) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    m = re.search(r"(\d+)\s*months?", text, re.I)
    if m:
        return {"duration_months": int(m.group(1))}
    m2 = re.search(r"(\d+)\s*years?", text, re.I)
    if m2:
        return {"duration_months": int(m2.group(1)) * 12}
    return {"summary": text[:200]}


def _norm_liability(text: Optional[str]) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    tl = text.lower()
    if "unlimited" in tl or "no limit" in tl or "unlimited liability" in tl:
        return {"type": "unlimited"}
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:x|times)\s*(?:the|annual)", tl)
    if m:
        return {"type": "limited", "multiplier": float(m.group(1))}
    m2 = re.search(r"exceed\s+.*?(\d+(?:\.\d+)?)\s*(?:x|times)", tl)
    if m2:
        return {"type": "limited", "multiplier": float(m2.group(1))}
    return {"type": "limited", "summary": text[:200]}


def _clause_risk_level(status: str, field: str) -> str:
    st = _map_clause_status(status)
    if st == "not_found":
        return "high" if field == "governing_law" else "medium"
    if st == "uncertain":
        return "medium"
    return "low"


def _sf_risk_level(name: str, nv: Optional[Dict[str, Any]]) -> Optional[str]:
    if name == "liability_cap" and isinstance(nv, dict):
        if nv.get("type") == "unlimited":
            return "high"
        mult = nv.get("multiplier")
        if mult and float(mult) > 3:
            return "high"
        return "medium"
    return None


class _EvidenceRegistry:
    def __init__(self) -> None:
        self._counters: Dict[str, int] = {}
        self.items: List[EvidenceItem] = []

    def register(self, prefix: str, heading: str, text: str, page: int) -> str:
        self._counters[prefix] = self._counters.get(prefix, 0) + 1
        n = self._counters[prefix]
        eid = f"EV-{prefix}-{n:03d}"
        span = (text or "")[:2000]
        self.items.append(
            EvidenceItem(
                evidence_id=eid,
                section_heading=heading,
                text_span=span,
                page_no=max(1, int(page or 1)),
                char_start=0,
                char_end=len(span),
            )
        )
        return eid


_PREFIX = {
    "governing_law": "GL",
    "audit_rights": "AR",
    "non_compete": "NC",
    "non_solicitation": "NS",
    "jurisdiction": "JUR",
    "payment_terms": "PAY",
    "notice_period": "NOT",
    "liability_cap": "LIAB",
}

_HEADING = {
    "governing_law": "Governing Law",
    "audit_rights": "Audit Rights",
    "non_compete": "Non-Compete",
    "non_solicitation": "Non-Solicitation",
    "jurisdiction": "Jurisdiction",
    "payment_terms": "Payment Terms",
    "notice_period": "Notice / Termination",
    "liability_cap": "Limitation of Liability",
}


def _build_clause(
    s1_block: Any,
    field: str,
    reg: _EvidenceRegistry,
    normalize_fn,
) -> Tuple[BaseClause, List[str]]:
    text = getattr(s1_block, "text", None) or None
    page = getattr(s1_block, "page", None) or 1
    status = _map_clause_status(getattr(s1_block, "status", "absent"))
    if not text or not str(text).strip():
        status = "not_found" if status != "uncertain" else "uncertain"
    has_text = bool(text and str(text).strip())
    conf = _base_confidence(getattr(s1_block, "status", "absent"), has_text)
    nv = normalize_fn(text) if has_text else None
    eids: List[str] = []
    if has_text and status in ("present", "uncertain"):
        eids = [reg.register(_PREFIX[field], _HEADING[field], str(text), int(page or 1))]

    return (
        BaseClause(
            status=status,
            raw_text=text,
            normalized_value=nv,
            confidence=conf,
            risk_level=_clause_risk_level(getattr(s1_block, "status", "absent"), field),
            evidence_ids=eids,
        ),
        eids,
    )


def _build_structured(
    s1_block: Any,
    field: str,
    reg: _EvidenceRegistry,
    normalize_fn,
) -> StructuredField:
    text = getattr(s1_block, "text", None) or None
    page = getattr(s1_block, "page", None) or 1
    status = _structured_status(text)
    has_text = bool(text and str(text).strip())
    conf = _sf_confidence(status, has_text)
    nv = normalize_fn(text) if has_text else None
    eids: List[str] = []
    if has_text and status == "present":
        eids = [reg.register(_PREFIX[field], _HEADING[field], str(text), int(page or 1))]
    rl = _sf_risk_level(field, nv)
    return StructuredField(
        status=status,
        raw_text=text,
        normalized_value=nv,
        confidence=conf,
        risk_level=rl,
        evidence_ids=eids,
    )


_ORG_SUFFIXES = re.compile(
    r"\b(llc|llp|ltd|limited|inc|incorporated|corp|corporation|plc|pvt|gmbh|ag|sa|bv|nv|co)\b",
    re.IGNORECASE,
)
_ORG_KEYWORDS = re.compile(
    r"\b(company|group|holdings|partners|associates|services|solutions|technologies|enterprises|bank|fund)\b",
    re.IGNORECASE,
)


def _detect_entity_type(name: str) -> str:
    """Heuristic: classify as Organization if name contains corporate suffixes/keywords."""
    if _ORG_SUFFIXES.search(name) or _ORG_KEYWORDS.search(name):
        return "Organization"
    # All-caps short names like "IBM", "GE" are typically organizations
    stripped = name.strip()
    if stripped.isupper() and len(stripped) >= 2:
        return "Organization"
    return "Person"


def build_contract_output_from_stage1(
    s1: Stage1Extraction,
    *,
    contract_id: str,
    file_stem: str,
    page_count: int,
    processing_time_ms: int,
    language: str = "en",
    classified_fallback_type: str = "Other",
) -> ContractOutput:
    reg = _EvidenceRegistry()

    gl, _ = _build_clause(s1.governing_law, "governing_law", reg, _norm_governing_law)
    ar, _ = _build_clause(s1.audit_rights, "audit_rights", reg, lambda t: None)
    nc, _ = _build_clause(s1.non_compete, "non_compete", reg, _norm_non_compete_solicit)
    ns, _ = _build_clause(s1.non_solicitation, "non_solicitation", reg, _norm_non_compete_solicit)

    clauses = Clauses(governing_law=gl, audit_rights=ar, non_compete=nc, non_solicitation=ns)

    jur = _build_structured(s1.jurisdiction, "jurisdiction", reg, _norm_jurisdiction)
    pay = _build_structured(s1.payment_terms, "payment_terms", reg, _norm_payment)
    ntp = _build_structured(s1.notice_period, "notice_period", reg, _norm_notice)
    liab = _build_structured(s1.liability_cap, "liability_cap", reg, _norm_liability)

    structured_fields = StructuredFields(
        jurisdiction=jur,
        payment_terms=pay,
        notice_period=ntp,
        liability_cap=liab,
    )

    label = (s1.contract_type or "").strip() or classified_fallback_type
    parties: List[Party] = []
    for p in s1.parties:
        if not p.name or not str(p.name).strip():
            continue
        parties.append(
            Party(
                name=str(p.name).strip(),
                role=(p.role or "unspecified").strip() or "unspecified",
                entity_type=_detect_entity_type(p.name),
                confidence=0.86,
            )
        )

    # Confidence summary
    confs: List[float] = []
    for c in (gl, ar, nc, ns):
        confs.append(c.confidence)
    for sf in (jur, pay, ntp, liab):
        confs.append(sf.confidence)
    overall = sum(confs) / len(confs) if confs else 0.0
    low_fields: List[str] = []
    mapping = [
        ("governing_law", gl.confidence),
        ("audit_rights", ar.confidence),
        ("non_compete", nc.confidence),
        ("non_solicitation", ns.confidence),
        ("jurisdiction", jur.confidence),
        ("payment_terms", pay.confidence),
        ("notice_period", ntp.confidence),
        ("liability_cap", liab.confidence),
    ]
    for name, cf in mapping:
        if cf < 0.60:
            low_fields.append(name)

    source_metadata = SourceMetadata(
        file_name=file_stem,
        file_type="pdf",
        processed_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        language=language,
        page_count=page_count,
        ocr_used=False,
    )

    processing_metadata = ProcessingMetadata(
        schema_version="contract_intelligence_v2",
        pipeline_version="two_stage_pipeline_v1",
        model_used=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
        processing_time_ms=processing_time_ms,
        extraction_stage="llm_simple_json",
        post_processing_stage="rule_engine_enrichment",
    )

    return ContractOutput(
        contract_id=contract_id,
        source_metadata=source_metadata,
        contract_type=ContractType(label=label, confidence=0.92, alternate_labels=[]),
        parties=parties,
        clauses=clauses,
        structured_fields=structured_fields,
        risk_summary=RiskSummary(risk_score=0, risk_level="low", issues=[]),
        confidence_summary=ConfidenceSummary(overall_confidence=round(overall, 4), low_confidence_fields=low_fields),
        evidence_index=reg.items,
        processing_metadata=processing_metadata,
    )
