"""
risk_engine.py — Dedicated Risk Intelligence Engine
Programmatically calculates a transparent, rule-based risk score from extracted contract data.
Each risk contribution is documented so the output is fully explainable.
"""

from __future__ import annotations
from app.models.schema import ContractOutput, RiskSummary


# Status values considered "missing" for risk evaluation purposes
_MISSING = {"not_found", "uncertain"}


def _is_missing(status: str) -> bool:
    return status in _MISSING


def evaluate_risk(contract: ContractOutput) -> ContractOutput:
    """
    Applies deterministic, explainable rules to calculate a risk score.
    Every point added to the score is accompanied by a human-readable reason.
    Completely overrides the LLM's risk_summary with a trustworthy result.
    """
    score = 0
    issues = []

    # ── Rule 1: Governing Law ──────────────────────────────
    # Missing or unclear governing law makes dispute resolution jurisdiction ambiguous.
    gov_law = getattr(contract.clauses, "governing_law", None)
    if gov_law:
        if gov_law.status == "not_found":
            score += 40
            issues.append("[+40] Governing law clause not found — jurisdiction of disputes is undefined (High Risk)")
            gov_law.risk_level = "high"
        elif gov_law.status == "uncertain":
            score += 20
            issues.append("[+20] Governing law is implied but not explicitly stated — uncertain legal applicability (Medium Risk)")
            gov_law.risk_level = "medium"

    # ── Rule 2: Liability Cap ──────────────────────────────
    # Unlimited or missing liability cap exposes parties to uncapped financial risk.
    liab_cap = getattr(contract.structured_fields, "liability_cap", None)
    if liab_cap:
        nv = liab_cap.normalized_value or {}
        cap_type = nv.get("type", "unknown") if isinstance(nv, dict) else "unknown"
        multiplier = nv.get("multiplier", 0) if isinstance(nv, dict) else 0

        if cap_type == "unlimited":
            score += 50
            issues.append("[+50] Liability cap is unlimited — uncapped exposure to damages (Critical Risk)")
            liab_cap.risk_level = "high"
        elif multiplier and float(multiplier) > 3.0:
            score += 30
            issues.append(f"[+30] Liability multiplier is {multiplier}x — unusually high, review carefully (High Risk)")
            liab_cap.risk_level = "high"
        elif liab_cap.status in _MISSING:
            score += 30
            issues.append("[+30] Liability cap not found — financial exposure is uncapped by default (High Risk)")
            liab_cap.risk_level = "high"

    # ── Rule 3: Audit Rights ──────────────────────────────
    # Absence of audit rights limits ability to verify compliance.
    audit = getattr(contract.clauses, "audit_rights", None)
    if audit and audit.status in _MISSING:
        score += 15
        issues.append("[+15] Audit rights clause not found — no mechanism to verify counterparty compliance (Medium Risk)")
        audit.risk_level = "medium"

    # ── Rule 4: Non-Compete (contract-type dependent) ──────────────────────────────
    # Non-compete clauses are expected in Employment and Service agreements.
    if contract.contract_type and contract.contract_type.label in ["Employment Agreement", "Service Agreement"]:
        nc = getattr(contract.clauses, "non_compete", None)
        if nc and nc.status in _MISSING:
            score += 10
            issues.append("[+10] Non-compete clause not found in Employment/Service agreement — competitive risk (Low-Medium Risk)")

    # ── Rule 5: Notice Period ──────────────────────────────
    # Missing notice period creates ambiguity in termination.
    notice = getattr(contract.structured_fields, "notice_period", None)
    if notice and notice.status in _MISSING:
        score += 5
        issues.append("[+5] Notice period not found — termination timeline is undefined (Low Risk)")

    # ── Normalize Score ──────────────────────────────
    final_score = min(100, max(0, score))

    # ── Map Score to Level ──────────────────────────────
    if final_score >= 70:
        level = "high"
    elif final_score >= 35:
        level = "medium"
    else:
        level = "low"

    if not issues:
        issues.append("[+0] No significant risk flags identified based on available extracted data")

    # ── Override LLM risk_summary ──────────────────────────────
    contract.risk_summary = RiskSummary(
        risk_score=final_score,
        risk_level=level,
        issues=issues
    )

    return contract
