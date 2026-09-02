"""Pure RSS parsing and ticker tagging -- no database, no ORM.

Split from news.py so the 5-minute CI job can import this alone. Pulling in
SQLAlchemy would also construct a database engine at import time, which that
job has no database for; keeping the parsing pure means the scheduled news
refresh needs nothing but httpx.

Keyless by design. Every commercial news API (Benzinga, FMP, Tiingo, Intrinio)
requires credentials, and OpenBB's news module is a thin wrapper over those.
Publisher RSS feeds are free, need no account, and are explicitly published for
syndication.

Deduplication happens on a hash of the canonical link rather than the title,
because the same wire story appears across feeds with reworded headlines and
different tracking parameters.
"""

from __future__ import annotations

import hashlib
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx
log = logging.getLogger(__name__)

USER_AGENT = "finance-dashboard/0.1 (https://github.com/AadhavSivakumar/Finance)"

FEEDS: dict[str, str] = {
    "Yahoo Finance": "https://finance.yahoo.com/news/rssindex",
    "CNBC Markets": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=15839069",
    "MarketWatch": "https://feeds.content.dowjones.io/public/rss/mw_topstories",
    "Investing.com": "https://www.investing.com/rss/news_25.rss",
}

# Tickers too short or too word-like to match safely in prose. "A" (Agilent),
# "IT" (Gartner) and "ON" (ON Semiconductor) would tag almost every headline.
TICKER_STOPLIST = {
    "A", "IT", "ON", "SO", "ALL", "KEY", "NOW", "CAT", "GO", "BY", "OR", "AN",
    "ARE", "HAS", "NEW", "TWO", "ONE", "SEE", "USA", "CEO", "AI", "EW", "DD",
    "PM", "MA", "MO", "K", "L", "C", "D", "F", "T", "V", "O",
}

# Single-word company names that are also common surnames or ordinary words.
# Matching these in prose produces false positives -- "USDA's Rollins" is a
# person, not Rollins Inc. Tagging is best-effort pattern matching, not entity
# resolution; proper NER would be the real fix and is disproportionate here.
NAME_STOPLIST = {
    "rollins", "cooper", "baker", "hunt", "moore", "hershey", "carrier",
    "brown", "campbell", "franklin", "gartner", "martin", "mosaic", "news",
    "regency", "sterling", "stanley", "charles", "howard", "jack", "jackson",
    "west", "york", "phillips", "watts", "wells", "morgan", "hess", "monster",
}

# Corporate suffixes stripped before matching a company name in a headline.
SUFFIXES = re.compile(
    r"\b(inc|corp|corporation|co|company|ltd|limited|plc|holdings|group|the|"
    r"class [abc]|&amp;|and)\b\.?", re.IGNORECASE
)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", "ignore")).hexdigest()[:32]


def _canonical(url: str) -> str:
    """Drop query strings so utm_* tracking does not defeat deduplication."""
    return url.split("?")[0].rstrip("/").lower()


def _parse_date(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        dt = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _clean(text: str | None) -> str:
    if not text:
        return ""
    # Feeds embed HTML in <description>; strip tags rather than render them.
    return re.sub(r"<[^>]+>", "", text).replace("&nbsp;", " ").strip()


def fetch_feed(name: str, url: str, timeout: float = 15.0) -> list[dict]:
    resp = httpx.get(
        url, timeout=timeout, follow_redirects=True, headers={"User-Agent": USER_AGENT}
    )
    resp.raise_for_status()
    root = ET.fromstring(resp.content)

    items = []
    for node in root.findall(".//item"):
        title = _clean(node.findtext("title"))
        link = (node.findtext("link") or "").strip()
        if not title or not link:
            continue
        items.append(
            {
                "guid": _hash(_canonical(link)),
                "title": title[:600],
                "link": link[:900],
                "source": name,
                "summary": _clean(node.findtext("description"))[:900],
                "published_at": _parse_date(node.findtext("pubDate")),
            }
        )
    return items




def tag_symbols(text: str, matchers: list[tuple[str, list["re.Pattern"]]], limit: int = 6) -> list[str]:
    """Best-effort ticker tagging by pattern match.

    Not entity resolution: a headline about a person named Rollins can still
    match Rollins Inc. The stoplists above cut the common cases, and the UI
    labels these tags as approximate.
    """
    hits = [sym for sym, patterns in matchers if any(p.search(text) for p in patterns)]
    return hits[:limit]


def build_matchers(symbol_names: list[tuple[str, str]]) -> list[tuple[str, list[re.Pattern]]]:
    """(symbol, name) pairs -> compiled matchers.

    Tickers match CASE-SENSITIVELY, company names case-insensitively. That
    asymmetry matters: tickers are written uppercase in prose, and matching
    them loosely turns ordinary words into tags -- "slides below all major MAs"
    was tagging MAS (Masco), because case-insensitively "MAs" is "MAS".

    Takes plain tuples rather than ORM rows so this works identically against
    the database and against a JSON file.
    """
    out: list[tuple[str, list[re.Pattern]]] = []
    for symbol, raw_name in symbol_names:
        patterns: list[re.Pattern] = []

        sym = (symbol or "").upper()
        if sym and sym not in TICKER_STOPLIST and len(sym) >= 2 and "-" not in sym and not sym.startswith("^"):
            # No IGNORECASE here, deliberately.
            patterns.append(re.compile(r"\b" + re.escape(sym) + r"\b"))

        name = SUFFIXES.sub("", raw_name or "").strip(" ,.&")
        name_ok = (
            len(name) >= 5 and " " not in name and name.lower() not in NAME_STOPLIST
        ) or (len(name.split()) >= 2 and len(name) >= 8)
        if name_ok:
            patterns.append(re.compile(r"\b" + re.escape(name) + r"\b", re.IGNORECASE))

        if patterns:
            out.append((symbol, patterns))
    return out


def collect(symbol_names: list[tuple[str, str]] | None = None) -> tuple[list[dict], dict[str, int]]:
    """Fetch every feed, tag, and deduplicate. Returns (items, per-feed counts)."""
    matchers = build_matchers(symbol_names or [])
    stats: dict[str, int] = {}
    rows: list[dict] = []

    for name, url in FEEDS.items():
        try:
            items = fetch_feed(name, url)
        except Exception as exc:  # noqa: BLE001
            log.warning("feed %s failed: %s", name, exc)
            stats[name] = 0
            continue
        for item in items:
            item["symbols"] = tag_symbols(f"{item['title']} {item['summary']}", matchers)
        rows.extend(items)
        stats[name] = len(items)

    # The same wire story often appears in two feeds within one pull, and
    # ON CONFLICT cannot resolve duplicates arriving inside a single statement.
    seen: set[str] = set()
    unique = []
    for r in rows:
        if r["guid"] in seen:
            continue
        seen.add(r["guid"])
        unique.append(r)
    return unique, stats
