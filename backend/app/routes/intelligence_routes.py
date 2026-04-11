"""
intelligence_routes.py — User Intelligence Layer
Role-specific API endpoints that filter/transform the extracted contract JSON
into views tailored for Legal, Business, Compliance, and Executive users.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from dotenv import load_dotenv
import os

load_dotenv()

router = APIRouter(prefix="/api/intelligence", tags=["intelligence"])

# Resolve the same way whether OUTPUT_DIR is relative (e.g. ../data/output in .env) or absolute,
# so role views read the JSON files written by /api/contracts/upload.
_BACKEND_DIR = Path(__file__).resolve().parents[2]
_raw_out = os.getenv("OUTPUT_DIR", str(_BACKEND_DIR.parent / "data" / "output"))
_p_out = Path(_raw_out)
OUTPUT_DIR = str(_p_out.resolve() if _p_out.is_absolute() else (_BACKEND_DIR / _p_out).resolve())

# Delegate view construction to the insights engine
from app.services.insights_engine import (
    build_legal_view,
    build_business_view,
    build_compliance_view,
    build_executive_view,
)


def _load_contract(contract_id: str) -> dict:
    """Load a processed contract JSON by filename stem or contract_id."""
    out_path = Path(OUTPUT_DIR)
    # Try direct filename match (e.g. "contract_001")
    candidate = out_path / f"{contract_id}.json"
    if candidate.exists():
        return json.loads(candidate.read_text(encoding="utf-8"))
    # Try matching contract_id field inside JSONs
    for f in out_path.glob("*.json"):
        if f.name.endswith(".error.json"):
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if data.get("contract_id") == contract_id:
                return data
        except Exception:
            continue
    raise HTTPException(status_code=404, detail=f"Contract '{contract_id}' not found.")


# ─────────────────────────────────────────────────────────────
# Legal View: clauses, missing clauses, risk flags
# ─────────────────────────────────────────────────────────────
@router.get("/legal-view/{contract_id}")
def legal_view(contract_id: str):
    """
    For lawyers and legal teams.
    Returns: all clauses, their status, evidence, and risk flags.
    """
    data = _load_contract(contract_id)
    return build_legal_view(data, contract_id)


# ─────────────────────────────────────────────────────────────
# Business View: payment, obligations, notice period
# ─────────────────────────────────────────────────────────────
@router.get("/business-view/{contract_id}")
def business_view(contract_id: str):
    """
    For business managers and operations teams.
    Returns: payment terms, notice period, key obligations, parties.
    """
    data = _load_contract(contract_id)
    return build_business_view(data, contract_id)


# ─────────────────────────────────────────────────────────────
# Compliance View: missing safeguards, issues
# ─────────────────────────────────────────────────────────────
@router.get("/compliance-view/{contract_id}")
def compliance_view(contract_id: str):
    """
    For compliance officers.
    Returns: missing safeguards, risk score breakdown, uncertain clauses.
    """
    data = _load_contract(contract_id)
    return build_compliance_view(data, contract_id)


# ─────────────────────────────────────────────────────────────
# Executive View: summary, risk score, key issues
# ─────────────────────────────────────────────────────────────
@router.get("/executive-view/{contract_id}")
def executive_view(contract_id: str):
    """
    For C-suite and decision makers.
    Returns: high-level summary, risk score, key issues, quick snapshot.
    """
    data = _load_contract(contract_id)
    return build_executive_view(data, contract_id)
