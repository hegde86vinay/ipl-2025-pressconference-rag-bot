"""Central configuration for IPL 2025 RAG Bot."""

import os

# Paths
DATA_DIR        = "data/raw/"
CHUNKS_PATH     = "data/chunks/chunks.json"
VECTORSTORE_DIR = "vectorstore/chroma_db/"
LOG_FILE        = "data/scrape_log.txt"

# Collection / model settings
COLLECTION_NAME = "ipl_2025_presscon"
EMBED_MODEL     = "all-MiniLM-L6-v2"
LLM_PROVIDER    = "claude"
LLM_MODEL       = "claude-haiku-4-5-20251001"

# RAG params
TOP_K         = 3
CHUNK_SIZE    = 500
CHUNK_OVERLAP = 50

# Scraper rules
MIN_DOC_WORDS   = 150
REQUEST_DELAY   = 2            # seconds between requests — be polite
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

# ── Source URLs (updated March 2026) ─────────────────────────────────────────
# ESPNcricinfo → blocked (Cloudflare 403)
# Cricbuzz     → JS-rendered React shell (empty response with requests)
# Replacements confirmed accessible with requests + BeautifulSoup:

# Source A — Indian Express IPL section (captain/coach quotes, match reports)
INDIAN_EXPRESS_IPL     = "https://indianexpress.com/section/sports/ipl/"
INDIAN_EXPRESS_IPL_TAG = "https://indianexpress.com/about/ipl-2025/"

# Source B — Times of India IPL (highest text density, post-match interviews)
TIMES_OF_INDIA_IPL     = "https://timesofindia.indiatimes.com/sports/cricket/ipl"

# Source C — Indian Express player tag pages (deep interview content per player)
INDIAN_EXPRESS_TAGS = [
    "https://indianexpress.com/about/ipl-2025/",
    "https://indianexpress.com/about/virat-kohli/",
    "https://indianexpress.com/about/rohit-sharma/",
    "https://indianexpress.com/about/ms-dhoni/",
    "https://indianexpress.com/about/hardik-pandya/",
    "https://indianexpress.com/about/shubman-gill/",
]

# ── Deprecated (kept for reference) ──────────────────────────────────────────
# ESPNCRICINFO_RESULTS = "https://www.espncricinfo.com/series/ipl-2025-1449924/match-results"
# ESPNCRICINFO_NEWS    = "https://www.espncricinfo.com/series/ipl-2025-1449924/news"
# CRICBUZZ_NEWS        = "https://www.cricbuzz.com/cricket-series/6732/indian-premier-league-2025/news"

# Keywords to filter interview/press-conference articles
INTERVIEW_KEYWORDS = [
    "interview", "press conference", "captain", "coach",
    "said", "speaks", "reacts", "reaction", "quotes",
    "post-match", "preview", "verdict", "review",
]

# IPL 2025 teams — used to tag documents with participating teams
IPL_TEAMS = ["RCB", "MI", "CSK", "KKR", "PBKS", "SRH", "RR", "DC", "GT", "LSG"]


def get_api_key() -> str:
    from dotenv import load_dotenv
    load_dotenv()
    key = os.getenv("ANTHROPIC_API_KEY", "")
    if not key:
        raise EnvironmentError(
            "ANTHROPIC_API_KEY not set. Copy .env.example → .env and fill it in."
        )
    return key
