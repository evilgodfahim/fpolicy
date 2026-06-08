# Geopolitics Feed

Hourly-updated RSS feed for geopolitics, foreign policy, and international relations.  
Google News redirect URLs are decoded to direct article links before publishing.

## Structure

```
.
├── scrape.py                     # main script
├── requirements.txt
├── state/
│   └── seen_guids.json           # persisted GUID state (committed by CI)
├── feed/
│   └── geopolitics.xml           # output RSS 2.0 feed (committed by CI)
├── index.html                    # web viewer (GitHub Pages)
└── .github/workflows/
    └── scrape.yml                # hourly Actions workflow
```

## Sources

Two Google News search feeds covering the past 7 days:

1. `"foreign policy" OR "diplomacy" OR "geopolitics" OR "international relations"`
2. `geopolitics OR "international relations" OR "foreign affairs" OR "global affairs"`

Items are merged, deduplicated by GUID (across feeds and across runs), and sorted by `pubDate` descending. The output is capped at 500 items.

## Setup

1. Fork / clone this repo.
2. Go to **Settings → Pages** and set source to `main` branch, root (`/`).
3. The Actions workflow runs automatically. Trigger it once manually to get an initial feed.
4. Your RSS URL: `https://<you>.github.io/<repo>/feed/geopolitics.xml`
5. Your viewer: `https://<you>.github.io/<repo>/`

## Local run

```bash
pip install -r requirements.txt
python scrape.py
```

## Notes

- `state/seen_guids.json` keeps a rolling window of the last 5 000 seen GUIDs to prevent unbounded growth.
- URL decoding uses `googlenewsdecoder` (pure computation). HTTP redirect follow is the fallback.
- The workflow only commits when the feed or state actually changed (no noisy empty commits).
