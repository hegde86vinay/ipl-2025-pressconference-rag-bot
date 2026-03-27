"""
RAG Query Engine — retrieve chunks from ChromaDB + answer via Claude.
CLI usage:  python rag.py "What did Kohli say after the IPL 2025 final?"
"""

import json
import os
import sys
from dataclasses import dataclass

import anthropic
import chromadb
from sentence_transformers import SentenceTransformer

import config

SYSTEM_PROMPT = (
    "You are an expert IPL cricket analyst with access to IPL 2025 press conference "
    "transcripts, match reports, and player interviews. Answer questions using only "
    "the provided context. If the context does not contain enough information, say so "
    "clearly. Always cite which match or interview your answer comes from."
)


@dataclass
class Chunk:
    text: str
    meta: dict
    distance: float


# ── Singleton retriever (lazy-loaded) ────────────────────────────────────────

_retriever: dict = {}


def load_retriever():
    if _retriever:
        return _retriever

    if not os.path.exists(config.VECTORSTORE_DIR):
        raise RuntimeError(
            f"Vector store not found at {config.VECTORSTORE_DIR}. Run embedder.py first."
        )

    client = chromadb.PersistentClient(path=config.VECTORSTORE_DIR)
    collection = client.get_collection(config.COLLECTION_NAME)
    model = SentenceTransformer(config.EMBED_MODEL, device="cpu")

    _retriever["collection"] = collection
    _retriever["model"] = model
    return _retriever


# ── Core pipeline ─────────────────────────────────────────────────────────────

def retrieve(question: str, top_k: int = config.TOP_K) -> list[Chunk]:
    r = load_retriever()
    embedding = r["model"].encode([question], device="cpu").tolist()
    results = r["collection"].query(
        query_embeddings=embedding,
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
    )
    chunks = []
    for text, meta, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        chunks.append(Chunk(text=text, meta=meta, distance=dist))
    return chunks


def build_prompt(question: str, chunks: list[Chunk]) -> str:
    context_parts = []
    for i, c in enumerate(chunks, 1):
        title = c.meta.get("title", "Unknown")
        date  = c.meta.get("date", "")
        url   = c.meta.get("source_url", "")
        context_parts.append(
            f"[{i}] Source: {title} ({date})\nURL: {url}\n\n{c.text}"
        )
    context = "\n\n---\n\n".join(context_parts)
    return f"Context:\n\n{context}\n\nQuestion: {question}"


def ask(question: str) -> dict:
    """Retrieve chunks, call Claude, return answer + sources."""
    chunks = retrieve(question)
    prompt = build_prompt(question, chunks)

    api_key = config.get_api_key()
    client  = anthropic.Anthropic(api_key=api_key)

    response = client.messages.create(
        model=config.LLM_MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )

    answer = next(
        (b.text for b in response.content if b.type == "text"), ""
    )

    sources = [
        {
            "title": c.meta.get("title", ""),
            "date":  c.meta.get("date", ""),
            "teams": c.meta.get("teams", ""),
            "url":   c.meta.get("source_url", ""),
        }
        for c in chunks
    ]

    return {"answer": answer, "sources": sources, "chunks": chunks}


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python rag.py "your question here"')
        sys.exit(1)

    question = " ".join(sys.argv[1:])
    print(f"\nQuestion: {question}\n")
    print("Retrieving context and querying Claude …\n")

    result = ask(question)

    print("Answer:\n")
    print(result["answer"])
    print("\nSources:")
    for i, s in enumerate(result["sources"], 1):
        print(f"  [{i}] {s['title']} ({s['date']}) — {s['url']}")
