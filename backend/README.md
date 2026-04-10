# Contract Intelligence & Structuring Engine

## Overview
An AI-powered pipeline that converts unstructured legal PDFs into structured, validated JSON — identifying contract types, parties, governing law, payment terms, liability caps, and boolean clause flags (non-compete, audit rights, non-solicitation).

## Project Structure
```
contract-intelligence/
├── backend/
│   ├── app/
│   │   ├── main.py               # FastAPI app entry point
│   │   ├── routes/
│   │   │   └── contract_routes.py  # REST API endpoints
│   │   ├── services/
│   │   │   ├── extractor.py      # PDF text extraction (pdfplumber)
│   │   │   ├── chunker.py        # Section-aware chunking
│   │   │   ├── llm_processor.py  # OpenAI LLM extraction
│   │   │   └── batch_processor.py # Async batch runner
│   │   ├── models/
│   │   │   └── schema.py         # Pydantic output schemas
│   │   └── utils/
│   │       └── helpers.py        # Normalization utilities
│   ├── data/
│   │   ├── contracts/            # ← PUT YOUR PDFs HERE
│   │   └── output/               # ← Extracted JSON results saved here
│   ├── .env.example
│   └── requirements.txt
└── frontend/
    └── index.html                # Dashboard UI
```

## Quick Start

### 1. Set up environment
```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure API key
```bash
cp .env.example .env
# Edit .env and set OPENAI_API_KEY=sk-...
```

### 3. Run the server
```bash
cd backend
source venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

Open **http://localhost:8000** in your browser.

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/contracts/upload` | Upload & process a single PDF |
| `POST` | `/api/contracts/batch` | Process all PDFs in `/data/contracts/` |
| `GET`  | `/api/contracts/status` | Live batch processing status |
| `GET`  | `/api/contracts/results` | List all processed results |
| `GET`  | `/api/contracts/results/{file}` | Get result for a specific contract |
| `GET`  | `/api/contracts/health` | Health check + file counts |
| `GET`  | `/api/docs` | Interactive Swagger UI |

---

## Output Schema
```json
{
  "source_file": "contract_001.pdf",
  "contract_type": "Service Agreement",
  "parties": ["Company A", "Company B"],
  "governing_law": "India",
  "jurisdiction": "Courts of Mumbai",
  "payment_terms": "Net 30",
  "liability_cap": "₹10,00,000",
  "notice_period": "30 days",
  "non_compete": true,
  "audit_rights": false,
  "non_solicitation": true,
  "key_clauses": ["Force Majeure", "IP Ownership"],
  "processing_time_sec": 4.21,
  "page_count": 12,
  "error": null
}
```

## Pipeline Architecture
```
PDF → extract_pdf() → DocumentContent (pages)
         ↓
      chunk_document() → List[Chunk] (section + metadata)
         ↓
  classify_contract()  ← first 3 pages → LLM
         ↓
   extract_fields()    ← top-scored chunks → LLM
         ↓
  ContractOutput (Pydantic validated JSON)
         ↓
    data/output/{filename}.json
```

## Environment Variables
| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | — | Required. Your OpenAI API key |
| `OPENAI_MODEL` | `gpt-4o-mini` | Model to use (e.g. `gpt-4o`) |
| `MAX_BATCH_CONCURRENCY` | `5` | Parallel workers for batch |
| `CONTRACTS_DIR` | `data/contracts` | Input PDF directory |
| `OUTPUT_DIR` | `data/output` | Output JSON directory |
