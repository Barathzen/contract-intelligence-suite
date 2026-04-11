"""
insights_engine.py — User Intelligence Layer

Provides four simple, rule-based processors that transform a processed
contract JSON into role-specific views for Legal, Business, Compliance,
and Executive users. Designed to be deterministic and easy to test.
"""
from __future__ import annotations
from typing import Dict, Any


def build_legal_view(data: Dict[str, Any], contract_id: str) -> Dict[str, Any]:
    clauses = data.get("clauses", {})
    risk = data.get("risk_summary", {})

    present, uncertain, missing = [], [], []
    for name, clause in clauses.items():
        status = clause.get("status", "not_found")
        entry = {
            "clause": name.replace("_", " ").title(),
            "status": status,
            "raw_text": clause.get("raw_text"),
            "risk_level": clause.get("risk_level", "low"),
            "confidence": clause.get("confidence", 0.0),
            "evidence_ids": clause.get("evidence_ids", []),
        }
        if status == "present":
            present.append(entry)
        elif status == "uncertain":
            uncertain.append(entry)
        else:
            missing.append(entry)

    return {
        "view": "legal",
        "contract_id": contract_id,
        "source_file": data.get("source_metadata", {}).get("file_name"),
        "contract_type": data.get("contract_type", {}).get("label"),
        "parties": data.get("parties", []),
        "clauses_found": present,
        "clauses_uncertain": uncertain,
        "clauses_missing": missing,
        "risk_flags": risk.get("issues", []),
        "overall_risk_level": risk.get("risk_level", "unknown"),
        "evidence_index": data.get("evidence_index", []),
    }


def build_business_view(data: Dict[str, Any], contract_id: str) -> Dict[str, Any]:
    fields = data.get("structured_fields", {})

    def _field(key: str) -> Dict[str, Any]:
        f = fields.get(key, {})
        return {
            "status": f.get("status", "not_found"),
            "raw_text": f.get("raw_text"),
            "normalized_value": f.get("normalized_value"),
            "confidence": f.get("confidence", 0.0),
        }

    clauses = data.get("clauses", {})
    obligations = []
    for name, clause in clauses.items():
        if clause.get("status") == "present" and clause.get("raw_text"):
            obligations.append({
                "obligation": name.replace("_", " ").title(),
                "text": clause["raw_text"],
            })

    return {
        "view": "business",
        "contract_id": contract_id,
        "source_file": data.get("source_metadata", {}).get("file_name"),
        "contract_type": data.get("contract_type", {}).get("label"),
        "parties": data.get("parties", []),
        "payment_terms": _field("payment_terms"),
        "notice_period": _field("notice_period"),
        "liability_cap": _field("liability_cap"),
        "jurisdiction": _field("jurisdiction"),
        "key_obligations": obligations,
        "contract_duration_pages": data.get("source_metadata", {}).get("page_count"),
    }


def build_compliance_view(data: Dict[str, Any], contract_id: str) -> Dict[str, Any]:
    clauses = data.get("clauses", {})
    fields = data.get("structured_fields", {})
    risk = data.get("risk_summary", {})

    safeguard_clauses = ["governing_law", "audit_rights", "non_compete", "non_solicitation"]
    safeguard_fields = ["liability_cap", "notice_period"]

    missing_safeguards = []
    uncertain_safeguards = []

    for key in safeguard_clauses:
        c = clauses.get(key, {})
        status = c.get("status", "not_found")
        label = key.replace("_", " ").title()
        if status == "not_found":
            missing_safeguards.append({"item": label, "type": "clause", "risk_level": c.get("risk_level", "medium")})
        elif status == "uncertain":
            uncertain_safeguards.append({"item": label, "type": "clause", "confidence": c.get("confidence", 0.0)})

    for key in safeguard_fields:
        f = fields.get(key, {})
        status = f.get("status", "not_found")
        label = key.replace("_", " ").title()
        if status == "not_found":
            missing_safeguards.append({"item": label, "type": "field", "risk_level": f.get("risk_level", "medium")})
        elif status == "uncertain":
            uncertain_safeguards.append({"item": label, "type": "field", "confidence": f.get("confidence", 0.0)})

    return {
        "view": "compliance",
        "contract_id": contract_id,
        "source_file": data.get("source_metadata", {}).get("file_name"),
        "contract_type": data.get("contract_type", {}).get("label"),
        "risk_score": risk.get("risk_score", 0),
        "risk_level": risk.get("risk_level", "unknown"),
        "missing_safeguards": missing_safeguards,
        "uncertain_items": uncertain_safeguards,
        "compliance_issues": risk.get("issues", []),
        "total_issues_count": len(missing_safeguards) + len(uncertain_safeguards),
    }


def build_executive_view(data: Dict[str, Any], contract_id: str) -> Dict[str, Any]:
    risk = data.get("risk_summary", {})
    clauses = data.get("clauses", {})
    fields = data.get("structured_fields", {})
    conf = data.get("confidence_summary", {})

    present_count = sum(1 for c in clauses.values() if c.get("status") == "present")
    total_count = len(clauses)
    fields_found = sum(1 for f in fields.values() if f.get("status") == "present")
    total_fields = len(fields)

    return {
        "view": "executive",
        "contract_id": contract_id,
        "source_file": data.get("source_metadata", {}).get("file_name"),
        "contract_type": data.get("contract_type", {}).get("label"),
        "parties_count": len(data.get("parties", [])),
        "parties": [p.get("name") for p in data.get("parties", [])],
        "risk_score": risk.get("risk_score", 0),
        "risk_level": risk.get("risk_level", "unknown"),
        "key_issues": risk.get("issues", [])[:3],
        "clauses_found": f"{present_count}/{total_count}",
        "fields_extracted": f"{fields_found}/{total_fields}",
        "overall_confidence": conf.get("overall_confidence", 0.0),
        "page_count": data.get("source_metadata", {}).get("page_count"),
        "processing_time_sec": round((data.get("processing_metadata", {}).get("processing_time_ms", 0)) / 1000, 1),
        "governing_law": clauses.get("governing_law", {}).get("raw_text") or "Not found",
    }
