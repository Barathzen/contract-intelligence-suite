from __future__ import annotations

from typing import List, Optional, Any, Dict
from pydantic import BaseModel, Field

# ──────────────────────────────────────────────
# Chunk metadata (internal use)
# ──────────────────────────────────────────────
class ChunkMetadata(BaseModel):
    clause_number: Optional[str] = None
    section_title: Optional[str] = None
    page_number: int = 1
    heading_type: Optional[str] = None  # governing_law, payment_terms, other, ...

class Chunk(BaseModel):
    text: str
    metadata: ChunkMetadata

# ──────────────────────────────────────────────
# Core contract output schema matching User Spec
# ──────────────────────────────────────────────

class SourceMetadata(BaseModel):
    file_name: str
    file_type: str
    processed_at: str
    language: str = "en"
    page_count: Optional[int] = None
    ocr_used: bool = False

class ContractType(BaseModel):
    label: str
    confidence: float
    alternate_labels: List[str] = []

class Party(BaseModel):
    name: str
    role: str
    entity_type: str
    confidence: float

class BaseClause(BaseModel):
    status: str
    raw_text: Optional[str] = None
    normalized_value: Optional[Dict[str, Any]] = None
    confidence: float
    risk_level: str
    evidence_ids: List[str] = []

class Clauses(BaseModel):
    governing_law: BaseClause
    audit_rights: BaseClause
    non_compete: BaseClause
    non_solicitation: BaseClause

class StructuredField(BaseModel):
    status: str = "not_found"  # present | uncertain | not_found
    raw_text: Optional[str] = None
    normalized_value: Optional[Dict[str, Any]] = None
    confidence: float
    risk_level: Optional[str] = None
    evidence_ids: List[str] = []

class StructuredFields(BaseModel):
    jurisdiction: StructuredField
    payment_terms: StructuredField
    notice_period: StructuredField
    liability_cap: StructuredField

class RiskSummary(BaseModel):
    risk_score: int
    risk_level: str
    issues: List[str] = []

class ConfidenceSummary(BaseModel):
    overall_confidence: float
    low_confidence_fields: List[str] = []

class EvidenceItem(BaseModel):
    evidence_id: str
    section_heading: str
    text_span: str
    page_no: int
    char_start: int
    char_end: int

from pydantic import BaseModel, Field, ConfigDict

class ProcessingMetadata(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    schema_version: str = "contract_intelligence_v2"
    pipeline_version: str = "two_stage_pipeline_v1"
    model_used: str = "llama-3.3-70b-versatile"
    processing_time_ms: int
    extraction_stage: Optional[str] = None  # e.g. llm_simple_json
    post_processing_stage: Optional[str] = None  # e.g. rule_engine_enrichment

class ContractOutput(BaseModel):
    contract_id: str
    source_metadata: SourceMetadata
    contract_type: ContractType
    parties: List[Party]
    clauses: Clauses
    structured_fields: StructuredFields
    risk_summary: RiskSummary
    confidence_summary: ConfidenceSummary
    evidence_index: List[EvidenceItem]
    processing_metadata: ProcessingMetadata


# ──────────────────────────────────────────────
# API response wrappers
# ──────────────────────────────────────────────

class UploadResponse(BaseModel):
    success: bool
    filename: str
    data: Optional[ContractOutput] = None
    error: Optional[str] = None


class BatchStatusResponse(BaseModel):
    status: str          # "idle" | "running" | "done" | "error"
    total: int
    processed: int
    failed: int
    current_file: Optional[str] = None
    results: List[str] = Field(default_factory=list)  # list of output JSON filenames


class ResultsListResponse(BaseModel):
    count: int
    results: List[ContractOutput]
