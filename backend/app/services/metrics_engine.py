"""
metrics_engine.py — Per-contract report card: field scores, PRF, grounding, loss.

Ground truth (optional): data/ground_truth/{contract_id}.json
See _GROUND_TRUTH_SCHEMA in docstring of load_ground_truth.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.models.metrics_schema import ContractMetricsPayload, FieldMetric
from app.models.schema import ContractOutput

_BACKEND_DIR = Path(__file__).resolve().parents[2]


def _env_path(key: str, default_relative: str) -> str:
    raw = os.getenv(key, default_relative)
    p = Path(raw)
    return str(p.resolve() if p.is_absolute() else (_BACKEND_DIR / p).resolve())


_METRICS_DIR = _env_path("METRICS_DIR", str(_BACKEND_DIR.parent / "data" / "metrics"))
_GROUND_TRUTH_DIR = _env_path("GROUND_TRUTH_DIR", str(_BACKEND_DIR.parent / "data" / "ground_truth"))

# Tracked extraction fields: (group, name)
TRACKED_FIELDS: List[Tuple[str, str]] = [
    ("clauses", "governing_law"),
    ("clauses", "audit_rights"),
    ("clauses", "non_compete"),
    ("clauses", "non_solicitation"),
    ("structured_fields", "jurisdiction"),
    ("structured_fields", "payment_terms"),
    ("structured_fields", "notice_period"),
    ("structured_fields", "liability_cap"),
]


def _get_nested(obj: Any, *keys: str) -> Any:
    cur = obj
    for k in keys:
        if cur is None:
            return None
        if isinstance(cur, dict):
            cur = cur.get(k)
        else:
            cur = getattr(cur, k, None)
    return cur


def _field_confidence_and_evidence(pred: ContractOutput, group: str, name: str) -> Tuple[float, List[str]]:
    block = _get_nested(pred, group, name)
    if block is None:
        return 0.0, []
    if isinstance(block, dict):
        conf = float(block.get("confidence") or 0.0)
        ev = block.get("evidence_ids") or []
    else:
        conf = float(getattr(block, "confidence", 0.0) or 0.0)
        ev = list(getattr(block, "evidence_ids", None) or [])
    return conf, ev


def _field_status(pred: ContractOutput, group: str, name: str) -> str:
    block = _get_nested(pred, group, name)
    if block is None:
        return "not_found"
    if isinstance(block, dict):
        return str(block.get("status") or "not_found")
    return str(getattr(block, "status", "not_found") or "not_found")


def _normalize_for_compare(obj: Any) -> str:
    if obj is None:
        return ""
    if isinstance(obj, dict):
        return json.dumps(obj, sort_keys=True, default=str)
    return str(obj)


def _status_match(pred_status: str, gt_status: str) -> bool:
    """Treat uncertain ~= present for GT 'present' if user only labels coarse."""
    if pred_status == gt_status:
        return True
    if gt_status == "present" and pred_status in ("present", "uncertain"):
        return True
    if gt_status in ("not_found", "absent") and pred_status in ("not_found", "absent"):
        return True
    return False


def _evaluate_one_field(
    pred: ContractOutput,
    group: str,
    name: str,
    gt_block: Optional[Dict[str, Any]],
) -> FieldMetric:
    pred_status = _field_status(pred, group, name)
    conf, _ = _field_confidence_and_evidence(pred, group, name)

    if not gt_block:
        return FieldMetric(status="unlabeled", confidence=conf, score=None)

    gt_status = str(gt_block.get("status", "not_found")).lower()
    if gt_status == "absent":
        gt_status = "not_found"

    pred_block = _get_nested(pred, group, name)
    pred_nv = pred_block.get("normalized_value") if isinstance(pred_block, dict) else getattr(pred_block, "normalized_value", None)
    gt_nv = gt_block.get("normalized_value")

    status_ok = _status_match(pred_status, gt_status)
    value_ok = True
    if gt_status == "present" and pred_status in ("present", "uncertain") and gt_nv is not None:
        value_ok = _normalize_for_compare(pred_nv) == _normalize_for_compare(gt_nv)

    if not status_ok:
        if gt_status == "present" and pred_status == "not_found":
            return FieldMetric(status="missed", confidence=conf, score=0)
        return FieldMetric(status="incorrect", confidence=conf, score=0)

    if gt_status == "present" and pred_status in ("present", "uncertain"):
        if not value_ok and gt_nv is not None:
            return FieldMetric(status="incorrect", confidence=conf, score=0)
        return FieldMetric(status="correct", confidence=conf, score=1)

    if gt_status in ("not_found", "absent") and pred_status in ("not_found", "absent"):
        return FieldMetric(status="not_found_correct", confidence=conf, score=1)

    return FieldMetric(status="incorrect", confidence=conf, score=0)


def load_ground_truth(contract_id: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Load optional ground truth. File shape:
    {
      "fields": {
        "governing_law": {"status": "present", "normalized_value": {...} optional},
        ...
      }
    }
    Or flat: {"governing_law": {"status": "not_found"}, ...}
    """
    safe_id = re.sub(r"[^\w\-.]+", "_", contract_id)
    candidates = [
        Path(_GROUND_TRUTH_DIR) / f"{safe_id}.json",
        Path(_GROUND_TRUTH_DIR) / f"{contract_id}.json",
    ]
    skip = frozenset({"contract_id", "schema_version", "source", "fields"})
    for path in candidates:
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data.get("fields"), dict):
                    return data["fields"], str(path)
                if isinstance(data, dict):
                    flat = {
                        k: v
                        for k, v in data.items()
                        if k not in skip and not k.startswith("_")
                    }
                    # only treat as GT if at least one known field key
                    names = {t[1] for t in TRACKED_FIELDS}
                    if any(k in names for k in flat):
                        return flat, str(path)
            except Exception:
                continue
    return None, None


def _compute_prf_from_scores(scores: List[int]) -> Tuple[float, float, float]:
    """When each field is binary correct (1) or not (0), micro accuracy = mean."""
    n = len(scores)
    if n == 0:
        return 0.0, 0.0, 0.0
    correct = sum(scores)
    acc = correct / n
    # Equal-weight per-field exact match: precision = recall = f1 = accuracy
    return acc, acc, acc


def _grounding_score(pred: ContractOutput) -> float:
    """Share of fields with valid evidence when extraction claims content; not_found counts as OK."""
    n = len(TRACKED_FIELDS)
    ok = 0
    for group, name in TRACKED_FIELDS:
        _, ev = _field_confidence_and_evidence(pred, group, name)
        st = _field_status(pred, group, name)
        if st in ("not_found", "absent"):
            ok += 1
            continue
        if st in ("present", "uncertain") and len(ev) > 0:
            ok += 1
    return ok / n if n else 0.0


def _avg_confidence(pred: ContractOutput) -> float:
    confs: List[float] = []
    for group, name in TRACKED_FIELDS:
        c, _ = _field_confidence_and_evidence(pred, group, name)
        confs.append(c)
    return sum(confs) / len(confs) if confs else 0.0


def _advanced_loss(f1: float, grounding: float, avg_conf: float) -> float:
    return (
        0.5 * (1.0 - f1)
        + 0.3 * (1.0 - grounding)
        + 0.2 * (1.0 - avg_conf)
    )


def _error_signals(
    field_rows: Dict[str, FieldMetric],
    pred: ContractOutput,
) -> Dict[str, List[str]]:
    low_conf: List[str] = []
    mismatch: List[str] = []
    missing_evidence: List[str] = []
    for key, fm in field_rows.items():
        if fm.confidence is not None and fm.confidence < 0.35:
            low_conf.append(key)
        if fm.score == 0 and fm.status != "unlabeled":
            mismatch.append(key)
        if "." in key:
            parts = key.split(".", 1)
            st = _field_status(pred, *parts)
            _, ev = _field_confidence_and_evidence(pred, *parts)
            if st in ("present", "uncertain") and not ev:
                missing_evidence.append(key)
    return {
        "low_confidence_fields": low_conf,
        "mismatch_or_wrong_fields": mismatch,
        "missing_evidence_fields": missing_evidence,
    }


def evaluate_contract(pred: ContractOutput) -> ContractMetricsPayload:
    """
    Build full metrics payload. If ground truth exists for contract_id, fills accuracy / PRF / field scores.
    Otherwise stores unlabeled field confidences + grounding + proxy loss from confidence/grounding only.
    """
    cid = pred.contract_id
    gt_fields, gt_path = load_ground_truth(cid)

    field_rows: Dict[str, FieldMetric] = {}
    scores: List[int] = []

    tracked_names = [t[1] for t in TRACKED_FIELDS]
    gt_complete = (
        gt_fields is not None and all(gt_fields.get(n) is not None for n in tracked_names)
    )

    for group, name in TRACKED_FIELDS:
        key = f"{group}.{name}"
        gt_block = gt_fields.get(name) if gt_fields else None
        if gt_block is not None and not isinstance(gt_block, dict):
            gt_block = {"status": str(gt_block)}
        fm = _evaluate_one_field(pred, group, name, gt_block if isinstance(gt_block, dict) else None)
        field_rows[key] = fm
        if fm.score is not None:
            scores.append(fm.score)

    grounding = _grounding_score(pred)
    avg_conf = _avg_confidence(pred)

    evaluated = bool(gt_complete) and len(scores) == len(TRACKED_FIELDS)

    if evaluated and scores:
        extraction_accuracy = sum(scores) / len(scores)
        precision, recall, f1 = _compute_prf_from_scores(scores)
        loss_simple = 1.0 - f1
    else:
        extraction_accuracy = None
        precision = None
        recall = None
        f1 = None
        loss_simple = None

    # F1 fallback for loss when no GT: use avg_conf as proxy
    f1_for_loss = f1 if f1 is not None else max(0.0, min(1.0, avg_conf))
    loss_adv = _advanced_loss(f1_for_loss, grounding, avg_conf)

    metrics: Dict[str, Any] = {
        "extraction_accuracy": extraction_accuracy,
        "field_level_scores": {
            k: {
                "status": v.status,
                "confidence": round(v.confidence, 4) if v.confidence is not None else None,
                "score": v.score,
            }
            for k, v in field_rows.items()
        },
        "precision": precision,
        "recall": recall,
        "f1_score": f1,
        "grounding_score": round(grounding, 4),
        "avg_confidence": round(avg_conf, 4),
        "loss": round(loss_simple, 4) if loss_simple is not None else None,
        "loss_weighted": round(loss_adv, 4),
    }

    errors = _error_signals(
        {k: v for k, v in field_rows.items()},
        pred,
    )

    return ContractMetricsPayload(
        contract_id=cid,
        metrics=metrics,
        evaluated_with_ground_truth=evaluated,
        ground_truth_source=gt_path,
        error_signals=errors,
    )


def metrics_filename(contract_id: str) -> str:
    safe = re.sub(r"[^\w\-.]+", "_", contract_id).strip("_") or "contract"
    return f"{safe}_metrics.json"


def save_metrics(pred: ContractOutput) -> Path:
    """Write metrics JSON under METRICS_DIR."""
    payload = evaluate_contract(pred)
    out_dir = Path(_METRICS_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / metrics_filename(pred.contract_id)
    path.write_text(
        json.dumps(payload.model_dump(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def load_metrics_file(contract_id: str) -> Optional[ContractMetricsPayload]:
    path = Path(_METRICS_DIR) / metrics_filename(contract_id)
    if not path.exists():
        # try loose match
        for f in Path(_METRICS_DIR).glob("*_metrics.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if data.get("contract_id") == contract_id:
                    return ContractMetricsPayload(**data)
            except Exception:
                continue
        return None
    try:
        return ContractMetricsPayload(**json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return None
