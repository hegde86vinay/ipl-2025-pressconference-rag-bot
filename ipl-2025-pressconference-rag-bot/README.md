# IPL 2025 Press Conference RAG Bot

A local RAG (Retrieval-Augmented Generation) pipeline to answer natural-language questions about IPL 2025 player and captain interviews, match reports, and post-match reactions.

**Stack:** requests + BeautifulSoup → tiktoken → sentence-transformers + ChromaDB → Claude Haiku → Streamlit

---

## Architecture

```mermaid
flowchart TD
    %% ── Data Sources ──────────────────────────────────────────────
    subgraph SOURCES["🌐 Data Sources"]
        SRC_A["ESPNcricinfo\nMatch Reports\n(/match-results)"]
        SRC_B["ESPNcricinfo\nNews & Interviews\n(/news)"]
        SRC_C["Cricbuzz\nMatch Reviews\n(/news)"]
    end

    %% ── Offline Indexing Pipeline ─────────────────────────────────
    subgraph OFFLINE["⚙️ Offline Indexing Pipeline  (run once)"]
        direction TB

        subgraph SCRAPER["scraper.py"]
            SC1["HTTP GET with\npolite delays 2s"]
            SC2["BeautifulSoup\nHTML parse"]
            SC3{"≥ 150 words?"}
            SC4["Save .txt + .json\nsidecar to data/raw/"]
            SC5["Log skip to\nscrape_log.txt"]
            SC1 --> SC2 --> SC3
            SC3 -- Yes --> SC4
            SC3 -- No / 403 / 404 --> SC5
        end

        subgraph CHUNKER["chunker.py"]
            CK1["Load all .txt files\n+ JSON metadata"]
            CK2["tiktoken cl100k_base\ntokenise"]
            CK3["Sliding window\n500 tokens / 50 overlap"]
            CK4["Attach metadata +\nSHA-256 chunk ID"]
            CK5["Write data/chunks/\nchunks.json"]
            CK1 --> CK2 --> CK3 --> CK4 --> CK5
        end

        subgraph EMBEDDER["embedder.py"]
            EM1["Load chunks.json"]
            EM2{"Chunk ID already\nin ChromaDB?"}
            EM3["all-MiniLM-L6-v2\ndevice=cpu\nbatch size 32"]
            EM4["Upsert vectors +\ndocuments + metadata"]
            EM5["Skip — already\nembedded"]
            EM1 --> EM2
            EM2 -- No --> EM3 --> EM4
            EM2 -- Yes --> EM5
        end

        subgraph VECTORDB["vectorstore/chroma_db/"]
            VDB[("ChromaDB\nPersistentClient\ncollection: ipl_2025_presscon\n~400 vectors")]
        end

        SCRAPER --> CHUNKER --> EMBEDDER --> VECTORDB
    end

    %% ── Online Query Pipeline ─────────────────────────────────────
    subgraph ONLINE["🔍 Online Query Pipeline  (per question)"]
        direction TB

        subgraph RETRIEVER["rag.py — retrieve()"]
            R1["Embed question\nall-MiniLM-L6-v2 cpu"]
            R2["ChromaDB cosine\nsimilarity search\nTop-K = 3"]
            R3["Return Chunk objects\n(text + metadata + distance)"]
            R1 --> R2 --> R3
        end

        subgraph PROMPT["rag.py — build_prompt()"]
            P1["Numbered context blocks\n[1] title · date · URL · text\n[2] …  [3] …"]
            P2["Append user question"]
            P1 --> P2
        end

        subgraph LLM["rag.py — Claude API"]
            L1["System prompt:\nIPL analyst, cite sources,\nadmit if context is thin"]
            L2["claude-haiku-4-5-20251001\nmax_tokens=1024"]
            L3["Extract answer text\nfrom response.content"]
            L1 --> L2 --> L3
        end

        RETRIEVER --> PROMPT --> LLM
    end

    %% ── User Interfaces ───────────────────────────────────────────
    subgraph UI["💬 User Interfaces"]
        direction LR

        subgraph STREAMLIT["app.py — Streamlit"]
            UI1["st.chat_input\nUser question"]
            UI2["Spinner while\nrag.ask() runs"]
            UI3["st.chat_message\nAnswer displayed"]
            UI4["Expander:\nSources used (3)\ntitle · date · teams · URL"]
            UI5["Sidebar:\ndoc count · chunk count\nmodel · last embed time"]
            UI1 --> UI2 --> UI3 --> UI4
        end

        subgraph CLI["rag.py — CLI"]
            CLI1["python rag.py\n'your question'"]
            CLI2["Prints answer\n+ source list"]
            CLI1 --> CLI2
        end
    end

    %% ── Config & Env ──────────────────────────────────────────────
    subgraph CONFIG["🔧 Config & Secrets"]
        CFG["config.py\nAll paths · models\nURLs · thresholds"]
        ENV[".env\nANTHROPIC_API_KEY"]
    end

    %% ── Connections ───────────────────────────────────────────────
    SRC_A & SRC_B & SRC_C --> SCRAPER

    VECTORDB -->|"cosine search"| RETRIEVER

    LLM --> UI2
    LLM --> CLI2

    UI1 --> RETRIEVER
    CLI1 --> RETRIEVER

    CONFIG -.->|"imported by all modules"| SCRAPER
    CONFIG -.->|"imported by all modules"| CHUNKER
    CONFIG -.->|"imported by all modules"| EMBEDDER
    CONFIG -.->|"imported by all modules"| RETRIEVER
    ENV -.->|"python-dotenv"| LLM

    %% ── Styles ────────────────────────────────────────────────────
    classDef source    fill:#dbeafe,stroke:#3b82f6,color:#1e3a5f
    classDef storage   fill:#dcfce7,stroke:#16a34a,color:#14532d
    classDef model     fill:#fef9c3,stroke:#ca8a04,color:#713f12
    classDef ui        fill:#f3e8ff,stroke:#9333ea,color:#3b0764
    classDef config    fill:#f1f5f9,stroke:#64748b,color:#1e293b

    class SRC_A,SRC_B,SRC_C source
    class VDB,CK5 storage
    class EM3,R1,L2 model
    class UI1,UI2,UI3,UI4,UI5,CLI1,CLI2 ui
    class CFG,ENV config
```

---

## Setup

```bash
# 1. Clone / enter the folder
cd ipl-2025-pressconference-rag-bot

# 2. Create a virtual environment
python -m venv .venv && source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Add your Anthropic API key
cp .env.example .env
# edit .env and paste your key
```

---

## Run Order

| Step | Command | Time |
|------|---------|------|
| 1 | `python scraper.py` | 30–45 min |
| 2 | `python chunker.py` | ~10 sec |
| 3 | `python embedder.py` | 5–8 min |
| 4 | `streamlit run app.py` | instant |

Or test from the CLI:
```bash
python rag.py "What did Virat Kohli say after RCB won the IPL 2025 final?"
```

---

## Example Questions

1. What did Virat Kohli say after RCB won the IPL 2025 final?
2. How did captains react to the suspension in May?
3. Which coaches talked about the impact player rule?
4. What did Suryakumar Yadav say about MI's batting in 2025?
5. How did Punjab Kings captain react after losing the final?
6. Which captains mentioned pitch conditions most often?
7. What reasons did coaches give for losing close matches?
8. How did Dhoni describe CSK's bowling strategy in 2025?
9. What did RCB players say about their maiden IPL title?
10. How did teams respond to the India-Pakistan tensions pause?

---

## Folder Structure

```
ipl-2025-pressconference-rag-bot/
├── config.py          # Central configuration
├── scraper.py         # Web scraper (3 sources)
├── chunker.py         # Token-based chunker (tiktoken)
├── embedder.py        # sentence-transformers + ChromaDB
├── rag.py             # Retriever + Claude query engine
├── app.py             # Streamlit chat UI
├── requirements.txt
├── .env.example
├── .gitignore
├── data/
│   ├── raw/           # .txt + .json sidecar pairs
│   ├── chunks/        # chunks.json
│   └── scrape_log.txt
└── vectorstore/
    └── chroma_db/
```

---

## Potential Issues & Fixes

| Step | Risk | Fix |
|------|------|-----|
| Scraper | ESPNcricinfo returns 403 | They block bots — if blocked, try again after a few minutes; the scraper logs and skips gracefully |
| Scraper | Pages are JS-rendered, content sparse | This is expected with requests-only scraping; Cricbuzz and news pages tend to have better static HTML |
| Scraper | < 60 docs collected | Lower `MIN_DOC_WORDS` in config.py from 150 → 100 |
| Embedder | `MPS` device warning | Already forced to `device="cpu"` in embedder.py — safe to ignore |
| Embedder | `chromadb` version conflict | Pin to `chromadb==0.5.23` as in requirements.txt |
| RAG | `ANTHROPIC_API_KEY not set` | Copy `.env.example` → `.env` and fill in your key |
| Streamlit | "Collection not found" | Run embedder.py before app.py |
| General | `tiktoken` download on first run | It downloads ~1 MB encoding tables — one-time, needs internet |
