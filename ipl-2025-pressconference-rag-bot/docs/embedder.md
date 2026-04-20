# Embedder

## Overview

`embedder.py` is the **vector indexing layer**. It takes every chunk from `chunks.json`, converts it into a dense floating-point vector using a local embedding model, and stores the vectors — alongside the original text and metadata — in a persistent ChromaDB collection on disk.

This step runs once (or incrementally when new chunks are added). The resulting vector store is what makes semantic search possible: instead of matching keywords, the RAG engine can find chunks that are *conceptually similar* to a question even when they share no words with it.

---

## Tech Stack

| Library | Version | Role | Why this choice |
|---------|---------|------|-----------------|
| `sentence-transformers` | 3.3 | Embedding model wrapper | De-facto standard for local semantic embeddings; supports 100+ HuggingFace models with a one-line API |
| `all-MiniLM-L6-v2` | — | Embedding model | 22 MB, 256-token context, 384-dim vectors; fastest CPU-runnable model with strong semantic similarity benchmarks (MTEB top-10 at its size class) |
| `chromadb` | 0.5.23 | Vector store | Fully local, zero-config, persistent storage; cosine similarity search built-in; no cloud account needed |
| `json` | stdlib | Chunk loading | Reads the flat list produced by chunker.py |

**Why `all-MiniLM-L6-v2` over larger models?**

| Model | Dim | Size | Speed (M2 CPU) | Quality |
|-------|-----|------|----------------|---------|
| `all-MiniLM-L6-v2` | 384 | 22 MB | ~1 000 chunks/min | Good |
| `all-mpnet-base-v2` | 768 | 438 MB | ~200 chunks/min | Better |
| `text-embedding-3-small` (OpenAI API) | 1 536 | — | API latency | Excellent |
| `amazon.titan-embed-text-v2:0` (AWS Bedrock) | 1 536 | — | API latency | Excellent |

For a hobby project on M2 Air with 8 GB RAM, MiniLM hits the right tradeoff: fast enough to embed ~400 chunks in under 8 minutes, good enough for cricket quote retrieval where sentences are relatively short and domain-specific.

> **AWS Bedrock alternative:** Titan Embeddings V2 produces 1 536-dim vectors with an 8 192-token context window (vs MiniLM's 256-token hard truncation), which means long chunks are fully encoded rather than silently truncated. See [`docs/bedrock.md`](bedrock.md) for the full migration path.

**Why ChromaDB over FAISS / Pinecone / OpenSearch?**

| | ChromaDB | FAISS | Pinecone | OpenSearch Serverless |
|--|---------|-------|---------|----------------------|
| Setup | `pip install` | `pip install` + compile | Cloud account | IAM + boto3 |
| Persistence | Auto (SQLite + files) | Manual save/load | Cloud | Cloud (managed) |
| Metadata filtering | Built-in | Not built-in | Built-in | Built-in |
| Re-run safety | ID-based upsert | Manual dedup | ID-based | ID-based upsert |
| Local-only | ✅ | ✅ | ❌ | ❌ |
| Managed / HA | ❌ | ❌ | ✅ | ✅ |

OpenSearch Serverless is the vector store used in the AWS Bedrock alternative — see [`docs/bedrock.md`](bedrock.md).

**Why `device="cpu"` explicitly?**
macOS MPS (Metal Performance Shaders) backend in PyTorch has known compatibility issues with `sentence-transformers` on some macOS + Python version combinations. Forcing CPU avoids silent correctness bugs in vector outputs.

---

## Component Diagram

```mermaid
flowchart TD
    START(["▶ python embedder.py"])

    subgraph INIT["Initialisation"]
        I1["Load chunks.json\ninto memory"]
        I2["SentenceTransformer\n'all-MiniLM-L6-v2'\ndevice=cpu"]
        I3["chromadb.PersistentClient\npath=vectorstore/chroma_db/"]
        I4["get_or_create_collection\n'ipl_2025_presscon'\nhnsw:space=cosine"]
        I1 --> I2 --> I3 --> I4
    end

    subgraph DEDUP["De-duplication Check"]
        D1["collection.get(include=[])\n→ existing ID set"]
        D2["Filter chunks:\npending = [c for c in chunks\n  if c.id NOT IN existing]"]
        D3{"pending\nis empty?"}
        D4["Print: nothing to do\nExit"]
        D1 --> D2 --> D3
        D3 -- "Yes" --> D4
        D3 -- "No" --> EMBED
    end

    subgraph EMBED["Embedding Loop — batches of 32"]
        E1["Slice batch:\npending[i : i+32]"]
        E2["Extract texts list"]
        E3["model.encode(texts\n  device='cpu'\n  show_progress_bar=False)\n→ float32 ndarray\nshape: (batch, 384)"]
        E4["Build metadatas list:\ncast non-scalar values → str\nexclude 'text' and 'id' keys"]
        E5["collection.add(\n  ids=ids,\n  embeddings=embeddings,\n  documents=texts,\n  metadatas=metadatas\n)"]
        E6["Print progress:\nEmbedded X/N chunks …"]
        E7{"More\nbatches?"}
        E1 --> E2 --> E3 --> E4 --> E5 --> E6 --> E7
        E7 -- "Yes" --> E1
        E7 -- "No" --> DONE
    end

    DONE(["✅ Collection has M vectors\nvectorstore/chroma_db/"])

    START --> INIT --> DEDUP
    EMBED --> DONE

    classDef io       fill:#f3e8ff,stroke:#9333ea,color:#3b0764
    classDef model    fill:#fef9c3,stroke:#ca8a04,color:#713f12
    classDef store    fill:#dcfce7,stroke:#16a34a,color:#14532d
    classDef decision fill:#dbeafe,stroke:#3b82f6,color:#1e3a5f
    classDef error    fill:#fee2e2,stroke:#dc2626,color:#7f1d1d

    class I1,DONE io
    class I2,E3 model
    class I3,I4,E5 store
    class D3,E7 decision
    class D4 error
```

---

## Sequence Diagram

```mermaid
sequenceDiagram
    actor User
    participant Embedder  as embedder.py
    participant FS        as data/chunks/<br/>chunks.json
    participant ST        as SentenceTransformer<br/>all-MiniLM-L6-v2 (CPU)
    participant Chroma    as ChromaDB<br/>PersistentClient
    participant Disk      as vectorstore/<br/>chroma_db/

    User->>Embedder: python embedder.py

    Embedder->>FS: json.load(chunks.json)
    FS-->>Embedder: list of N chunk objects

    Embedder->>ST: SentenceTransformer("all-MiniLM-L6-v2", device="cpu")
    Note over ST: Downloads model (~22 MB) on first run<br/>then loads from ~/.cache/

    Embedder->>Chroma: PersistentClient(path="vectorstore/chroma_db/")
    Chroma->>Disk: open / create SQLite + HNSW index files
    Disk-->>Chroma: ready

    Embedder->>Chroma: get_or_create_collection("ipl_2025_presscon", cosine)
    Chroma-->>Embedder: collection handle

    Embedder->>Chroma: collection.get(include=[]) → existing IDs
    Chroma-->>Embedder: set of already-embedded chunk IDs

    Embedder->>Embedder: pending = chunks where id ∉ existing_ids

    alt No pending chunks
        Embedder-->>User: All chunks already embedded — nothing to do.
    else Pending chunks exist
        loop Batches of 32
            Embedder->>Embedder: slice batch[i : i+32]

            Embedder->>ST: encode(texts, device="cpu")
            Note over ST: BPE tokenise → transformer forward pass<br/>→ mean-pool → L2-normalise
            ST-->>Embedder: float32 ndarray (batch_size × 384)

            Embedder->>Embedder: cast metadata values to str/int/float/bool

            Embedder->>Chroma: collection.add(ids, embeddings, documents, metadatas)
            Chroma->>Disk: persist vectors + metadata to HNSW + SQLite
            Disk-->>Chroma: write confirmed
            Chroma-->>Embedder: OK

            Embedder-->>User: Embedded X/N chunks …
        end

        Embedder->>Chroma: collection.count()
        Chroma-->>Embedder: total vector count M

        Embedder-->>User: Done. Collection 'ipl_2025_presscon' has M vectors.
    end
```

---

## What the Embedding Model Actually Does

```
Input text (string)
       │
       ▼
  BPE Tokeniser  ──►  token IDs  (max 256 tokens, truncated if longer)
       │
       ▼
  6-layer Transformer (MiniLM architecture)
  • 384 hidden dimensions
  • 12 attention heads
  • ~22 M parameters
       │
       ▼
  Mean pooling over token embeddings
       │
       ▼
  L2 normalisation  ──►  unit vector in ℝ³⁸⁴
       │
       ▼
  Output: float32[384]  stored in ChromaDB
```

Cosine similarity between two such vectors equals their dot product (because they're unit vectors). ChromaDB's HNSW index exploits this to answer approximate nearest-neighbour queries in O(log N) time rather than brute-force O(N).

---

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Batch size 32 | Saturates CPU L2/L3 cache for matrix ops without exceeding 8 GB RAM even for large corpora |
| `hnsw:space=cosine` | Semantic similarity is direction-based (angle between vectors), not magnitude-based; cosine handles this correctly. Euclidean distance would penalise short chunks |
| Cast metadata to scalar types | ChromaDB rejects Python lists/dicts inside metadata; lists (e.g. `teams`) are cast to `str` to preserve them without losing data |
| Re-run safety via ID check | Running `embedder.py` again after adding new scraped docs only embeds the new chunks; existing vectors are untouched |
| `device="cpu"` | MPS backend has known bugs with sentence-transformers on macOS; CPU is slower but produces correct, reproducible embeddings |
