"""
rag_retriever.py — Semantic retrieval from ChromaDB for RAG-based extraction (Groq Powered)

Given a natural-language query, finds the most relevant contract chunks
from a specific source document using cosine similarity on Groq embeddings.
"""

from __future__ import annotations

from typing import List

from app.models.schema import Chunk, ChunkMetadata
from app.services.embedder import _get_collection, _embed_texts


# ──────────────────────────────────────────────
# Field-specific retrieval queries
# Targeted questions drive higher recall for each extraction field
# ──────────────────────────────────────────────

FIELD_QUERIES = {
    "parties": "Who are the parties to this agreement? Names of companies or individuals signing the contract.",
    "contract_type": "What type of legal agreement or contract is this? Service agreement, lease, NDA, IP agreement?",
    "governing_law": "What is the governing law clause? Which country or state law governs this contract?",
    "jurisdiction": "What is the jurisdiction for disputes? Which court or arbitration body handles disputes?",
    "payment_terms": "What are the payment terms? Net 30, invoice cycles, milestone payments, monthly fees?",
    "liability_cap": "What is the liability_cap or maximum liability? What is the ceiling on damages or indemnification?",
    "notice_period": "What is the notice period for termination? How many days notice is required to terminate the contract?",
    "non_compete": "Is there a non-compete clause? Restrictions on competition after contract ends?",
    "audit_rights": "Are there audit rights or inspection rights? Can a party audit books or inspect records?",
    "non_solicitation": "Is there a non-solicitation clause? Restrictions on poaching employees or clients?",
    "key_clauses": "What are the important clauses in this contract? Force majeure, IP ownership, confidentiality, indemnification?",
}


def retrieve_for_field(
    field: str,
    source_file: str,
    top_k: int = 6,
) -> List[Chunk]:
    """
    Retrieve the top-k most relevant chunks for a specific field query,
    filtered to only the given source_file.
    """
    query = FIELD_QUERIES.get(field, field)
    return _retrieve(query=query, source_file=source_file, top_k=top_k)


def retrieve_all_relevant(
    source_file: str,
    top_k_per_field: int = 4,
    deduplicate: bool = True,
) -> List[Chunk]:
    """
    Run retrieval for all key fields and merge results.
    Returns a deduplicated ordered list of the most relevant chunks.
    Used to build one comprehensive context window for LLM extraction.
    """
    seen_texts: set[str] = set()
    combined: List[Chunk] = []

    for field in FIELD_QUERIES:
        chunks = retrieve_for_field(field, source_file, top_k=top_k_per_field)
        for chunk in chunks:
            key = chunk.text[:120]  # deduplicate by first 120 chars
            if deduplicate and key in seen_texts:
                continue
            seen_texts.add(key)
            combined.append(chunk)

    return combined


from rank_bm25 import BM25Okapi
import traceback

def _retrieve(query: str, source_file: str, top_k: int = 6) -> List[Chunk]:
    """Core retrieval: Fetch all chunks for source_file, embed query, run BM25, and use RRF."""
    try:
        col = _get_collection()

        # Get the query vector
        query_vecs = _embed_texts([query])
        if not query_vecs:
            raise RuntimeError("Embedding service returned empty vectors for query")
        query_vec = query_vecs[0]

        # 1. First, fetch ALL chunks for the given source file from ChromaDB
        results = col.get(
            where={"source_file": source_file},
            include=["documents", "metadatas", "embeddings"],
        )

        docs = results.get("documents") or []
        metas = results.get("metadatas") or []
        embeddings = results.get("embeddings") or []

        if not docs:
            return []

        n_results = max(1, min(top_k * 2, len(docs)))  # clamp: never exceed available docs

        # Build Chunk objects (guard against metadata length mismatch)
        all_chunks: List[Chunk] = []
        for idx, text in enumerate(docs):
            meta = metas[idx] if idx < len(metas) else {}
            page_num = 1
            try:
                page_num = int(meta.get("page_number", 1))
            except Exception:
                page_num = 1
            all_chunks.append(Chunk(
                text=text,
                metadata=ChunkMetadata(
                    clause_number=meta.get("clause_number") or None,
                    section_title=meta.get("section_title") or None,
                    page_number=page_num,
                    heading_type=meta.get("heading_type") or None,
                )
            ))

        # 2. Semantic ranking via ChromaDB query
        semantic_results = col.query(
            query_embeddings=[query_vec],
            n_results=n_results,
            where={"source_file": source_file},
            include=["documents", "distances"]
        )

        # semantic_results['documents'] may be nested or flat depending on Chroma client
        sem_docs = semantic_results.get("documents")
        if not sem_docs:
            semantic_ranked_docs = []
        else:
            # If it's a list-of-lists, take first; else if flat list, use it
            if isinstance(sem_docs, list) and len(sem_docs) > 0 and isinstance(sem_docs[0], list):
                semantic_ranked_docs = sem_docs[0]
            else:
                semantic_ranked_docs = sem_docs

        # Build map: text -> semantic rank (1-indexed)
        semantic_ranks = {text: rank + 1 for rank, text in enumerate(semantic_ranked_docs)}

        # 3. Compute BM25 scores (guard tokenization)
        tokenized_corpus = []
        for d in docs:
            try:
                tokenized_corpus.append(d.lower().split())
            except Exception:
                tokenized_corpus.append([])

        if not any(tokenized_corpus):
            # fallback: return semantic top-k
            return [
                Chunk(text=t, metadata=ChunkMetadata(page_number=1, heading_type=None))
                for t in semantic_ranked_docs[:top_k]
            ]

        bm25 = BM25Okapi(tokenized_corpus)
        tokenized_query = query.lower().split()
        bm25_scores = bm25.get_scores(tokenized_query)

        # Sort docs by BM25 score
        bm25_ranked = sorted(zip(docs, bm25_scores), key=lambda x: x[1], reverse=True)
        bm25_ranks = {doc: rank + 1 for rank, (doc, score) in enumerate(bm25_ranked)}

        # 4. Reciprocal Rank Fusion (RRF)
        RRF_K = 60
        rrf_scores = []
        for i, chunk in enumerate(all_chunks):
            s_rank = semantic_ranks.get(chunk.text, len(docs) + 1)
            b_rank = bm25_ranks.get(chunk.text, len(docs) + 1)
            score = (1.0 / (RRF_K + s_rank)) + (1.0 / (RRF_K + b_rank))
            rrf_scores.append((score, chunk))

        # Sort by best RRF score
        rrf_scores.sort(key=lambda x: x[0], reverse=True)
        # Return top-k
        return [chunk for score, chunk in rrf_scores[:top_k]]

    except Exception as exc:
        print(f"[RAG] Retrieval error for '{source_file}': {exc}")
        traceback.print_exc()
        return []
