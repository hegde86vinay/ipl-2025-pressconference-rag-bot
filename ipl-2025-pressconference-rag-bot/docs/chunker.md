# Chunker

## Overview

`chunker.py` is the **text preparation layer**. It takes the raw article files produced by the scraper and splits them into overlapping token windows that are small enough for a vector embedding model to process accurately and large enough to carry meaningful context.

The output — `data/chunks/chunks.json` — is the single input consumed by the embedder. Every chunk carries the full metadata of its parent document, so the RAG engine can surface precise source citations without any secondary lookup.

---

## Tech Stack

| Library | Version | Role | Why this choice |
|---------|---------|------|-----------------|
| `tiktoken` | 0.8 | Tokeniser | OpenAI's BPE tokeniser; `cl100k_base` encoding is used by GPT-4, Claude, and `all-MiniLM-L6-v2`'s training data — token counts are accurate rather than approximated by word count |
| `json` | stdlib | I/O | Universal format; chunks.json is human-inspectable and can be consumed by any downstream tool |
| `hashlib` | stdlib | Chunk ID generation | SHA-256 of `source_url::chunk_index` produces collision-resistant IDs that are stable across re-runs — the embedder uses these to skip already-processed chunks |
| `glob` | stdlib | File discovery | Matches `data/raw/*.txt` without shell expansion — safe on all platforms |

**Why `cl100k_base` encoding?**
Tiktoken's `cl100k_base` is the byte-pair encoding (BPE) vocabulary used by `text-embedding-ada-002`, GPT-4, and most modern LLMs. Using it here means our chunk boundaries align with how the embedding model (`all-MiniLM-L6-v2`) was trained, reducing the chance of a meaningful phrase being split across a chunk boundary mid-subword.

**Why 500 tokens / 50-token overlap?**

| Parameter | Value | Reasoning |
|-----------|-------|-----------|
| `CHUNK_SIZE` | 500 tokens | Fits comfortably within MiniLM's 256-token limit after truncation, while carrying ~350 words of context — enough for a full quote + surrounding paragraph |
| `CHUNK_OVERLAP` | 50 tokens | ~10% overlap. Prevents a sentence that straddles a boundary from being semantically orphaned in both halves |

> **Note:** `all-MiniLM-L6-v2` hard-truncates input at 256 tokens. With 500-token chunks the model sees the first 256 tokens only. This is intentional — longer chunks are still useful because they give more context to the reader in the source expander, and the most salient content (names, quotes, match scores) typically appears early in a paragraph.

---

## Component Diagram

```mermaid
flowchart TD
    START(["▶ python chunker.py"])

    subgraph LOAD["Load Phase"]
        L1["glob data/raw/*.txt\nsorted alphabetically"]
        L2["For each .txt file:\nread full text"]
        L3["Check for matching .json sidecar"]
        L4{"Sidecar\nexists?"}
        L5["Load metadata dict\nfrom JSON"]
        L6["Use empty dict {}"]
        L7["Append {text, meta}\nto docs list"]
        L1 --> L2 --> L3 --> L4
        L4 -- "Yes" --> L5 --> L7
        L4 -- "No" --> L6 --> L7
    end

    subgraph CHUNK["Chunk Phase — per document"]
        C1["tiktoken.get_encoding\n'cl100k_base'"]
        C2["enc.encode(text)\n→ token ID list"]
        C3["Sliding window loop\nstart = 0"]
        C4["end = min(start + 500, len)"]
        C5["tokens[start:end]\n→ enc.decode()"]
        C6["Append chunk string"]
        C7{"end == len(tokens)\n(last chunk)?"}
        C8["start += 500 - 50\n(advance with overlap)"]
        C9["All chunks for doc\ncollected"]
        C1 --> C2 --> C3 --> C4 --> C5 --> C6 --> C7
        C7 -- "No" --> C8 --> C4
        C7 -- "Yes" --> C9
    end

    subgraph META["Metadata Enrichment — per chunk"]
        M1["chunk_index = position in doc (0-based)"]
        M2["total_chunks = len(all chunks for doc)"]
        M3["id = SHA-256(source_url::chunk_index)[:16]"]
        M4["Flatten meta dict into chunk\n(source_url · title · date · teams …)"]
        M5["Emit chunk object\n{id, text, chunk_index, total_chunks, …meta}"]
        M1 --> M2 --> M3 --> M4 --> M5
    end

    subgraph SAVE["Save Phase"]
        S1["Collect all chunk objects\ninto list"]
        S2["json.dump → data/chunks/chunks.json\n(indent=2 for readability)"]
        S3["Print summary:\nChunked N docs into M chunks"]
    end

    START --> LOAD
    LOAD -->|"docs list"| CHUNK
    CHUNK -->|"raw chunk strings"| META
    META -->|"enriched chunk objects"| SAVE

    classDef io       fill:#f3e8ff,stroke:#9333ea,color:#3b0764
    classDef process  fill:#f0fdf4,stroke:#16a34a,color:#14532d
    classDef decision fill:#fef9c3,stroke:#ca8a04,color:#713f12
    classDef data     fill:#dbeafe,stroke:#3b82f6,color:#1e3a5f

    class L1,S2,S3 io
    class CHUNK,META process
    class L4,C7 decision
    class M3,M4 data
```

---

## Sequence Diagram

```mermaid
sequenceDiagram
    actor User
    participant Chunker  as chunker.py
    participant FS_In    as data/raw/<br/>(Filesystem)
    participant Tiktoken as tiktoken<br/>cl100k_base
    participant Hasher   as hashlib<br/>SHA-256
    participant FS_Out   as data/chunks/<br/>chunks.json

    User->>Chunker: python chunker.py

    Chunker->>FS_In: glob("data/raw/*.txt")
    FS_In-->>Chunker: [article-1.txt, article-2.txt, …]

    loop For each .txt file
        Chunker->>FS_In: read article-N.txt → raw text
        FS_In-->>Chunker: text string

        Chunker->>FS_In: read article-N.json (sidecar)
        alt JSON sidecar found
            FS_In-->>Chunker: {source_url, title, date, …}
        else No sidecar
            FS_In-->>Chunker: FileNotFoundError (caught)
            Chunker->>Chunker: use empty meta = {}
        end

        Chunker->>Tiktoken: enc.encode(text)
        Tiktoken-->>Chunker: [token_id, token_id, …] (N tokens)

        Note over Chunker: Sliding window — 500 tok / 50 overlap

        loop start = 0 → N, step = 450
            Chunker->>Tiktoken: enc.decode(tokens[start : start+500])
            Tiktoken-->>Chunker: chunk_text (string)

            Chunker->>Hasher: sha256(f"{source_url}::{chunk_index}")
            Hasher-->>Chunker: hex_digest[:16] (chunk ID)

            Chunker->>Chunker: build chunk object<br/>{id, text, chunk_index, total_chunks, …meta}
        end
    end

    Chunker->>FS_Out: json.dump(all_chunks, indent=2)
    FS_Out-->>Chunker: write confirmed

    Chunker-->>User: Chunked N docs into M chunks → data/chunks/chunks.json
```

---

## Chunk Object Schema

```json
{
  "id":           "a3f8c1d2e4b56789",
  "text":         "Virat Kohli said after the final: 'This is for every RCB fan …'",
  "chunk_index":  2,
  "total_chunks": 5,
  "source_url":   "https://www.espncricinfo.com/series/.../match-report",
  "title":        "RCB beat PBKS by 6 runs — Match Report",
  "date":         "2025-06-03",
  "teams":        [],
  "match_number": "",
  "author":       "",
  "source":       "espncricinfo_match_report",
  "file_path":    "data/raw/rcb-beat-pbks-by-6-runs.txt"
}
```

---

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| SHA-256 chunk ID from `source_url::index` | Deterministic and stable — the same article always produces the same IDs across re-runs, enabling the embedder's skip logic |
| Flatten metadata into every chunk | Avoids a join at query time; the RAG engine gets full citation info from the vector store result alone |
| Overlap of 10% (50/500) | Empirically balanced — enough to catch cross-boundary sentences without doubling corpus size |
| Sort `.txt` files alphabetically | Deterministic processing order for reproducible `chunk_index` values |
| `cl100k_base` vs word-split | Word count varies wildly by language and punctuation; token count is a stable unit that directly maps to model context limits |
