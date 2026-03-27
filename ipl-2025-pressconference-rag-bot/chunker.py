"""
Chunker — loads raw .txt files, splits into overlapping token chunks,
saves metadata-enriched chunks to data/chunks/chunks.json
Run: python chunker.py
"""

import glob
import hashlib
import json
import os

import tiktoken

import config

os.makedirs("data/chunks", exist_ok=True)

enc = tiktoken.get_encoding("cl100k_base")


def load_raw_docs(data_dir: str) -> list[dict]:
    """Load every .txt file and its .json sidecar."""
    docs = []
    for txt_path in sorted(glob.glob(os.path.join(data_dir, "*.txt"))):
        json_path = txt_path.replace(".txt", ".json")
        try:
            with open(txt_path) as f:
                text = f.read().strip()
            meta = {}
            if os.path.exists(json_path):
                with open(json_path) as f:
                    meta = json.load(f)
            meta["file_path"] = txt_path
            docs.append({"text": text, "meta": meta})
        except Exception as e:
            print(f"  WARN: could not load {txt_path}: {e}")
    return docs


def chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Split text into overlapping token windows."""
    tokens = enc.encode(text)
    chunks = []
    start = 0
    while start < len(tokens):
        end = min(start + chunk_size, len(tokens))
        chunk_tokens = tokens[start:end]
        chunks.append(enc.decode(chunk_tokens))
        if end == len(tokens):
            break
        start += chunk_size - overlap
    return chunks


def make_chunk_id(source_url: str, chunk_index: int) -> str:
    raw = f"{source_url}::{chunk_index}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def process_docs(docs: list[dict]) -> list[dict]:
    all_chunks = []
    for doc in docs:
        text = doc["text"]
        meta = doc["meta"]
        raw_chunks = chunk_text(text, config.CHUNK_SIZE, config.CHUNK_OVERLAP)
        total = len(raw_chunks)
        source_url = meta.get("source_url", meta.get("file_path", "unknown"))

        for idx, chunk_text_str in enumerate(raw_chunks):
            chunk = {
                "id": make_chunk_id(source_url, idx),
                "text": chunk_text_str,
                "chunk_index": idx,
                "total_chunks": total,
                **meta,   # flatten all metadata fields into the chunk
            }
            all_chunks.append(chunk)
    return all_chunks


if __name__ == "__main__":
    print(f"Loading documents from {config.DATA_DIR} …")
    docs = load_raw_docs(config.DATA_DIR)

    if not docs:
        print("No documents found. Run scraper.py first.")
        raise SystemExit(1)

    print(f"Loaded {len(docs)} documents — chunking …")
    chunks = process_docs(docs)

    with open(config.CHUNKS_PATH, "w") as f:
        json.dump(chunks, f, indent=2)

    print(f"Chunked {len(docs)} docs into {len(chunks)} chunks → {config.CHUNKS_PATH}")
