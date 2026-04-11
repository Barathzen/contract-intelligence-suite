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

COLLECTION_NAME = "contract_chunks_mpnet"


from sentence_transformers import SentenceTransformer

# all-mpnet-base-v2 produces 768-dim embeddings (vs 384 for MiniLM)
# It scores significantly higher on semantic similarity benchmarks
_SENTENCE_MODEL = "all-mpnet-base-v2"
_embedder_model = None


def _get_embedder() -> SentenceTransformer:
    global _embedder_model
    if _embedder_model is None:
        print(f"[RAG] Loading embedding model '{_SENTENCE_MODEL}'...")
        _embedder_model = SentenceTransformer(_SENTENCE_MODEL)
        print(f"[RAG] Model loaded — embedding dim: {_embedder_model.get_sentence_embedding_dimension()}")
    return _embedder_model


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
        # Collection name includes model slug so old MiniLM data is not mixed in
        _collection = _chroma_client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine", "model": _SENTENCE_MODEL},
        )
        print(f"[RAG] ChromaDB collection '{COLLECTION_NAME}' ready — {_collection.count()} chunks")
    return _collection


def _embed_texts(texts: List[str]) -> List[List[float]]:
    """Embed a list of texts using all-mpnet-base-v2 (768-dim)."""
    model = _get_embedder()
    embeddings = model.encode(texts, show_progress_bar=False, normalize_embeddings=True)
    return [vec.tolist() for vec in embeddings]


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
    all_embeddings = []

    BATCH_SIZE = 50
    for i in range(0, len(texts), BATCH_SIZE):
        batch_texts = texts[i : i + BATCH_SIZE]
        batch_embeddings = _embed_texts(batch_texts)
        all_embeddings.extend(batch_embeddings)

    # Upsert to Chroma
    collection.add(
        ids=ids,
        embeddings=all_embeddings,
        documents=texts,
        metadatas=metadatas,
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
