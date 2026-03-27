"""
Embedder — embeds chunks with all-MiniLM-L6-v2 and stores in ChromaDB.
Re-run safe: already-embedded chunks (by hash ID) are skipped.
Run: python embedder.py
"""

import json
import os

import chromadb
from sentence_transformers import SentenceTransformer

import config

BATCH_SIZE = 32


def load_chunks(path: str) -> list[dict]:
    with open(path) as f:
        return json.load(f)


def build_client_and_collection() -> tuple[chromadb.Client, chromadb.Collection]:
    os.makedirs(config.VECTORSTORE_DIR, exist_ok=True)
    client = chromadb.PersistentClient(path=config.VECTORSTORE_DIR)
    collection = client.get_or_create_collection(
        name=config.COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )
    return client, collection


def embed_chunks(chunks: list[dict], collection: chromadb.Collection, model: SentenceTransformer):
    # Find which IDs are already stored
    existing = set(collection.get(include=[])["ids"])

    pending = [c for c in chunks if c["id"] not in existing]
    if not pending:
        print("All chunks already embedded — nothing to do.")
        return

    print(f"Embedding {len(pending)} new chunks (skipping {len(existing)} already stored) …")

    for batch_start in range(0, len(pending), BATCH_SIZE):
        batch = pending[batch_start: batch_start + BATCH_SIZE]

        texts = [c["text"] for c in batch]
        ids   = [c["id"]   for c in batch]

        # Build metadata dicts — ChromaDB requires str/int/float/bool values only
        metadatas = []
        for c in batch:
            meta = {
                k: (str(v) if not isinstance(v, (str, int, float, bool)) else v)
                for k, v in c.items()
                if k not in ("text", "id")
            }
            metadatas.append(meta)

        embeddings = model.encode(texts, device="cpu", show_progress_bar=False).tolist()

        collection.add(ids=ids, embeddings=embeddings, documents=texts, metadatas=metadatas)

        done = min(batch_start + BATCH_SIZE, len(pending))
        print(f"  Embedded {done}/{len(pending)} chunks …")

    print(f"Done. Collection '{config.COLLECTION_NAME}' now has {collection.count()} vectors.")


if __name__ == "__main__":
    if not os.path.exists(config.CHUNKS_PATH):
        print(f"Chunks file not found at {config.CHUNKS_PATH}. Run chunker.py first.")
        raise SystemExit(1)

    print(f"Loading chunks from {config.CHUNKS_PATH} …")
    chunks = load_chunks(config.CHUNKS_PATH)
    print(f"Loaded {len(chunks)} chunks.")

    print(f"Loading embedding model '{config.EMBED_MODEL}' on CPU …")
    model = SentenceTransformer(config.EMBED_MODEL, device="cpu")

    _, collection = build_client_and_collection()
    embed_chunks(chunks, collection, model)
