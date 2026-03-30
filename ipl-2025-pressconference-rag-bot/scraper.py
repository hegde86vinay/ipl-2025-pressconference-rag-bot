"""
IPL 2025 Press Conference Scraper — updated sources
  Source A: Indian Express IPL section   (replaces ESPNcricinfo — was 403)
  Source B: Times of India IPL           (replaces Cricbuzz — was JS-only)
  Source C: Indian Express player tags   (deep per-player interview content)
Run: python scraper.py   (~20-35 mins, targeting 60-80 docs)
"""

import json, os, re, time
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

import config

os.makedirs(config.DATA_DIR, exist_ok=True)
os.makedirs("data/chunks", exist_ok=True)

session = requests.Session()
session.headers.update(config.REQUEST_HEADERS)

scraped_count = 0
seen_urls: set = set()          # dedup across all sources


# ── Helpers ───────────────────────────────────────────────────────────────────

def log(msg: str):
    with open(config.LOG_FILE, "a") as f:
        f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n")


def safe_get(url: str):
    """GET with graceful error handling; returns BeautifulSoup or None."""
    try:
        r = session.get(url, timeout=15)
        if r.status_code in (403, 404):
            log(f"SKIP {r.status_code}: {url}")
            return None
        r.raise_for_status()
        return BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        log(f"ERROR {url}: {e}")
        return None


def slugify(text: str) -> str:
    return re.sub(r"[^\w-]", "-", text.lower())[:60].strip("-")


def clean_text(soup: BeautifulSoup) -> str:
    """Strip boilerplate tags and return normalised plain text."""
    for tag in soup(["script", "style", "nav", "header", "footer",
                     "aside", "form", "iframe", "noscript"]):
        tag.decompose()
    return " ".join(soup.get_text(" ", strip=True).split())


def extract_teams(text: str) -> list:
    return [t for t in config.IPL_TEAMS if t in text.upper()]


def save_article(text: str, meta: dict) -> bool:
    global scraped_count
    words = len(text.split())
    if words < config.MIN_DOC_WORDS:
        log(f"SKIP too short ({words} words): {meta.get('source_url','')[:80]}")
        return False
    slug = slugify(meta.get("title", "article"))
    base, n = f"{config.DATA_DIR}{slug}", 0
    while os.path.exists(f"{base}.txt"):
        n += 1
        base = f"{config.DATA_DIR}{slug}-{n}"
    with open(f"{base}.txt", "w", encoding="utf-8") as f:
        f.write(text)
    with open(f"{base}.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    scraped_count += 1
    print(f"  Scraped {scraped_count}/~70: {meta.get('title','')[:65]}")
    return True


def default_meta(url: str, title: str, source: str, text: str = "") -> dict:
    return {
        "source_url":   url,
        "title":        title,
        "date":         datetime.now().strftime("%Y-%m-%d"),
        "teams":        extract_teams(title + " " + text[:400]),
        "match_number": "",
        "author":       "",
        "source":       source,
    }


def scrape_article(url: str, source_tag: str):
    """Fetch a single article URL, extract text, and save."""
    if url in seen_urls:
        return
    seen_urls.add(url)

    soup = safe_get(url)
    time.sleep(config.REQUEST_DELAY)
    if not soup:
        return

    h1 = soup.find("h1")
    title = h1.get_text(strip=True) if h1 else url

    # Prefer semantic article containers; fall back to <main> then full page
    article = (
        soup.find("div", class_=re.compile(
            r"article[_-]?(body|content|text|details?)|"
            r"story[_-]?(body|content|detail)|"
            r"(normal|full)[_-]content", re.I))
        or soup.find("article")
        or soup.find("main")
    )
    text = clean_text(article or soup)
    save_article(text, default_meta(url, title, source_tag, text))


def collect_links(index_url: str, domain: str, path_fragment: str,
                  filter_kws: list = None, max_pages: int = 3) -> set:
    """
    Crawl an index page (+ optional pagination) and return filtered article links.
    Pagination tried via ?page=N — stops early if a page yields no new links.
    """
    all_links: set = set()

    for page in range(1, max_pages + 1):
        paged_url = index_url if page == 1 else f"{index_url}?page={page}"
        soup = safe_get(paged_url)
        time.sleep(config.REQUEST_DELAY)
        if not soup:
            break

        new_on_page = 0
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if path_fragment not in href:
                continue
            full = urljoin(domain, href) if not href.startswith("http") else href
            if full in all_links:
                continue
            anchor_text = a.get_text(" ", strip=True).lower()
            if filter_kws and not any(k in href.lower() + " " + anchor_text
                                      for k in filter_kws):
                continue
            all_links.add(full)
            new_on_page += 1

        if page > 1 and new_on_page == 0:
            break                       # no new links — stop paginating

    return all_links


# ── Source A: Indian Express IPL section ─────────────────────────────────────

def scrape_indian_express_ipl():
    print("\n── Source A: Indian Express IPL section ──")
    domain   = "https://indianexpress.com"
    path_frag = "/article/sports/cricket/"
    kws = config.INTERVIEW_KEYWORDS + [
        "ipl", "t20", "match", "final", "win", "loss", "trophy",
        "rcb", "mi", "csk", "kkr", "pbks", "srh", "rr", "dc", "gt", "lsg",
    ]

    links: set = set()
    for index_url in [config.INDIAN_EXPRESS_IPL, config.INDIAN_EXPRESS_IPL_TAG]:
        found = collect_links(index_url, domain, path_frag,
                              filter_kws=kws, max_pages=5)
        links |= found
        log(f"Source A [{index_url.split('/')[-2]}]: {len(found)} links")

    log(f"Source A total: {len(links)} unique article URLs")
    print(f"  Found {len(links)} articles — scraping ...")

    for url in sorted(links):
        if scraped_count >= 70:
            break
        scrape_article(url, "indian_express")


# ── Source B: Times of India IPL ─────────────────────────────────────────────

def scrape_times_of_india():
    print("\n── Source B: Times of India IPL ──")
    domain = "https://timesofindia.indiatimes.com"
    kws    = config.INTERVIEW_KEYWORDS + [
        "ipl", "2025", "rcb", "mi", "csk", "kkr", "pbks",
        "srh", "rr", "dc", "gt", "lsg", "captain", "coach",
    ]

    links: set = set()
    # Require /sports/cricket/ipl/ in path to exclude entertainment/lifestyle
    # articles that mention IPL only in passing
    for path_frag in ["/sports/cricket/ipl/top-stories/",
                      "/sports/cricket/ipl/t20-cricket/"]:
        found = collect_links(config.TIMES_OF_INDIA_IPL, domain,
                              path_frag, filter_kws=kws, max_pages=4)
        links |= found
        log(f"Source B [{path_frag.strip('/')}]: {len(found)} links")

    log(f"Source B total: {len(links)} unique article URLs")
    print(f"  Found {len(links)} articles — scraping ...")

    for url in sorted(links):
        if scraped_count >= 70:
            break
        scrape_article(url, "times_of_india")


# ── Source C: Indian Express player tag pages ─────────────────────────────────

def scrape_ie_player_tags():
    print("\n── Source C: Indian Express player tag pages ──")
    domain    = "https://indianexpress.com"
    path_frag = "/article/sports/cricket/"
    kws       = config.INTERVIEW_KEYWORDS + ["ipl", "2025"]

    links: set = set()
    for tag_url in config.INDIAN_EXPRESS_TAGS:
        found = collect_links(tag_url, domain, path_frag,
                              filter_kws=kws, max_pages=2)
        links |= found
        time.sleep(config.REQUEST_DELAY)

    # Exclude already-scraped URLs from Source A
    links -= seen_urls
    log(f"Source C total: {len(links)} new URLs from player tag pages")
    print(f"  Found {len(links)} new articles — scraping ...")

    for url in sorted(links):
        if scraped_count >= 70:
            break
        scrape_article(url, "indian_express_player_tag")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("IPL 2025 Press Conference Scraper")
    print("Sources: Indian Express (A + C) | Times of India (B)")
    print("Target : ~70 documents | Delay: 2s between requests")
    print("=" * 60)
    log("=== Scrape run started ===")

    scrape_indian_express_ipl()
    scrape_times_of_india()
    scrape_ie_player_tags()

    print(f"\n{'=' * 60}")
    print(f"Done. Scraped {scraped_count} documents → {config.DATA_DIR}")
    print(f"Next step: python chunker.py")
    log(f"=== Scrape complete: {scraped_count} docs ===")
