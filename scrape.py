#!/usr/bin/env python3
"""
Geopolitics / International Relations Google News RSS → Direct URL RSS
Fetches two Google News search feeds, decodes redirect URLs, merges,
deduplicates, sorts by pubDate desc, and writes a 500-item RSS 2.0 feed.
"""

import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import feedparser
import requests
from googlenewsdecoder import new_decoderv1 as gnewsdecoder

# ── Config ─────────────────────────────────────────────────────────────────────
FEED_URLS = [
    (
        "https://news.google.com/rss/search?"
        'q=%22foreign+policy%22+OR+%22diplomacy%22+OR+%22geopolitics%22+'
        'OR+%22international+relations%22+when%3A7d'
        "&hl=en-US&gl=US&ceid=US%3Aen"
    ),
    (
        "https://news.google.com/rss/search?"
        "q=geopolitics+OR+%22international+relations%22+OR+%22foreign+affairs%22+"
        'OR+%22global+affairs%22+when%3A7d'
        "&hl=en-US&gl=US&ceid=US%3Aen"
    ),
]

STATE_FILE  = "state/seen_guids.json"
OUTPUT_FILE = "feed/geopolitics.xml"
MAX_ITEMS   = 500
MAX_SEEN    = 5000
DECODE_DELAY = 0.3           # seconds between decoder calls

FEED_TITLE = "Geopolitics & International Relations"
FEED_DESC  = (
    "Curated geopolitics, foreign policy, and international relations news "
    "with direct article URLs, decoded from Google News."
)
FEED_LINK = "https://news.google.com"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}


# ── Helpers ────────────────────────────────────────────────────────────────────
def now_rfc822() -> str:
    return datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")


def strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s).replace("&nbsp;", " ").strip()


def parse_pubdate(pub: str) -> datetime:
    """Parse RFC 822 pubDate to timezone-aware datetime for sorting. Falls back to epoch."""
    try:
        return parsedate_to_datetime(pub)
    except Exception:
        return datetime.fromtimestamp(0, tz=timezone.utc)


# ── State ──────────────────────────────────────────────────────────────────────
def load_seen(path: str) -> list:
    p = Path(path)
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text())
    except Exception:
        return []


def save_seen(path: str, seen: list):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(seen[-MAX_SEEN:]))


# ── URL Decoding ───────────────────────────────────────────────────────────────
def decode_url(google_url: str) -> str:
    """
    1. googlenewsdecoder (pure computation, no network).
    2. HTTP redirect follow.
    3. Return original if both fail.
    """
    try:
        try:
            result = gnewsdecoder(google_url, interval=0)
        except TypeError:
            result = gnewsdecoder(google_url)
        url = (result or {}).get("decoded_url", "")
        if url and url.startswith("http"):
            return url
    except Exception as e:
        print(f"      [decoder error: {e}] trying redirect…")

    try:
        r = requests.get(google_url, allow_redirects=True, headers=HEADERS, timeout=15)
        if r.url and r.url.startswith("http") and "google.com" not in r.url:
            return r.url
    except Exception as e:
        print(f"      [redirect error: {e}]")

    return google_url


# ── XML I/O ────────────────────────────────────────────────────────────────────
def load_existing(path: str) -> list[dict]:
    if not Path(path).exists():
        return []
    try:
        root = ET.parse(path).getroot()
        ch = root.find("channel")
        if ch is None:
            return []
        return [
            {
                "title":   it.findtext("title", ""),
                "link":    it.findtext("link", ""),
                "desc":    it.findtext("description", ""),
                "pubDate": it.findtext("pubDate", ""),
            }
            for it in ch.findall("item")
        ]
    except Exception as e:
        print(f"[load_existing error: {e}]")
        return []


def write_rss(items: list[dict], path: str):
    rss = ET.Element("rss", attrib={"version": "2.0"})
    ch  = ET.SubElement(rss, "channel")

    ET.SubElement(ch, "title").text        = FEED_TITLE
    ET.SubElement(ch, "link").text         = FEED_LINK
    ET.SubElement(ch, "description").text  = FEED_DESC
    ET.SubElement(ch, "language").text     = "en-US"
    ET.SubElement(ch, "lastBuildDate").text = now_rfc822()

    for d in items:
        it = ET.SubElement(ch, "item")
        ET.SubElement(it, "title").text       = d["title"]
        ET.SubElement(it, "link").text        = d["link"]
        ET.SubElement(it, "description").text = d["desc"]
        ET.SubElement(it, "pubDate").text     = d["pubDate"]
        g = ET.SubElement(it, "guid")
        g.set("isPermaLink", "true")
        g.text = d["link"]

    ET.indent(rss, space="  ")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        + ET.tostring(rss, encoding="unicode"),
        encoding="utf-8",
    )


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    seen_list = load_seen(STATE_FILE)
    seen_set  = set(seen_list)
    existing  = load_existing(OUTPUT_FILE)

    print(f"Known GUIDs : {len(seen_set)}")
    print(f"Existing    : {len(existing)} items in feed")

    # ── Fetch all feeds, deduplicate entries by GUID across feeds ──────────────
    all_entries: list[tuple[str, object]] = []   # (guid, entry)
    seen_this_run: set[str] = set()

    for i, url in enumerate(FEED_URLS, 1):
        print(f"\nFeed {i}/{len(FEED_URLS)}: {url[:80]}…")
        feed = feedparser.parse(url)
        if feed.bozo and not feed.entries:
            print(f"  [fetch failed: {feed.bozo_exception}]")
            continue
        print(f"  Entries: {len(feed.entries)}")
        for entry in feed.entries:
            guid = entry.get("id", "")
            if not guid or guid in seen_this_run:
                continue
            seen_this_run.add(guid)
            all_entries.append((guid, entry))

    print(f"\nUnique entries across feeds: {len(all_entries)}")

    # ── Decode new entries ─────────────────────────────────────────────────────
    new_items: list[dict] = []

    for guid, entry in all_entries:
        if guid in seen_set:
            continue

        title   = entry.get("title", "No title")
        raw_url = entry.get("link", "")
        desc    = strip_html(entry.get("summary", title))
        pub     = entry.get("published", now_rfc822())

        print(f"  + {title[:80]}")
        direct_url = decode_url(raw_url)

        new_items.append({"title": title, "link": direct_url, "desc": desc, "pubDate": pub})
        seen_list.append(guid)
        seen_set.add(guid)
        time.sleep(DECODE_DELAY)

    print(f"\nNew items   : {len(new_items)}")

    # ── Dedup existing by link (handles URL collisions across runs) ────────────
    existing_links = {d["link"] for d in new_items}
    deduped_existing = [d for d in existing if d["link"] not in existing_links]

    # ── Merge and sort by pubDate descending ───────────────────────────────────
    combined = new_items + deduped_existing
    combined.sort(key=lambda d: parse_pubdate(d["pubDate"]), reverse=True)
    final = combined[:MAX_ITEMS]

    write_rss(final, OUTPUT_FILE)
    print(f"Output      : {len(final)} items → {OUTPUT_FILE}")

    save_seen(STATE_FILE, seen_list)
    print("State saved.")


if __name__ == "__main__":
    main()
