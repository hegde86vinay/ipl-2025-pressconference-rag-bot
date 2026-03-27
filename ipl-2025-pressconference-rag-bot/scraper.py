"""
IPL 2025 Press Conference Scraper (3 sources)
Run: python scraper.py
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


def log(msg):
    with open(config.LOG_FILE, "a") as f:
        f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n")


def safe_get(url):
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


def slugify(text):
    return re.sub(r"[^\w-]", "-", text.lower())[:60].strip("-")


def clean_text(soup):
    for t in soup(["script", "style", "nav", "header", "footer"]):
        t.decompose()
    return " ".join(soup.get_text(" ", strip=True).split())


def save_article(text, meta):
    global scraped_count
    if len(text.split()) < config.MIN_DOC_WORDS:
        return False
    slug = slugify(meta.get("title", "article"))
    base, n = f"{config.DATA_DIR}{slug}", 0
    while os.path.exists(f"{base}.txt"):
        n += 1; base = f"{config.DATA_DIR}{slug}-{n}"
    open(f"{base}.txt", "w").write(text)
    json.dump(meta, open(f"{base}.json", "w"), indent=2)
    scraped_count += 1
    print(f"Scraped {scraped_count}/~70: {meta.get('title','')[:60]}")
    return True


def default_meta(url, title, source):
    return {"source_url": url, "title": title, "date": datetime.now().strftime("%Y-%m-%d"),
            "teams": [], "match_number": "", "author": "", "source": source}

def scrape_page(url, source_tag):
    soup = safe_get(url)
    time.sleep(config.REQUEST_DELAY)
    if not soup: return
    h1 = soup.find("h1")
    title = h1.get_text(strip=True) if h1 else url
    article = (soup.find("article")
               or soup.find(class_=re.compile(r"article|story|report|content", re.I))
               or soup.find("main"))
    save_article(clean_text(article or soup), default_meta(url, title, source_tag))

def collect_links(index_url, domain, path_fragment, filter_kws=None):
    soup = safe_get(index_url)
    if not soup: return set()
    links = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if path_fragment in href:
            full = urljoin(domain, href)
            if not filter_kws or any(k in (href + a.get_text()).lower() for k in filter_kws):
                links.add(full)
    return links


# ── Source A ──────────────────────────────────────────────────────────────────

def scrape_espn_match_reports():
    print("\n── Source A: ESPNcricinfo match reports ──")
    base = "https://www.espncricinfo.com"
    links = collect_links(config.ESPNCRICINFO_RESULTS, base, "/series/ipl-2025-1449924/")
    report_links = {
        u.replace("/full-scorecard", "/match-report")
        for u in links
        if "full-scorecard" in u or "match-report" in u
    }
    log(f"Source A: {len(report_links)} match report URLs")
    for url in sorted(report_links):
        if scraped_count >= 70: break
        scrape_page(url, "espncricinfo_match_report")


# ── Source B ──────────────────────────────────────────────────────────────────

def scrape_espn_news():
    print("\n── Source B: ESPNcricinfo news / interviews ──")
    base = "https://www.espncricinfo.com"
    links = collect_links(config.ESPNCRICINFO_NEWS, base, "/story/",
                          filter_kws=config.INTERVIEW_KEYWORDS)
    links |= collect_links(config.ESPNCRICINFO_NEWS, base, "/news/",
                           filter_kws=config.INTERVIEW_KEYWORDS)
    log(f"Source B: {len(links)} news URLs")
    for url in sorted(links):
        if scraped_count >= 70: break
        scrape_page(url, "espncricinfo_news")


# ── Source C ──────────────────────────────────────────────────────────────────

def scrape_cricbuzz():
    print("\n── Source C: Cricbuzz match reviews ──")
    base = "https://www.cricbuzz.com"
    kws = config.INTERVIEW_KEYWORDS + ["review", "report"]
    links = collect_links(config.CRICBUZZ_NEWS, base, "/cricket-news/", filter_kws=kws)
    links |= collect_links(config.CRICBUZZ_NEWS, base, "/cricket-match/", filter_kws=kws)
    log(f"Source C: {len(links)} Cricbuzz URLs")
    for url in sorted(links):
        if scraped_count >= 70: break
        scrape_page(url, "cricbuzz")


if __name__ == "__main__":
    print("Starting IPL 2025 scraper — target ~70 documents")
    log("=== Scrape run started ===")
    scrape_espn_match_reports()
    scrape_espn_news()
    scrape_cricbuzz()
    print(f"\nDone. Scraped {scraped_count} documents → {config.DATA_DIR}")
    log(f"=== Scrape complete: {scraped_count} docs ===")
