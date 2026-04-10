"""
main.py  — FastAPI application entry point
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

load_dotenv()

from app.routes.contract_routes import router as contract_router

# ──────────────────────────────────────────────
# App factory
# ──────────────────────────────────────────────

app = FastAPI(
    title="Contract Intelligence & Structuring Engine",
    description="Converts unstructured legal PDFs into structured, machine-readable JSON.",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

# Allow all origins for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ──────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────

app.include_router(contract_router)

# ──────────────────────────────────────────────
# Startup: ensure required directories exist
# ──────────────────────────────────────────────

@app.on_event("startup")
async def startup_event():
    contracts_dir = os.getenv("CONTRACTS_DIR", "data/contracts")
    output_dir = os.getenv("OUTPUT_DIR", "data/output")
    Path(contracts_dir).mkdir(parents=True, exist_ok=True)
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    Path("data/tmp").mkdir(parents=True, exist_ok=True)
    print(f"✅ Contract Intelligence Engine ready (Groq + RAG).")
    print(f"   PDFs         : {contracts_dir}")
    print(f"   Output       : {output_dir}")
    print(f"   Vector store : {os.getenv('VECTORSTORE_DIR', 'data/vectorstore')}")
    print(f"   API docs     : http://localhost:8000/api/docs")
    print(f"   UI           : http://localhost:8000")

# ──────────────────────────────────────────────
# Serve frontend
# ──────────────────────────────────────────────

FRONTEND_DIR = Path(__file__).parent.parent.parent / "frontend" / "dist"

if FRONTEND_DIR.exists():
    # Mount assets folder explicitly so Vite generated files work
    assets_dir = FRONTEND_DIR / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_frontend(full_path: str):
        path = FRONTEND_DIR / full_path
        if path.is_file():
            return FileResponse(str(path))
        return FileResponse(str(FRONTEND_DIR / "index.html"))
