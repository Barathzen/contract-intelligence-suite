"""
contract_routes.py  — REST endpoints (now RAG-powered)
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import List

import aiofiles
from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from app.models.schema import (
    BatchStatusResponse, ContractOutput, ResultsListResponse, UploadResponse
)
from app.services.batch_processor import get_batch_state, run_batch
from app.services.chunker import chunk_document
from app.services.extractor import extract_pdf
from app.services.llm_processor import process_document_rag
from app.services.metrics_engine import load_metrics_file, save_metrics

router = APIRouter(prefix="/api/contracts", tags=["contracts"])

_BACKEND_DIR = Path(__file__).resolve().parents[2]


def _env_path(key: str, default_relative: str) -> str:
    raw = os.getenv(key, default_relative)
    p = Path(raw)
    return str(p.resolve() if p.is_absolute() else (_BACKEND_DIR / p).resolve())


_CONTRACTS_DIR = _env_path("CONTRACTS_DIR", str(_BACKEND_DIR.parent / "data" / "contracts"))
_OUTPUT_DIR = _env_path("OUTPUT_DIR", str(_BACKEND_DIR.parent / "data" / "output"))
_UPLOAD_TMP = Path(_BACKEND_DIR.parent / "data" / "tmp").resolve()
_MAX_CONCURRENCY = int(os.getenv("MAX_BATCH_CONCURRENCY", "5"))


def _load_result(json_path: Path) -> ContractOutput | None:
    try:
        return ContractOutput(**json.loads(json_path.read_text(encoding="utf-8")))
    except Exception:
        return None


# ──────────────────────────────────────────────
# POST /upload  — single PDF (full RAG pipeline)
# ──────────────────────────────────────────────

@router.post("/upload", response_model=UploadResponse)
async def upload_contract(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    _UPLOAD_TMP.mkdir(parents=True, exist_ok=True)
    tmp_path = _UPLOAD_TMP / file.filename

    async with aiofiles.open(tmp_path, "wb") as f:
        await f.write(await file.read())

    start = time.time()
    try:
        loop = asyncio.get_running_loop()
        doc    = await loop.run_in_executor(None, extract_pdf, tmp_path)
        chunks = await loop.run_in_executor(None, chunk_document, doc)
        result = await loop.run_in_executor(
            None, process_document_rag, doc, chunks, file.filename, start
        )

        out_path = Path(_OUTPUT_DIR)
        out_path.mkdir(parents=True, exist_ok=True)
        (out_path / f"{Path(file.filename).stem}.json").write_text(
            result.model_dump_json(indent=2), encoding="utf-8"
        )
        try:
            save_metrics(result)
        except Exception as exc:
            print(f"[METRICS] Failed to save metrics: {exc}")
        return UploadResponse(success=True, filename=file.filename, data=result)

    except Exception as exc:
        return UploadResponse(success=False, filename=file.filename, error=str(exc))
    finally:
        tmp_path.unlink(missing_ok=True)


# ──────────────────────────────────────────────
# POST /batch  — trigger batch
# ──────────────────────────────────────────────

@router.post("/batch", response_model=BatchStatusResponse)
async def trigger_batch(background_tasks: BackgroundTasks):
    state = get_batch_state()
    if state.status == "running":
        raise HTTPException(status_code=409, detail="Batch is already running.")
    background_tasks.add_task(run_batch, _CONTRACTS_DIR, _OUTPUT_DIR, _MAX_CONCURRENCY)
    return BatchStatusResponse(status="started", total=0, processed=0, failed=0)


# ──────────────────────────────────────────────
# GET /status
# ──────────────────────────────────────────────

@router.get("/status", response_model=BatchStatusResponse)
async def batch_status():
    return get_batch_state().to_response()


# ──────────────────────────────────────────────
# GET /results  — list all processed
# ──────────────────────────────────────────────

@router.get("/results", response_model=ResultsListResponse)
async def list_results():
    output_path = Path(_OUTPUT_DIR)
    output_path.mkdir(parents=True, exist_ok=True)
    results: List[ContractOutput] = []
    for jf in sorted(output_path.glob("*.json")):
        if jf.name.endswith(".error.json"):
            continue
        r = _load_result(jf)
        if r:
            results.append(r)
    return ResultsListResponse(count=len(results), results=results)


# ──────────────────────────────────────────────
# GET /results/{filename}
# ──────────────────────────────────────────────

@router.get("/results/{filename}", response_model=ContractOutput)
async def get_result(filename: str):
    stem = filename.replace(".json", "").replace(".pdf", "")
    json_path = Path(_OUTPUT_DIR) / f"{stem}.json"
    if not json_path.exists():
        raise HTTPException(status_code=404, detail=f"No result found for '{filename}'")
    result = _load_result(json_path)
    if not result:
        raise HTTPException(status_code=500, detail="Failed to parse result file.")
    return result


# ──────────────────────────────────────────────
# GET /health
# ──────────────────────────────────────────────

@router.get("/metrics/{contract_id}")
async def get_contract_metrics(contract_id: str):
    """
    Per-contract report card (JSON). File: data/metrics/{contract_id}_metrics.json
    Requires contract_id as stored in output JSON (e.g. CTR-001).
    """
    payload = load_metrics_file(contract_id)
    if not payload:
        raise HTTPException(status_code=404, detail="No metrics file for this contract. Process the contract first.")
    return JSONResponse(content=payload.model_dump())


@router.get("/health")
async def health():
    from app.services.embedder import collection_size, indexed_files
    contracts_path = Path(_CONTRACTS_DIR)
    output_path    = Path(_OUTPUT_DIR)
    pdf_count       = len(list(contracts_path.glob("*.pdf"))) if contracts_path.exists() else 0
    processed_count = len([f for f in output_path.glob("*.json") if not f.name.endswith(".error.json")]) if output_path.exists() else 0
    return {
        "status": "ok",
        "contracts_available": pdf_count,
        "contracts_processed": processed_count,
        "rag_indexed_chunks": collection_size(),
        "rag_indexed_files": len(indexed_files()),
    }


# ──────────────────────────────────────────────
# GET /rag/status  — vector store stats
# ──────────────────────────────────────────────

@router.get("/rag/status")
async def rag_status():
    from app.services.embedder import collection_size, indexed_files
    files = indexed_files()
    return {
        "total_chunks": collection_size(),
        "indexed_files": len(files),
        "files": files,
    }
