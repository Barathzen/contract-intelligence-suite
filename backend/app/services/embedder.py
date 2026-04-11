"""
embedder.py — Build and manage ChromaDB vector store from contract chunks using all-mpnet-base-v2
"""

from __future__ import annotations

import os
os.environ["ANONYMIZED_TELEMETRY"] = "False"
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv

load_dotenv()

_VECTORSTORE_DIR = os.getenv(
    "VECTORSTORE_DIR",
    "/mnt/B89EC7B79EC76D06/contract-intelligence/data/vectorstore"
)

# Lazy singletons
_chroma_client = None
_collection = None

from openai import OpenAI

_SENTENCE_MODEL = os.getenv("EMBED_MODEL", "text-embedding-3-small")

_openai_client = None

def _get_openai_client():
    global _openai_client
    if _openai_client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set. Please add it to your .env file.")
        _openai_client = OpenAI(api_key=api_key)
        print(f"[RAG] OpenAI Embedding Client initialized for '{_SENTENCE_MODEL}'")
    return _openai_client

def _embed_texts(texts: List[str]) -> List[List[float]]:
    """Embed a list of texts using explicit OpenAI SDK (bypass Chroma legacy hooks)."""
    client = _get_openai_client()
    response = client.embeddings.create(
        input=texts,
        model=_SENTENCE_MODEL
    )
    return [data.embedding for data in response.data]


def _get_collection():
    global _chroma_client, _collection
    if _collection is None:
        import chromadb
        from chromadb.config import Settings
        Path(_VECTORSTORE_DIR).mkdir(parents=True, exist_ok=True)
        _chroma_client = chromadb.PersistentClient(
            path=_VECTORSTORE_DIR,
            settings=Settings(anonymized_telemetry=False)
        )
        # Using a new collection name prevents mixing 768-dim mpnet vs 1536-dim OpenAI
        _collection = _chroma_client.get_or_create_collection(
            name="contract_chunks_openai",
            metadata={"hnsw:space": "cosine", "model": _SENTENCE_MODEL},
        )
        print(f"[RAG] ChromaDB collection 'contract_chunks_openai' ready — {_collection.count()} chunks")
    return _collection


# ──────────────────────────────────────────────
# Index a document's chunks
# ──────────────────────────────────────────────

def index_document(source_file: str, chunks) -> int:
    """
    Embed and store all chunks for a document in the vector store.
    Overwrites any existing chunks for the same source_file.
    Returns number of chunks indexed.
    """
    if not chunks:
        return 0

    collection = _get_collection()

    # Remove existing entries for this file (idempotent)
    try:
        existing = collection.get(where={"source_file": source_file})
        if existing["ids"]:
            collection.delete(ids=existing["ids"])
    except Exception:
        pass

    texts = [c.text for c in chunks]
    metadatas = [
        {
            "source_file": source_file,
            "clause_number": c.metadata.clause_number or "",
            "section_title": c.metadata.section_title or "",
            "page_number": c.metadata.page_number,
            "heading_type": c.metadata.heading_type or "",
        }
        for c in chunks
    ]

    # Batch embed in groups of 50 to keep memory usage predictable
    ids = [f"{source_file}::chunk::{i}" for i in range(len(texts))]

    BATCH_SIZE = 50
    for i in range(0, len(texts), BATCH_SIZE):
        batch_texts = texts[i : i + BATCH_SIZE]
        batch_ids = ids[i : i + BATCH_SIZE]
        batch_metas = metadatas[i : i + BATCH_SIZE]
        batch_embeddings = _embed_texts(batch_texts)
        
        # Upsert with explicit embeddings
        collection.add(
            ids=batch_ids,
            embeddings=batch_embeddings,
            documents=batch_texts,
            metadatas=batch_metas,
        )



    return len(chunks)


def collection_size() -> int:
    """Return total number of indexed chunks."""
    try:
        return _get_collection().count()
    except Exception:
        return 0


def indexed_files() -> List[str]:
    """Return list of source files that have been indexed."""
    try:
        col = _get_collection()
        results = col.get(include=["metadatas"])
        files = list({m["source_file"] for m in results["metadatas"]})
        return sorted(files)
    except Exception:
        return []
