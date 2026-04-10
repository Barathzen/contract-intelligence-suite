"""
embedder.py — Build and manage ChromaDB vector store from contract chunks using Groq Embeddings
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
from groq import Groq

load_dotenv()

_VECTORSTORE_DIR = os.getenv(
    "VECTORSTORE_DIR",
    "/mnt/B89EC7B79EC76D06/contract-intelligence/data/vectorstore"
)
_EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text-v1.5")

# Lazy singletons
_client: Optional[Groq] = None
_chroma_client = None
_collection = None

COLLECTION_NAME = "contract_chunks_groq"


from sentence_transformers import SentenceTransformer

_embedder_model = None

def _get_embedder():
    global _embedder_model
    if _embedder_model is None:
        print("[RAG] Loading local MiniLM model...")
        _embedder_model = SentenceTransformer("all-MiniLM-L6-v2")
    return _embedder_model


def _get_collection():
    global _chroma_client, _collection
    if _collection is None:
        import chromadb
        Path(_VECTORSTORE_DIR).mkdir(parents=True, exist_ok=True)
        _chroma_client = chromadb.PersistentClient(path=_VECTORSTORE_DIR)
        
        # We change the collection name to isolate Groq embeddings from previous local ones
        _collection = _chroma_client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine", "model": _EMBED_MODEL},
        )
        print(f"[RAG] ChromaDB collection '{COLLECTION_NAME}' ready — {_collection.count()} chunks")
    return _collection


def _embed_texts(texts: List[str]) -> List[List[float]]:
    """Get embeddings from local MiniLM."""
    model = _get_embedder()
    embeddings = model.encode(texts, show_progress_bar=False)
    # Convert numpy arrays to lists of float
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
        }
        for c in chunks
    ]

    # Batch embed via Groq
    # Note: Groq might have limits on input size per request, but usually 
    # it can handle dozens of small-to-medium chunks at once.
    # We'll batch in chunks of 50 just to be safe.
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
