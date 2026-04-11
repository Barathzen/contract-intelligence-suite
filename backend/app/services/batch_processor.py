"""
batch_processor.py  — async batch processing for all PDFs using RAG pipeline
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Optional

from app.models.schema import BatchStatusResponse


class BatchState:
    def __init__(self):
        self.status: str = "idle"
        self.total: int = 0
        self.processed: int = 0
        self.failed: int = 0
        self.current_file: Optional[str] = None
        self.completed_files: list[str] = []

    def to_response(self) -> BatchStatusResponse:
        return BatchStatusResponse(
            status=self.status,
            total=self.total,
            processed=self.processed,
            failed=self.failed,
            current_file=self.current_file,
            results=self.completed_files,
        )


_state = BatchState()


def get_batch_state() -> BatchState:
    return _state


# ──────────────────────────────────────────────
# Single file processor (RAG pipeline)
# ──────────────────────────────────────────────

async def _process_file(pdf_path: Path, output_dir: Path, semaphore: asyncio.Semaphore):
    async with semaphore:
        _state.current_file = pdf_path.name
        start = time.time()
        try:
            loop = asyncio.get_running_loop()

            # Step 1: Extract PDF text
            from app.services.extractor import extract_pdf
            doc = await loop.run_in_executor(None, extract_pdf, pdf_path)

            # Step 2: Chunk document
            from app.services.chunker import chunk_document
            chunks = await loop.run_in_executor(None, chunk_document, doc)

            # Step 3: RAG index + Groq extract
            from app.services.llm_processor import process_document_rag
            result = await loop.run_in_executor(
                None, process_document_rag, doc, chunks, pdf_path.name, start
            )

            # Save result
            out_path = output_dir / f"{pdf_path.stem}.json"
            out_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
            _state.completed_files.append(out_path.name)
            _state.processed += 1
            try:
                from app.services.metrics_engine import save_metrics

                save_metrics(result)
            except Exception as mex:
                print(f"[METRICS] Failed to save metrics for {pdf_path.name}: {mex}")

        except Exception as exc:
            _state.failed += 1
            error_record = {
                "source_file": pdf_path.name,
                "error": str(exc),
                "processing_time_sec": round(time.time() - start, 2),
            }
            out_path = output_dir / f"{pdf_path.stem}.error.json"
            out_path.write_text(json.dumps(error_record, indent=2), encoding="utf-8")
            print(f"[BATCH] ❌ Failed: {pdf_path.name} — {exc}")


# ──────────────────────────────────────────────
# Batch runner
# ──────────────────────────────────────────────

async def run_batch(contracts_dir: str, output_dir: str, concurrency: int = 5):
    """
    Process all PDFs in contracts_dir via the RAG pipeline.
    Skips already-processed files (idempotent).
    """
    global _state
    _state = BatchState()
    _state.status = "running"

    contracts_path = Path(contracts_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    pdfs = sorted(contracts_path.glob("*.pdf"))
    pending = []

    for pdf in pdfs:
        result_path = output_path / f"{pdf.stem}.json"
        if result_path.exists():
            _state.processed += 1
            _state.completed_files.append(result_path.name)
        else:
            pending.append(pdf)

    _state.total = len(pdfs)
    print(f"[BATCH] Starting: {len(pending)} pending, {_state.processed} already done")

    semaphore = asyncio.Semaphore(concurrency)
    tasks = [_process_file(pdf, output_path, semaphore) for pdf in pending]

    try:
        await asyncio.gather(*tasks)
        _state.status = "done"
        print(f"[BATCH] ✅ Done. {_state.processed} processed, {_state.failed} failed.")
    except Exception as e:
        _state.status = "error"
        raise e
    finally:
        _state.current_file = None
