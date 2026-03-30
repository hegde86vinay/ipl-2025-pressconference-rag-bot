# Scraper Service

## Overview

`scraper.py` is the **data collection layer** of the pipeline. It harvests written text about IPL 2025 from three cricket journalism sources, applies quality filters, and persists each article as a plain-text file alongside a structured JSON metadata sidecar. Every downstream component — chunker, embedder, RAG engine — depends on the output of this step.

The scraper is intentionally simple: no headless browser, no JavaScript execution, no proxy rotation. It targets the static HTML that servers return to a plain `GET` request, which is sufficient for article bodies on these sites.

---

## Tech Stack

| Library | Version | Role | Why this choice |
|---------|---------|------|-----------------|
| `requests` | 2.32 | HTTP client | Industry-standard, connection pooling via `Session`, clean timeout control |
| `BeautifulSoup4` | 4.12 | HTML parser | Tolerant of malformed HTML (common on sports sites); simple CSS/tag selector API |
| `lxml` (bs4 backend) | — | Fast HTML parser | 3–5× faster than Python's built-in `html.parser` for large pages |
| `time.sleep` | stdlib | Rate limiting | Polite crawling — 2 s gap prevents IP bans and respects server load |
| `json` | stdlib | Metadata serialisation | Human-readable sidecar files that any downstream tool can consume |
| `re` | stdlib | URL filtering & slugs | Lightweight pattern matching without adding a dependency |

**Why `requests` over `httpx` or `aiohttp`?**
Scraping here is I/O-bound but sequential (intentional rate limiting). `requests` is synchronous, battle-tested, and has zero async complexity overhead. Async would only help if we parallelised requests — which we deliberately avoid to stay polite.

**Why not Selenium / Playwright?**
ESPNcricinfo's article bodies render some content server-side in static HTML. A headless browser adds ~500 MB of Chromium, significant startup latency, and anti-bot fingerprinting risk. For this hobby project the tradeoff is not worth it.

---

## Component Diagram

```mermaid
flowchart TD
    START(["▶ python scraper.py"])

    subgraph INIT["Initialisation"]
        I1["Create data/raw/ directory"]
        I2["Open requests.Session\nwith User-Agent header"]
        I3["Reset scraped_count = 0"]
        I1 --> I2 --> I3
    end

    subgraph SRC_A["Source A — ESPNcricinfo Match Reports"]
        A1["GET /series/ipl-2025-1449924/match-results"]
        A2["Parse all &lt;a href&gt; tags"]
        A3["Filter: href contains\n'match-report' or\n'full-scorecard'"]
        A4["Rewrite scorecard URLs\n→ match-report URLs"]
        A5["De-duplicate with set()"]
        A1 --> A2 --> A3 --> A4 --> A5
    end

    subgraph SRC_B["Source B — ESPNcricinfo News & Interviews"]
        B1["GET /series/ipl-2025-1449924/news"]
        B2["Parse all &lt;a href&gt; tags"]
        B3["Filter: href contains\n'/story/' or '/news/'"]
        B4["Keyword filter on href + link text:\ninterview · captain · coach\nreacts · speaks · said · quotes"]
        B5["De-duplicate with set()"]
        B1 --> B2 --> B3 --> B4 --> B5
    end

    subgraph SRC_C["Source C — Cricbuzz Match Reviews"]
        C1["GET /cricket-series/6732/.../news"]
        C2["Parse all &lt;a href&gt; tags"]
        C3["Filter: href contains\n'/cricket-news/' or '/cricket-match/'"]
        C4["Keyword filter:\ninterview · review · report\ncaptain · reacts · said"]
        C5["De-duplicate with set()"]
        C1 --> C2 --> C3 --> C4 --> C5
    end

    subgraph FETCH["Per-URL Fetch & Parse"]
        F1["safe_get(url)\nGET with 15 s timeout"]
        F2{"HTTP status?"}
        F3["Parse BeautifulSoup"]
        F4["Extract &lt;h1&gt; → title"]
        F5["Find article / main / .content\nRemove script·style·nav·footer"]
        F6["get_text() → collapse whitespace"]
        F1 --> F2
        F2 -- "200 OK" --> F3 --> F4 --> F5 --> F6
        F2 -- "403 / 404" --> SKIP_HTTP["Log to scrape_log.txt\nSkip URL"]
        F2 -- "Exception / timeout" --> SKIP_ERR["Log error\nSkip URL"]
    end

    subgraph SAVE["Quality Gate & Persist"]
        S1{"word count\n≥ MIN_DOC_WORDS\n(150)?"}
        S2["slugify(title) → filename"]
        S3["Collision check:\nadd -1 -2 suffix if needed"]
        S4["Write data/raw/&lt;slug&gt;.txt"]
        S5["Write data/raw/&lt;slug&gt;.json\n{source_url, title, date,\n teams, match_number, author, source}"]
        S6["scraped_count += 1\nPrint progress"]
        S7["Log: TOO_SHORT\nDiscard article"]
        S1 -- "Yes" --> S2 --> S3 --> S4 --> S5 --> S6
        S1 -- "No" --> S7
    end

    GUARD{"scraped_count\n≥ 70?"}
    DONE(["✅ Done — N docs in data/raw/"])

    START --> INIT --> SRC_A
    SRC_A --> GUARD
    GUARD -- "No" --> SRC_B
    SRC_B --> GUARD
    GUARD -- "No" --> SRC_C
    SRC_C --> GUARD

    A5 & B5 & C5 -->|"sorted URL list"| FETCH
    FETCH --> SAVE
    SAVE --> GUARD
    GUARD -- "Yes" --> DONE

    classDef source  fill:#dbeafe,stroke:#3b82f6,color:#1e3a5f
    classDef process fill:#f0fdf4,stroke:#16a34a,color:#14532d
    classDef decision fill:#fef9c3,stroke:#ca8a04,color:#713f12
    classDef io      fill:#f3e8ff,stroke:#9333ea,color:#3b0764
    classDef error   fill:#fee2e2,stroke:#dc2626,color:#7f1d1d

    class SRC_A,SRC_B,SRC_C source
    class FETCH,SAVE process
    class F2,S1,GUARD decision
    class S4,S5,DONE io
    class SKIP_HTTP,SKIP_ERR,S7 error
```

---

## Sequence Diagram

```mermaid
sequenceDiagram
    actor User
    participant Scraper as scraper.py
    participant ESPN_R  as ESPNcricinfo<br/>(Match Results)
    participant ESPN_N  as ESPNcricinfo<br/>(News)
    participant CB      as Cricbuzz<br/>(News)
    participant FS      as data/raw/<br/>(Filesystem)
    participant Log     as scrape_log.txt

    User->>Scraper: python scraper.py

    Note over Scraper: Phase 1 — Source A

    Scraper->>ESPN_R: GET /series/ipl-2025-1449924/match-results
    ESPN_R-->>Scraper: 200 HTML (match cards)
    Scraper->>Scraper: parse <a> tags → collect match-report URLs

    loop For each match-report URL
        Scraper->>Scraper: time.sleep(2)
        Scraper->>ESPN_R: GET /series/.../match-report
        alt 200 OK
            ESPN_R-->>Scraper: HTML article
            Scraper->>Scraper: extract title + body text
            Scraper->>Scraper: word count ≥ 150?
            alt Passes quality gate
                Scraper->>FS: write <slug>.txt
                Scraper->>FS: write <slug>.json (metadata)
            else Too short
                Scraper->>Log: TOO_SHORT: <url>
            end
        else 403 / 404
            ESPN_R-->>Scraper: 403 Forbidden
            Scraper->>Log: SKIP 403: <url>
        else Network error
            Scraper->>Log: ERROR <url>: <exception>
        end
    end

    Note over Scraper: Phase 2 — Source B

    Scraper->>ESPN_N: GET /series/ipl-2025-1449924/news
    ESPN_N-->>Scraper: 200 HTML (news index)
    Scraper->>Scraper: filter links by keyword (interview, captain, reacts …)

    loop For each news URL
        Scraper->>Scraper: time.sleep(2)
        Scraper->>ESPN_N: GET /story/<article>
        ESPN_N-->>Scraper: 200 HTML
        Scraper->>Scraper: extract + quality-gate
        Scraper->>FS: write .txt + .json
    end

    Note over Scraper: Phase 3 — Source C

    Scraper->>CB: GET /cricket-series/6732/.../news
    CB-->>Scraper: 200 HTML (news index)
    Scraper->>Scraper: filter links by keyword (review, report, captain …)

    loop For each Cricbuzz URL
        Scraper->>Scraper: time.sleep(2)
        Scraper->>CB: GET /cricket-news/<article>
        CB-->>Scraper: 200 HTML
        Scraper->>Scraper: extract + quality-gate
        Scraper->>FS: write .txt + .json
    end

    Scraper->>Log: === Scrape complete: N docs ===
    Scraper-->>User: Done. Scraped N documents → data/raw/
```

---

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| `requests.Session` (not bare `requests.get`) | Reuses TCP connections; shares headers across all requests automatically |
| 2-second `time.sleep` between every request | Mimics human browsing pace; reduces chance of IP rate-limiting by target sites |
| Keyword filter on URL + anchor text | Eliminates scorecard-only and stats pages; focuses the corpus on spoken-word content |
| `.txt` + `.json` sidecar pattern | Keeps raw text and metadata decoupled; either file can be inspected or replaced independently without touching the other |
| SHA-256 collision-safe slug suffix | Prevents overwriting when two articles have the same title slug |
| Hard stop at 70 documents | Keeps embedding time under 8 min on M2 Air; prevents runaway scraping on a first run |

---

## Output Schema (`data/raw/<slug>.json`)

```json
{
  "source_url":   "https://www.espncricinfo.com/series/.../match-report",
  "title":        "RCB beat PBKS by 6 runs — Match Report",
  "date":         "2025-06-03",
  "teams":        [],
  "match_number": "",
  "author":       "",
  "source":       "espncricinfo_match_report"
}
```

> `teams`, `match_number`, and `author` are scaffolded for future enrichment (e.g. regex extraction from the article body or ESPNcricinfo's JSON API).
