# RAG Query Engine

## Overview

`rag.py` is the **intelligence layer** — the component that transforms a natural-language question into a grounded, cited answer. It combines three sub-steps:

1. **Retrieve** — embed the question and find the most semantically similar chunks in ChromaDB
2. **Augment** — inject the retrieved chunks as numbered context into a structured prompt
3. **Generate** — send the prompt to Claude Haiku and return the answer with source metadata

The module exposes both a Python API (`ask(question) → dict`) for the Streamlit UI and a CLI entrypoint (`python rag.py "your question"`).

---

## Tech Stack

| Library | Version | Role | Why this choice |
|---------|---------|------|-----------------|
| `anthropic` | 0.40 | Claude API SDK | Official Python SDK; handles auth, retries, and response parsing |
| `claude-haiku-4-5-20251001` | — | LLM for generation | Fastest Claude model; ideal for Q&A where latency matters and answers are short. At $1/1M input tokens it's also the most cost-effective option for a hobby project |
| `sentence-transformers` | 3.3 | Query embedding | Same model used at index time (`all-MiniLM-L6-v2`) — query and document vectors live in the same embedding space |
| `chromadb` | 0.5.23 | Vector retrieval | Cosine similarity search over the pre-built HNSW index |
| `python-dotenv` | 1.0 | API key loading | Reads `ANTHROPIC_API_KEY` from `.env` without exposing it in code |

**Why Claude Haiku over GPT-3.5 / local LLMs?**

| | Claude Haiku (direct) | Claude Haiku (Bedrock) | GPT-3.5-turbo | Llama-3-8B (local) |
|--|----------------------|----------------------|--------------|-------------------|
| Latency | ~1 s | ~1–2 s | ~1 s | 20–60 s on M2 Air |
| Quality (Q&A) | High | High (same model) | High | Medium |
| Cost | $1/1M in | Bedrock on-demand | $0.50/1M in | Free |
| Instruction following | Excellent | Excellent | Good | Variable |
| RAM needed | API only | API only | API only | 8 GB+ |
| Auth | `ANTHROPIC_API_KEY` | IAM Role | `OPENAI_API_KEY` | Local weights |

Local LLMs are ruled out by the 8 GB RAM constraint on M2 Air — loading an 8B model leaves no headroom for the rest of the pipeline. Between the API options, Haiku's instruction-following quality and explicit citation behaviour are noticeably stronger for this use case.

> **AWS Bedrock note:** Claude Haiku is also available via AWS Bedrock (`anthropic.claude-3-5-haiku-20241022-v1:0`). The model quality is identical — the difference is auth (IAM instead of an API key) and SDK (`boto3` + `bedrock-runtime` instead of the `anthropic` package). See [`docs/bedrock.md`](bedrock.md) for the full approach.

**Why Top-K = 3?**
Three chunks fit comfortably within Haiku's context window while keeping prompt cost low. Empirically, the third chunk rarely adds new information for a narrow factual question; raising to 5 increases cost by ~40% with marginal quality gain.

---

## Component Diagram

```mermaid
flowchart TD
    START_CLI(["▶ python rag.py 'question'"])
    START_API(["▶ rag.ask('question')\ncalled by app.py"])

    subgraph INIT["Lazy Initialisation — load_retriever()"]
        IR1{"_retriever\nalready loaded?"}
        IR2["chromadb.PersistentClient\n→ get_collection('ipl_2025_presscon')"]
        IR3["SentenceTransformer\n'all-MiniLM-L6-v2'\ndevice=cpu"]
        IR4["Cache in module-level\n_retriever dict"]
        IR1 -- "No (first call)" --> IR2 --> IR3 --> IR4
        IR1 -- "Yes" --> RETRIEVE
    end

    subgraph RETRIEVE["retrieve(question, top_k=3)"]
        R1["model.encode([question])\n→ float32[1 × 384]"]
        R2["collection.query(\n  query_embeddings=embedding,\n  n_results=3,\n  include=['documents','metadatas','distances']\n)"]
        R3["Zip documents + metadatas\n+ distances into Chunk objects"]
        R1 --> R2 --> R3
    end

    subgraph PROMPT["build_prompt(question, chunks)"]
        P1["For each chunk (1–3):\n[N] Source: title (date)\nURL: source_url\n\nchunk text"]
        P2["Join blocks with ---\ndelimiter"]
        P3["Append:\nQuestion: {question}"]
        P1 --> P2 --> P3
    end

    subgraph GENERATE["Claude API — ask()"]
        G1["anthropic.Anthropic(api_key=…)"]
        G2["messages.create(\n  model='claude-haiku-4-5-20251001',\n  max_tokens=1024,\n  system=SYSTEM_PROMPT,\n  messages=[{role:'user', content:prompt}]\n)"]
        G3["Extract first TextBlock\nfrom response.content"]
        G4["Build sources list:\n[{title, date, teams, url}, …]"]
        G1 --> G2 --> G3 --> G4
    end

    subgraph RETURN["Return / Display"]
        RET1["Return dict:\n{answer, sources, chunks}"]
        RET2["CLI: print answer\n+ source list"]
        RET3["app.py: st.chat_message\n+ expander"]
    end

    START_CLI & START_API --> INIT
    IR4 --> RETRIEVE
    RETRIEVE -->|"top-3 Chunk objects"| PROMPT
    PROMPT -->|"augmented prompt string"| GENERATE
    GENERATE --> RETURN
    RET1 --> RET2 & RET3

    classDef io       fill:#f3e8ff,stroke:#9333ea,color:#3b0764
    classDef model    fill:#fef9c3,stroke:#ca8a04,color:#713f12
    classDef store    fill:#dcfce7,stroke:#16a34a,color:#14532d
    classDef decision fill:#dbeafe,stroke:#3b82f6,color:#1e3a5f
    classDef llm      fill:#fce7f3,stroke:#db2777,color:#831843

    class START_CLI,START_API,RET2,RET3 io
    class R1,IR3 model
    class IR2,R2 store
    class IR1 decision
    class G2,G3 llm
```

---

## Sequence Diagram

```mermaid
sequenceDiagram
    actor User
    participant App      as app.py / CLI
    participant RAG      as rag.py
    participant ST       as SentenceTransformer<br/>(CPU, singleton)
    participant Chroma   as ChromaDB<br/>ipl_2025_presscon
    participant Claude   as Anthropic API<br/>claude-haiku-4-5-20251001

    User->>App: "What did Kohli say after the final?"

    App->>RAG: ask(question)

    Note over RAG: load_retriever() — singleton, loaded once per process

    alt First call in process
        RAG->>Chroma: PersistentClient + get_collection(…)
        Chroma-->>RAG: collection handle (~400 vectors)
        RAG->>ST: SentenceTransformer("all-MiniLM-L6-v2", device="cpu")
        ST-->>RAG: model loaded
    end

    Note over RAG: retrieve(question, top_k=3)

    RAG->>ST: model.encode(["What did Kohli say after the final?"])
    ST-->>RAG: float32[1 × 384] query vector

    RAG->>Chroma: collection.query(query_embeddings, n_results=3)
    Note over Chroma: HNSW approximate nearest-neighbour<br/>cosine similarity over ~400 vectors
    Chroma-->>RAG: top-3 {documents, metadatas, distances}

    RAG->>RAG: build Chunk(text, meta, distance) × 3

    Note over RAG: build_prompt(question, chunks)

    RAG->>RAG: format context blocks [1][2][3]<br/>with title · date · URL · chunk text
    RAG->>RAG: append "Question: {question}"

    Note over RAG: call Claude API

    RAG->>Claude: messages.create(<br/>  model="claude-haiku-4-5-20251001",<br/>  system=SYSTEM_PROMPT,<br/>  messages=[{role:"user", content:prompt}],<br/>  max_tokens=1024<br/>)

    Note over Claude: Reads context blocks,<br/>grounds answer in citations,<br/>refuses to speculate beyond context

    Claude-->>RAG: Message(content=[TextBlock(text="…")])

    RAG->>RAG: extract answer text
    RAG->>RAG: build sources = [{title, date, teams, url} × 3]

    RAG-->>App: {answer, sources, chunks}

    App-->>User: Display answer + "Sources used (3)" expander
```

---

## System Prompt

```
You are an expert IPL cricket analyst with access to IPL 2025 press conference
transcripts, match reports, and player interviews. Answer questions using only
the provided context. If the context does not contain enough information, say so
clearly. Always cite which match or interview your answer comes from.
```

**Why this phrasing?**

| Instruction | Purpose |
|-------------|---------|
| "using only the provided context" | Prevents Claude from hallucinating facts from its training data about IPL 2025 |
| "If the context does not contain enough information, say so clearly" | Produces an honest "I don't know" rather than a confident wrong answer |
| "Always cite which match or interview" | Forces grounded responses; matches the source expander in the UI |

---

## Prompt Structure (Example)

```
Context:

[1] Source: RCB beat PBKS by 6 runs — Match Report (2025-06-03)
URL: https://www.espncricinfo.com/series/.../match-report

Virat Kohli was visibly emotional at the post-match presentation.
"This is for every RCB fan who waited 17 years," he said …

---

[2] Source: Kohli speaks after historic win (2025-06-04)
URL: https://www.espncricinfo.com/story/…

In a press conference the following morning, Kohli elaborated …

---

[3] Source: Faf du Plessis on RCB's journey (2025-06-03)
URL: https://www.cricbuzz.com/cricket-news/…

Captain Faf du Plessis credited the team's batting depth …

Question: What did Virat Kohli say after RCB won the IPL 2025 final?
```

---

## Return Object Schema

```python
{
    "answer": "Virat Kohli said 'This is for every RCB fan who waited 17 years' …",
    "sources": [
        {
            "title": "RCB beat PBKS by 6 runs — Match Report",
            "date":  "2025-06-03",
            "teams": "[]",
            "url":   "https://www.espncricinfo.com/series/…/match-report"
        },
        { … },
        { … }
    ],
    "chunks": [Chunk(text=…, meta={…}, distance=0.18), …]   # internal; not shown in UI
}
```

---

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Singleton `_retriever` dict | Loading the embedding model and opening the ChromaDB client both take ~2 s. Caching them at module level means the Streamlit app only pays this cost on the first question per session |
| Same embedding model for index and query | Query and document vectors must live in the same vector space. Using different models would produce meaningless similarity scores |
| `max_tokens=1024` | Q&A answers about cricket quotes are short. 1 024 tokens (~750 words) is plenty; a lower limit risks truncation mid-sentence |
| Return raw `chunks` in response dict | The Streamlit app only needs `sources` for display, but returning `chunks` (with `distance` scores) lets a developer inspect retrieval quality without re-running the pipeline |
| `top_k=3` default (configurable in config.py) | Three chunks = ~1 500 tokens of context, well within Haiku's 200 K window but minimal enough to keep prompt cost low |
