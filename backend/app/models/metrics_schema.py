"""Per-contract evaluation metrics (report card) — stored as JSON alongside outputs."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class FieldMetric(BaseModel):
    status: str  # correct | incorrect | not_found_correct | missed | unlabeled
    confidence: Optional[float] = None
    score: Optional[int] = None  # 0 or 1 when labeled


class ContractMetricsPayload(BaseModel):
    """Written to data/metrics/{contract_id}_metrics.json"""

    contract_id: str
    metrics: Dict[str, Any] = Field(default_factory=dict)
    evaluated_with_ground_truth: bool = False
    ground_truth_source: Optional[str] = None
    error_signals: Dict[str, List[str]] = Field(default_factory=dict)
