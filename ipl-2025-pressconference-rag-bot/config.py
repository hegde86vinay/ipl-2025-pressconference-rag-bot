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
REQUEST_DELAY   = 2            # seconds between requests
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (educational research)"
}

# Source URLs
ESPNCRICINFO_RESULTS = (
    "https://www.espncricinfo.com/series/ipl-2025-1449924/match-results"
)
ESPNCRICINFO_NEWS = (
    "https://www.espncricinfo.com/series/ipl-2025-1449924/news"
)
CRICBUZZ_NEWS = (
    "https://www.cricbuzz.com/cricket-series/6732/indian-premier-league-2025/news"
)

# Keywords to filter interview/press-conference articles
INTERVIEW_KEYWORDS = [
    "interview", "press conference", "captain", "coach",
    "said", "speaks", "reacts", "reaction", "quotes",
]

# Ensure ANTHROPIC_API_KEY is loaded at import time so callers get a clear error
def get_api_key() -> str:
    from dotenv import load_dotenv
    load_dotenv()
    key = os.getenv("ANTHROPIC_API_KEY", "")
    if not key:
        raise EnvironmentError(
            "ANTHROPIC_API_KEY not set. Copy .env.example → .env and fill it in."
        )
    return key
