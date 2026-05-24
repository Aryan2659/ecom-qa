"""
src/scraper/scraper.py
Fix #3 — 3-tier scraping with caching:
  Tier 1: Playwright (headless Chromium + stealth) — handles JS-heavy pages
  Tier 2: requests + BeautifulSoup with rotated headers — fast, for simple pages
  Tier 3: Graceful failure — tells user to paste text manually
Also implements URL-level SQLite caching (Fix #3 cache requirement).
"""

import re
import time
import logging
import hashlib
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# How long to keep a cached page (seconds)
CACHE_TTL_SECONDS = 60 * 60 * 6   # 6 hours

# Realistic browser headers to reduce bot detection
HEADERS_POOL = [
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Connection": "keep-alive",
    },
    {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) "
                      "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                      "Version/17.4.1 Safari/605.1.15",
        "Accept-Language": "en-GB,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    },
]

# CSS selectors for product content on known sites
SITE_SELECTORS = {
    "amazon":   ["#productTitle", "#feature-bullets", "#productDescription",
                 "#aplus", ".a-expander-content", "#customerReviews",
                 "[data-component-type='s-customer-reviews']"],
    "flipkart": ["._1AtVbE", ".G4BRas", "._1mXcCf", "._3nPA3R",
                 "._3dtsli", ".t-ZTKy", "._2kHMtA"],
    "default":  ["main", "article", "#content", ".product", ".description",
                 "[itemprop='description']", "body"],
}


def _url_hash(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:32]


def _detect_site(url: str) -> str:
    domain = urlparse(url).netloc.lower()
    if "amazon" in domain:
        return "amazon"
    if "flipkart" in domain:
        return "flipkart"
    return "default"


def _clean_text(text: str) -> str:
    """Remove excessive whitespace and non-printable characters."""
    text = re.sub(r"[\r\n\t]+", " ", text)
    text = re.sub(r" {2,}", " ", text)
    return text.strip()


def _extract_from_soup(soup: BeautifulSoup, site: str) -> str:
    """Extract product text using site-specific selectors."""
    selectors = SITE_SELECTORS.get(site, SITE_SELECTORS["default"])
    parts = []
    for sel in selectors:
        for el in soup.select(sel):
            t = el.get_text(separator=" ").strip()
            if t:
                parts.append(t)

    if not parts:
        # last resort: all paragraph text
        parts = [p.get_text() for p in soup.find_all("p") if len(p.get_text()) > 30]

    return _clean_text(" ".join(parts))


class Scraper:
    def __init__(self, db=None):
        self._db = db

    # ── Cache helpers ─────────────────────────────────────────────────────────
    def _get_cached(self, url: str):
        if self._db is None:
            return None
        return self._db.get_cached_page(url)

    def _save_cache(self, url: str, text: str):
        if self._db:
            self._db.cache_page(url, text)

    # ── Tier 1: Playwright ────────────────────────────────────────────────────
    def _scrape_playwright(self, url: str) -> str | None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.info("Playwright not installed — skipping Tier 1")
            return None

        logger.info("Tier 1 scraping (Playwright): %s", url)
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=[
                    "--no-sandbox", "--disable-setuid-sandbox",
                    "--disable-blink-features=AutomationControlled",
                ])
                ctx = browser.new_context(
                    user_agent=HEADERS_POOL[0]["User-Agent"],
                    viewport={"width": 1280, "height": 720},
                    locale="en-US",
                )
                # Stealth: hide navigator.webdriver
                ctx.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3]});
                """)
                page = ctx.new_page()
                page.goto(url, timeout=20_000, wait_until="domcontentloaded")
                time.sleep(2)   # let lazy content load
                html = page.content()
                browser.close()

            soup = BeautifulSoup(html, "html.parser")
            text = _extract_from_soup(soup, _detect_site(url))
            return text if len(text) > 200 else None

        except Exception as e:
            logger.warning("Playwright scraping failed: %s", e)
            return None

    # ── Tier 2: requests + BeautifulSoup ─────────────────────────────────────
    def _scrape_requests(self, url: str) -> str | None:
        logger.info("Tier 2 scraping (requests): %s", url)
        import random
        headers = random.choice(HEADERS_POOL)
        try:
            resp = requests.get(url, headers=headers, timeout=15, allow_redirects=True)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            # Remove script / style noise
            for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                tag.decompose()
            text = _extract_from_soup(soup, _detect_site(url))
            return text if len(text) > 200 else None
        except Exception as e:
            logger.warning("requests scraping failed: %s", e)
            return None

    # ── Public interface ──────────────────────────────────────────────────────
    def scrape(self, url: str) -> tuple[str, str]:
        """
        Returns (text, source_tier) where source_tier is one of:
        'cache' | 'playwright' | 'requests' | None
        Raises ValueError if all tiers fail.
        """
        # Check cache first
        cached = self._get_cached(url)
        if cached:
            logger.info("Cache hit for %s", url)
            return cached, "cache"

        # Tier 1
        text = self._scrape_playwright(url)
        if text:
            self._save_cache(url, text)
            return text, "playwright"

        # Tier 2
        text = self._scrape_requests(url)
        if text:
            self._save_cache(url, text)
            return text, "requests"

        # Tier 3: fail gracefully
        raise ValueError(
            "Could not scrape this URL automatically. "
            "Please copy and paste the product description text manually."
        )
