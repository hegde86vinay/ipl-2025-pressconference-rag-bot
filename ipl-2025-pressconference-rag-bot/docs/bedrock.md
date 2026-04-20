# AWS Bedrock Alternative Architecture

## Overview

This document describes how the IPL 2025 Press Conference RAG Bot could be rebuilt on **AWS Bedrock** — Amazon's fully managed foundation model service. Two approaches are presented, ranging from fully managed (minimal code) to DIY (preserves the existing pipeline structure).

The local baseline uses:
- `sentence-transformers` (`all-MiniLM-L6-v2`, 384-dim) for embeddings
- ChromaDB (local persistent) as the vector store
- `anthropic` SDK → `claude-haiku-4-5-20251001` for generation

Both Bedrock approaches replace these three components with AWS equivalents while keeping `scraper.py` and `chunker.py` largely intact.

---

## Approach A — Fully Managed (Bedrock Knowledge Bases)

AWS Bedrock Knowledge Bases replace `chunker.py`, `embedder.py`, and ChromaDB entirely. The entire indexing pipeline collapses into a single **Sync Job** triggered from the AWS console or API. At query time, a single `retrieve_and_generate()` call handles retrieval, prompt construction, and generation.

### How It Works

| Stage | Who Does It | Detail |
|-------|------------|--------|
| Scraping | `scraper.py` (one line changed) | Output goes to S3 instead of local disk |
| Chunking | Bedrock KB (automatic) | Fixed-size, configurable token count |
| Embedding | Amazon Titan Embeddings V2 | 1 536-dim, 8 192-token context |
| Vector Store | OpenSearch Serverless | Managed kNN index, HA, zero ops |
| Retrieval + Generation | `bedrock-agent-runtime` | Single `retrieve_and_generate()` call |
| Auth | IAM Roles | No API keys; Lambda assumes execution role |

### Component Diagram

```mermaid
flowchart TD
    %% ── Data Sources ──────────────────────────────────────────────
    subgraph SOURCES["🌐 Data Sources"]
        SRC_A["ESPNcricinfo\nMatch Reports"]
        SRC_B["ESPNcricinfo\nNews & Interviews"]
        SRC_C["Cricbuzz\nMatch Reviews"]
    end

    %% ── Ingestion Pipeline ────────────────────────────────────────
    subgraph INGEST["⚙️ Ingestion Pipeline  (run once)"]
        direction TB

        subgraph SCRAPER["scraper.py  ← 1-line change"]
            SC1["HTTP GET + BeautifulSoup\nPolite 2 s delays"]
            SC2{"≥ 150 words?"}
            SC3["s3.put_object()\ns3://ipl-rag-docs/raw/"]
            SC1 --> SC2
            SC2 -- "Yes" --> SC3
            SC2 -- "No" --> SC_SKIP["Log skip"]
        end

        subgraph S3["🪣 Amazon S3"]
            S3B[("s3://ipl-rag-docs/\nraw/*.txt\nraw/*.json")]
        end

        subgraph KB["Amazon Bedrock Knowledge Base"]
            KB_SYNC["StartIngestionJob\n(console / EventBridge cron)"]
            KB_CHUNK["Auto-Chunking\nFixed-size · 500 tokens\n(configurable in console)"]
            KB_EMBED["Amazon Titan\nEmbeddings V2\n1 536-dim · 8 192-token ctx"]
            KB_IDX[("OpenSearch Serverless\nVector Index\nkNN / cosine · managed HA")]
            KB_SYNC --> KB_CHUNK --> KB_EMBED --> KB_IDX
        end

        SC3 --> S3B
        S3B -->|"S3 data source\nconfigured in KB"| KB_SYNC
    end

    %% ── Query Pipeline ────────────────────────────────────────────
    subgraph QUERY["🔍 Query Pipeline  (per question)"]
        direction TB

        subgraph GATEWAY["API Layer"]
            AG["Amazon API Gateway\nPOST /ask"]
            LAM["AWS Lambda\nbedrock_handler.py"]
            AG --> LAM
        end

        subgraph MANAGED_RAG["bedrock-agent-runtime"]
            RAG_CALL["retrieve_and_generate(\n  input.text = question,\n  knowledgeBaseId = KB_ID,\n  modelArn = claude-3-5-haiku\n)"]
            RETR["Embed question via Titan V2\nkNN search OpenSearch (top-3)"]
            AUGMENT["Prompt construction\n(handled by KB service)"]
            GEN["Claude 3.5 Haiku\nvia Bedrock runtime\nmax_tokens = 1 024"]
            CITE["Citations extracted\nfrom KB response object"]
            RAG_CALL --> RETR --> AUGMENT --> GEN --> CITE
        end

        LAM --> RAG_CALL
        RETR <-->|"cosine kNN"| KB_IDX
        CITE --> LAM
    end

    %% ── Security ──────────────────────────────────────────────────
    subgraph SEC["🔐 IAM — No API Keys"]
        IAM_LAM["Lambda Execution Role\nbedrock:RetrieveAndGenerate\nbedrock:InvokeModel"]
        IAM_KB["KB Ingestion Role\ns3:GetObject\nbedrock:InvokeModel (Titan)"]
    end

    %% ── User Interfaces ───────────────────────────────────────────
    subgraph UI["💬 User Interfaces"]
        UI_WEB["React / Streamlit\nAnswer + citations"]
        UI_CLI["curl / REST client"]
    end

    %% ── Connections ───────────────────────────────────────────────
    SOURCES --> SCRAPER
    LAM --> UI_WEB & UI_CLI
    SEC -.->|"assumed by"| LAM
    SEC -.->|"assumed by"| KB_SYNC

    %% ── Styles ────────────────────────────────────────────────────
    classDef source   fill:#dbeafe,stroke:#3b82f6,color:#1e3a5f
    classDef storage  fill:#dcfce7,stroke:#16a34a,color:#14532d
    classDef model    fill:#fef9c3,stroke:#ca8a04,color:#713f12
    classDef ui       fill:#f3e8ff,stroke:#9333ea,color:#3b0764
    classDef aws      fill:#fff7ed,stroke:#ea580c,color:#7c2d12
    classDef security fill:#f1f5f9,stroke:#64748b,color:#1e293b
    classDef llm      fill:#fce7f3,stroke:#db2777,color:#831843
    classDef skip     fill:#fee2e2,stroke:#dc2626,color:#7f1d1d

    class SRC_A,SRC_B,SRC_C source
    class S3B,KB_IDX storage
    class KB_EMBED model
    class UI_WEB,UI_CLI ui
    class AG,LAM,KB_SYNC,KB_CHUNK,RAG_CALL,RETR,AUGMENT,CITE aws
    class IAM_LAM,IAM_KB security
    class GEN llm
    class SC_SKIP skip
```

### Sequence Diagram

```mermaid
sequenceDiagram
    actor Dev  as Developer (once — ingestion)
    actor User as End User (each query)

    participant Scraper as scraper.py
    participant S3      as Amazon S3
    participant KB      as Bedrock Knowledge Base
    participant Titan   as Titan Embeddings V2
    participant OS      as OpenSearch Serverless
    participant GW      as API Gateway + Lambda
    participant BRT     as bedrock-agent-runtime
    participant Claude  as Claude 3.5 Haiku (Bedrock)

    Note over Dev,OS: ── Ingestion (run once) ──────────────────────────

    Dev->>Scraper: python scraper.py
    loop For each article
        Scraper->>S3: s3.put_object(Bucket="ipl-rag-docs", Key="raw/<slug>.txt")
        Scraper->>S3: s3.put_object(Key="raw/<slug>.json")
    end
    Scraper-->>Dev: Done. N docs uploaded to S3.

    Dev->>KB: StartIngestionJob (console or boto3)
    KB->>S3: GetObject(raw/*.txt)
    S3-->>KB: article text

    loop For each document
        KB->>KB: Split into chunks (500 tokens, configurable)
        KB->>Titan: InvokeModel(amazon.titan-embed-text-v2:0, chunk_text)
        Titan-->>KB: float32[1 536]
        KB->>OS: Index vector + metadata + source reference
        OS-->>KB: Indexed OK
    end
    KB-->>Dev: Ingestion complete — N chunks indexed

    Note over User,Claude: ── Query (per question) ──────────────────────

    User->>GW: POST /ask  { "question": "What did Kohli say?" }
    GW->>BRT: retrieve_and_generate(<br/>  input.text = question,<br/>  knowledgeBaseId = "KB_ID",<br/>  modelArn = "anthropic.claude-3-5-haiku-...",<br/>  numberOfResults = 3<br/>)

    BRT->>Titan: Embed question → float32[1 536]
    Titan-->>BRT: query vector

    BRT->>OS: kNN search (top-3 by cosine similarity)
    OS-->>BRT: top-3 chunks + source metadata

    BRT->>BRT: Build grounded prompt with context blocks

    BRT->>Claude: InvokeModel(prompt, system, max_tokens=1024)
    Note over Claude: Reads context, cites sources,<br/>refuses to speculate beyond context
    Claude-->>BRT: answer text

    BRT-->>GW: { output.text, citations[{retrievedReferences}] }
    GW-->>User: { answer, sources }
```

---

## Approach B — DIY on Bedrock (Custom Pipeline)

This approach keeps the full pipeline structure of the local implementation. Only the AI components are swapped — `sentence-transformers` becomes **Bedrock Titan Embeddings**, ChromaDB becomes **OpenSearch Serverless**, and the `anthropic` SDK becomes **`boto3` + `bedrock-runtime`**. The pipeline scripts remain individually runnable in the same order.

### How It Works

| Stage | Current | Bedrock Equivalent | Change |
|-------|---------|-------------------|--------|
| Scraping | `scraper.py` → `data/raw/` | `scraper.py` → S3 | 1 line (`open()` → `s3.put_object()`) |
| Chunking | `chunker.py` + tiktoken | `chunker.py` (unchanged) | None |
| Embedding | `embedder.py` + MiniLM | `bedrock_embedder.py` + Titan V2 | Full rewrite |
| Vector store | ChromaDB local | OpenSearch Serverless | Full rewrite |
| Retrieval + LLM | `rag.py` + `anthropic` SDK | `bedrock_rag.py` + `boto3` | Full rewrite |
| Auth | `ANTHROPIC_API_KEY` in `.env` | IAM Role / AWS credentials | Config change |
| UI | `app.py` Streamlit | `app.py` Streamlit (unchanged) | None |

### Component Diagram

```mermaid
flowchart TD
    %% ── Data Sources ──────────────────────────────────────────────
    subgraph SOURCES["🌐 Data Sources"]
        SRC_A["ESPNcricinfo\nMatch Reports"]
        SRC_B["ESPNcricinfo\nNews & Interviews"]
        SRC_C["Cricbuzz\nMatch Reviews"]
    end

    %% ── Ingestion Pipeline ────────────────────────────────────────
    subgraph INGEST["⚙️ Ingestion Pipeline  (run once)"]
        direction TB

        subgraph SCRAPER["scraper.py  ← 1-line change"]
            SC1["HTTP GET + BeautifulSoup\nPolite 2 s delays"]
            SC2{"≥ 150 words?"}
            SC3["s3.put_object()\ns3://ipl-rag-docs/raw/"]
            SC1 --> SC2
            SC2 -- "Yes" --> SC3
            SC2 -- "No" --> SC_SKIP["Log skip"]
        end

        subgraph S3["🪣 Amazon S3"]
            S3B[("s3://ipl-rag-docs/\nraw/*.txt\nraw/*.json")]
        end

        subgraph CHUNKER["chunker.py  ← UNCHANGED"]
            CK1["Load *.txt + *.json\nfrom S3 (or local cache)"]
            CK2["tiktoken cl100k_base\n500 tokens / 50 overlap"]
            CK3["SHA-256 chunk IDs\nstable across re-runs"]
            CK4["Write chunks.json\n(S3 or local)"]
            CK1 --> CK2 --> CK3 --> CK4
        end

        subgraph EMBEDDER["bedrock_embedder.py  ← REWRITTEN"]
            BE1["Load chunks.json"]
            BE2{"Chunk ID already\nin OpenSearch?"}
            BE3["bedrock-runtime\ninvoke_model(\n  amazon.titan-embed-text-v2:0\n  dimensions=1536\n)"]
            BE4["float32[1 536]\nunit vector"]
            BE5["os_client.index(\n  id, vector, metadata\n)"]
            BE6["Skip — already\nindexed"]
            BE1 --> BE2
            BE2 -- "No" --> BE3 --> BE4 --> BE5
            BE2 -- "Yes" --> BE6
        end

        subgraph OS["OpenSearch Serverless"]
            OS_IDX[("Vector Index\nipl_2025_presscon\nkNN · cosine · managed")]
        end

        SC3 --> S3B --> CK1
        BE5 --> OS_IDX
    end

    %% ── Query Pipeline ────────────────────────────────────────────
    subgraph QUERY["🔍 Query Pipeline  (per question)"]
        direction TB

        subgraph RAG["bedrock_rag.py  ← REWRITTEN"]
            R1["bedrock-runtime\ninvoke_model(Titan V2)\nEmbed question → 1 536-dim"]
            R2["os_client.search(\n  knn · top_k=3 · cosine\n)"]
            R3["Build prompt\n[1][2][3] context blocks\n(same format as rag.py)"]
            R4["bedrock-runtime\ninvoke_model(\n  anthropic.claude-3-5-haiku\n  max_tokens=1 024\n)"]
            R5["Extract answer\nBuild sources list\n{title, date, teams, url}"]
            R1 --> R2 --> R3 --> R4 --> R5
        end

        R2 <-->|"kNN cosine"| OS_IDX
    end

    %% ── User Interfaces ───────────────────────────────────────────
    subgraph UI["💬 User Interfaces  ← UNCHANGED"]
        UI_ST["app.py — Streamlit\nst.chat_input + st.chat_message\nexpander: sources"]
        UI_CLI["python bedrock_rag.py\n'your question' (CLI)"]
    end

    %% ── Config & Auth ─────────────────────────────────────────────
    subgraph CONFIG["🔧 Config & Auth"]
        CFG["config.py\n(update model IDs\n+ S3 bucket name)"]
        AUTH["AWS credentials\n~/.aws/credentials\nor IAM Role (Lambda)"]
    end

    %% ── Connections ───────────────────────────────────────────────
    SOURCES --> SCRAPER
    R5 --> UI_ST & UI_CLI
    CONFIG -.->|"imported by all modules"| SCRAPER
    CONFIG -.->|"imported by all modules"| CHUNKER
    CONFIG -.->|"imported by all modules"| EMBEDDER
    CONFIG -.->|"imported by all modules"| RAG
    AUTH -.->|"boto3 session"| BE3
    AUTH -.->|"boto3 session"| R1
    AUTH -.->|"boto3 session"| R4

    %% ── Styles ────────────────────────────────────────────────────
    classDef source    fill:#dbeafe,stroke:#3b82f6,color:#1e3a5f
    classDef storage   fill:#dcfce7,stroke:#16a34a,color:#14532d
    classDef model     fill:#fef9c3,stroke:#ca8a04,color:#713f12
    classDef ui        fill:#f3e8ff,stroke:#9333ea,color:#3b0764
    classDef unchanged fill:#f0fdf4,stroke:#16a34a,color:#14532d
    classDef changed   fill:#fff7ed,stroke:#ea580c,color:#7c2d12
    classDef llm       fill:#fce7f3,stroke:#db2777,color:#831843
    classDef config    fill:#f1f5f9,stroke:#64748b,color:#1e293b
    classDef skip      fill:#fee2e2,stroke:#dc2626,color:#7f1d1d

    class SRC_A,SRC_B,SRC_C source
    class S3B,OS_IDX storage
    class BE3,R1 model
    class UI_ST,UI_CLI ui
    class CK1,CK2,CK3,CK4 unchanged
    class BE1,BE2,BE3,BE4,BE5,R1,R2,R3,R4,R5,SC3 changed
    class R4 llm
    class CFG,AUTH config
    class SC_SKIP,BE6 skip
```

### Sequence Diagram

```mermaid
sequenceDiagram
    actor Dev  as Developer (once — ingestion)
    actor User as End User (each query)

    participant Scraper  as scraper.py (modified)
    participant S3       as Amazon S3
    participant Chunker  as chunker.py (unchanged)
    participant BEmbed   as bedrock_embedder.py
    participant Titan    as Titan Embeddings V2<br/>(bedrock-runtime)
    participant OS       as OpenSearch Serverless
    participant BRAG     as bedrock_rag.py
    participant BRT      as bedrock-runtime
    participant Claude   as Claude 3.5 Haiku (Bedrock)

    Note over Dev,OS: ── Step 1: Scrape ────────────────────────────────

    Dev->>Scraper: python scraper.py
    loop For each article (≥ 150 words)
        Scraper->>S3: s3.put_object(Key="raw/<slug>.txt", Body=text)
        Scraper->>S3: s3.put_object(Key="raw/<slug>.json", Body=meta)
    end
    Scraper-->>Dev: Done. N docs → s3://ipl-rag-docs/raw/

    Note over Dev,OS: ── Step 2: Chunk ────────────────────────────────

    Dev->>Chunker: python chunker.py
    Chunker->>S3: GetObject(raw/*.txt + raw/*.json)
    S3-->>Chunker: article files

    loop For each document
        Chunker->>Chunker: tiktoken cl100k_base encode
        Note over Chunker: sliding window 500 tok / 50 overlap
        Chunker->>Chunker: SHA-256 chunk IDs
    end

    Chunker->>S3: PutObject(chunks/chunks.json)
    Chunker-->>Dev: Chunked N docs into M chunks

    Note over Dev,OS: ── Step 3: Embed ────────────────────────────────

    Dev->>BEmbed: python bedrock_embedder.py
    BEmbed->>S3: GetObject(chunks/chunks.json)
    S3-->>BEmbed: list of M chunk objects

    BEmbed->>OS: Search existing IDs (dedup check)
    OS-->>BEmbed: set of already-indexed chunk IDs

    loop For each pending chunk
        BEmbed->>Titan: invoke_model(<br/>  modelId="amazon.titan-embed-text-v2:0",<br/>  inputText=chunk_text, dimensions=1536<br/>)
        Titan-->>BEmbed: float32[1 536] embedding

        BEmbed->>OS: index(id, vector, metadata)
        OS-->>BEmbed: 201 Created
    end
    BEmbed-->>Dev: Done. M vectors in OpenSearch.

    Note over User,Claude: ── Step 4: Query (per question) ─────────────

    User->>BRAG: ask("What did Kohli say after the final?")

    BRAG->>Titan: invoke_model(Titan V2, question_text)
    Titan-->>BRAG: float32[1 536] query vector

    BRAG->>OS: search(knn, query_vector, k=3, cosine)
    Note over OS: Approximate nearest-neighbour<br/>over M indexed vectors
    OS-->>BRAG: top-3 { _source.text, _source.metadata, _score }

    BRAG->>BRAG: build Chunk(text, meta, score) × 3

    BRAG->>BRAG: build_prompt(question, chunks)<br/>→ [1][2][3] context blocks + question

    BRAG->>BRT: invoke_model(<br/>  modelId="anthropic.claude-3-5-haiku-...",<br/>  system=SYSTEM_PROMPT,<br/>  messages=[{role:user, content:prompt}],<br/>  max_tokens=1024<br/>)
    Note over Claude: Same grounding instructions<br/>as local claude-haiku — cite sources,<br/>admit if context is thin
    Claude-->>BRAG: answer text

    BRAG->>BRAG: build sources list<br/>{title, date, teams, url} × 3
    BRAG-->>User: { answer, sources, chunks }
```

---

## Component Comparison

| Component | Local (Baseline) | Approach A — Managed | Approach B — DIY |
|-----------|-----------------|---------------------|-----------------|
| **Scraper** | `data/raw/*.txt` | S3 (`s3.put_object`) | S3 (`s3.put_object`) |
| **Chunking** | `chunker.py` + tiktoken | Bedrock KB (automatic) | `chunker.py` (unchanged) |
| **Embedding model** | `all-MiniLM-L6-v2` · 384-dim | Titan Embeddings V2 · 1 536-dim | Titan Embeddings V2 · 1 536-dim |
| **Embedding infra** | `embedder.py` (local process) | Bedrock KB sync job | `bedrock_embedder.py` + boto3 |
| **Vector store** | ChromaDB (local SQLite + HNSW) | OpenSearch Serverless (managed) | OpenSearch Serverless (managed) |
| **Retrieval** | `collection.query()` ChromaDB | Auto inside `retrieve_and_generate()` | `os_client.search(knn)` |
| **LLM SDK** | `anthropic` Python SDK | `bedrock-agent-runtime` boto3 | `bedrock-runtime` boto3 |
| **LLM model ID** | `claude-haiku-4-5-20251001` | `anthropic.claude-3-5-haiku-...-v1:0` | `anthropic.claude-3-5-haiku-...-v1:0` |
| **Auth** | `ANTHROPIC_API_KEY` in `.env` | IAM Role (no secrets) | IAM Role / `~/.aws/credentials` |
| **UI** | Streamlit `app.py` | React + Amplify (or keep Streamlit) | Streamlit `app.py` (unchanged) |
| **Files changed** | — | `scraper.py` (1 line) | `scraper.py`, `bedrock_embedder.py`, `bedrock_rag.py` |
| **Files removed** | — | `chunker.py`, `embedder.py` | `embedder.py`, `rag.py` (replaced) |

---

## Code Change Summary

### `scraper.py` — both approaches (1-line change)

```python
# BEFORE: write to local disk
with open(f"data/raw/{slug}.txt", "w") as f:
    f.write(content)

# AFTER: upload to S3
import boto3
s3 = boto3.client("s3", region_name="us-east-1")
s3.put_object(Bucket="ipl-rag-docs", Key=f"raw/{slug}.txt",
              Body=content.encode())
s3.put_object(Bucket="ipl-rag-docs", Key=f"raw/{slug}.json",
              Body=json.dumps(metadata).encode())
```

### `bedrock_embedder.py` — Approach B only (Approach A eliminates this file)

```python
import boto3, json

bedrock = boto3.client("bedrock-runtime", region_name="us-east-1")

def embed(text: str) -> list[float]:
    response = bedrock.invoke_model(
        modelId="amazon.titan-embed-text-v2:0",
        body=json.dumps({"inputText": text, "dimensions": 1536}),
    )
    return json.loads(response["body"].read())["embedding"]
```

### `bedrock_rag.py` — Approach B LLM call

```python
import boto3, json

bedrock = boto3.client("bedrock-runtime", region_name="us-east-1")

def generate(prompt: str, system: str) -> str:
    response = bedrock.invoke_model(
        modelId="anthropic.claude-3-5-haiku-20241022-v1:0",
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 1024,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
        }),
    )
    return json.loads(response["body"].read())["content"][0]["text"]
```

### `bedrock_handler.py` — Approach A single call

```python
import boto3

agent_rt = boto3.client("bedrock-agent-runtime", region_name="us-east-1")

def ask(question: str) -> dict:
    response = agent_rt.retrieve_and_generate(
        input={"text": question},
        retrieveAndGenerateConfiguration={
            "type": "KNOWLEDGE_BASE",
            "knowledgeBaseConfiguration": {
                "knowledgeBaseId": "YOUR_KB_ID",
                "modelArn": (
                    "arn:aws:bedrock:us-east-1::foundation-model/"
                    "anthropic.claude-3-5-haiku-20241022-v1:0"
                ),
                "retrievalConfiguration": {
                    "vectorSearchConfiguration": {"numberOfResults": 3}
                },
            },
        },
    )
    return {
        "answer": response["output"]["text"],
        "sources": response.get("citations", []),
    }
```

### `requirements.txt` — dependencies change

```diff
- anthropic==0.40.0
- chromadb==0.5.23
- sentence-transformers==3.3.1
+ boto3>=1.34.0
+ opensearch-py>=2.4.0        # Approach B only
  tiktoken==0.8.0              # Approach B only (A removes chunker.py)
  streamlit==1.40.2            # Keep if retaining Streamlit UI
  beautifulsoup4==4.12.3       # scraper.py — unchanged
  requests==2.32.3             # scraper.py — unchanged
  python-dotenv==1.0.1         # Now loads AWS_REGION, S3_BUCKET, etc.
```

---

## Key Design Decisions & Trade-offs

| Area | Improvement on Bedrock | Trade-off |
|------|----------------------|-----------|
| **Embedding quality** | 384-dim → 1 536-dim; Titan V2 is multilingual and trained on a broader corpus | API latency per chunk vs local CPU; cost per 1 K tokens |
| **Vector store** | OpenSearch Serverless is fully managed, HA, auto-scaled — zero ops | No local fallback; needs real AWS account even in dev |
| **Security** | IAM roles, no secrets in `.env`; auditable via CloudTrail | Needs IAM setup; local dev requires `~/.aws/credentials` or a dev role |
| **Scalability** | Serverless: handles concurrent users, no OOM risk | Lambda cold starts add ~200–800 ms on first query |
| **Observability** | CloudWatch logs, Bedrock model invocation logs, X-Ray tracing | More setup than `print()` statements |
| **Pipeline control** | Approach A: zero chunking code to maintain | Approach A: chunking parameters are console-only; no programmatic custom logic |
| **Cost model** | Bedrock on-demand pricing (pay per call) | At low query volume, direct Anthropic API + local ChromaDB is cheaper; Bedrock becomes cost-effective at scale |
| **Portability** | Deep AWS coupling | Switching providers later requires a rewrite of embedding + retrieval + generation layers |

### Recommended Contribution Path

If contributing a Bedrock backend to this repo:

1. Start with **Approach B** — easier to reason about, all stages are visible and debuggable
2. Add `bedrock_embedder.py` and `bedrock_rag.py` **alongside** the existing files — don't delete anything
3. Add a `RAG_BACKEND=local|bedrock` env-var switch in `config.py` so users without AWS credentials can still run the original pipeline
4. Validate that the same questions produce equivalent answers before retiring the local path
5. Layer Approach A on top once Approach B is validated — Approach A is strictly less code but harder to debug when citations are wrong
