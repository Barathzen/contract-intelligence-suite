"""Stage 1 — LLM outputs this simple JSON only (no nested intelligence)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class SimpleClauseExtraction(BaseModel):
    model_config = ConfigDict(extra="ignore")
    text: Optional[str] = None
    page: Optional[int] = None
    status: str = "absent"  # present | absent | uncertain


class SimpleStructuredExtraction(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: Optional[str] = None
    page: Optional[int] = None


class SimpleParty(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str = ""
    role: str = "unspecified"


class Stage1Extraction(BaseModel):
    model_config = ConfigDict(extra="ignore")

    contract_type: str = "Other"
    parties: List[SimpleParty] = Field(default_factory=list)
    governing_law: SimpleClauseExtraction = Field(default_factory=SimpleClauseExtraction)
    audit_rights: SimpleClauseExtraction = Field(default_factory=SimpleClauseExtraction)
    non_compete: SimpleClauseExtraction = Field(default_factory=SimpleClauseExtraction)
    non_solicitation: SimpleClauseExtraction = Field(default_factory=SimpleClauseExtraction)
    jurisdiction: SimpleStructuredExtraction = Field(default_factory=SimpleStructuredExtraction)
    payment_terms: SimpleStructuredExtraction = Field(default_factory=SimpleStructuredExtraction)
    notice_period: SimpleStructuredExtraction = Field(default_factory=SimpleStructuredExtraction)
    liability_cap: SimpleStructuredExtraction = Field(default_factory=SimpleStructuredExtraction)


def parse_stage1(data: Dict[str, Any]) -> Stage1Extraction:
    """Coerce loose LLM dict into Stage1Extraction with defaults."""
    if not isinstance(data, dict):
        return Stage1Extraction()
    try:
        return Stage1Extraction.model_validate(_soft_coerce(data))
    except Exception:
        return Stage1Extraction()


def _soft_coerce(d: Dict[str, Any]) -> Dict[str, Any]:
    """Fill missing keys; normalize nested dicts."""
    out = dict(d)
    for key in ("governing_law", "audit_rights", "non_compete", "non_solicitation"):
        if key not in out or not isinstance(out[key], dict):
            out[key] = {"text": None, "page": None, "status": "absent"}
    for key in ("jurisdiction", "payment_terms", "notice_period", "liability_cap"):
        if key not in out or not isinstance(out[key], dict):
            out[key] = {"text": None, "page": None}
    if "parties" not in out or not isinstance(out["parties"], list):
        out["parties"] = []
    if "contract_type" not in out:
        out["contract_type"] = "Other"
    return out
