"""Orchestrates the scraper: curated + discovered URLs -> Gemini -> public.discounts.

Curated LOCAL_URLS and discovery-scout URLs are scraped, batched into ONE Gemini
call, then upserted into the single flat public.discounts table — no scope split.
scraped_output_debug.json keeps an on-disk copy for debugging.
"""
import asyncio
import json
import os
import re
from dataclasses import asdict

from urllib.parse import urlsplit

import httpx

from config import LOCAL_URLS, GITHUB_SEED_URLS
from pipeline_global import discover_local_directories, filter_directories
from pipeline_local import fetch, page_text, parse_deals_batch, parse_github_markdown
from database import Deal, save_deals

# Anchored to this file (not cwd) so the dump always lands in the scraper folder.
_DEBUG_PATH = os.path.join(os.path.dirname(__file__), "scraped_output_debug.json")

# Intent-driven seeds: find regional / campus student-deal directories, not
# individual brand offers.
SEED_QUERIES = [
    "site:.edu 'student discounts' OR 'campus perks' California",
    "downtown association 'student deals' OR 'local discounts'",
]


# Brand-name noise words stripped before comparison, so "Spotify" and "Spotify
# Premium Student Discount" collapse to the same key.
_BRAND_NOISE = re.compile(
    r"\b(premium|student|students|discount|discounts|offer|offers|deal|deals|for|the|pro|plan)\b")


def _norm_brand(name: str) -> str:
    """Brand name -> comparison key: noise words dropped, then alnum-only."""
    b = re.sub(r"[^a-z0-9]+", "", _BRAND_NOISE.sub("", name.lower()))
    return b or re.sub(r"[^a-z0-9]+", "", name.lower())  # all-noise -> full name


def _dedupe_key(d: Deal) -> tuple[str, str] | None:
    """(normalized brand, host). Collapses the same merchant listed twice on the
    same site (e.g. a product in both GitHub files) while KEEPING the same brand on
    different sites — Woodstock's in two cities, Spotify campus vs spotify.com — so
    we never delete a genuinely distinct deal. Null URL -> no key (passes through)."""
    if not d.redemption_url:
        return None
    return (_norm_brand(d.brand), urlsplit(d.redemption_url).netloc.lower())


def dedupe(deals: list[Deal]) -> list[Deal]:
    """Collapse rows for the same merchant on the same site, keeping the first seen.
    Null-URL rows pass through — they're dropped later at the save step anyway."""
    seen: set[tuple[str, str]] = set()
    out: list[Deal] = []
    for d in deals:
        key = _dedupe_key(d)
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        out.append(d)
    return out


def merge_sources(campus: list[Deal], github: list[Deal]) -> list[Deal]:
    """Dedupe within each source by (brand, host); across sources GitHub wins — if a
    brand exists in the GitHub lists, drop the campus rows for that same brand (the
    curated enterprise listing is preferred over a campus-specific one)."""
    github = dedupe(github)
    gh_brands = {_norm_brand(d.brand) for d in github}
    campus = [d for d in dedupe(campus) if _norm_brand(d.brand) not in gh_brands]
    return campus + github


def dump_debug(deals: list[Deal]) -> None:
    """Write the standardized payload to disk for a human eyeball before it hits
    the DB — runs first, so we keep a record even if the upsert fails."""
    with open(_DEBUG_PATH, "w", encoding="utf-8") as f:
        json.dump([asdict(d) for d in deals], f, indent=2, ensure_ascii=False)
    print(f"[main] Wrote {len(deals)} deals -> {_DEBUG_PATH}")


async def collect_global_urls() -> list[str]:
    """Run the discovery scout over all seed queries, filter, dedupe."""
    found: list[str] = []
    for query in SEED_QUERIES:
        found.extend(await discover_local_directories(query))

    urls = filter_directories(found)
    print(f"[main] discovery -> {len(urls)} candidate directories")
    return urls


async def collect_pages(urls: list[str], client: httpx.AsyncClient) -> list[dict]:
    """Fetch (native -> ScraperAPI) each URL and flatten to text, building the
    batch aggregator payload: [{"url": url, "html_text": text}, ...]."""
    pages: list[dict] = []
    for url in urls:
        html = await fetch(url, client)
        if not html:
            print(f"[main] {url} -> unreachable, skipping")
            continue
        pages.append({"url": url, "html_text": page_text(html)})
    return pages


async def main():
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        local_pages = await collect_pages(LOCAL_URLS, client)
        # Raw markdown lists: native fetch, same {url, html_text} shape. page_text's
        # HTML cleaner is a harmless passthrough on tag-free markdown.
        github_pages = await collect_pages(GITHUB_SEED_URLS, client)
        global_urls = await collect_global_urls()
        global_pages = await collect_pages(global_urls, client)

    # Campus HTML is messy -> Gemini. The curated GitHub lists are clean structured
    # markdown -> a deterministic regex parser (100% recall, no quota, no LLM call).
    campus_deals = await parse_deals_batch(local_pages + global_pages)
    github_deals = parse_github_markdown(github_pages)
    # Within-source dedupe + GitHub-wins on cross-source brand collisions.
    # (Non-USD region-locked deals were already dropped at parse time.)
    all_deals = merge_sources(campus_deals, github_deals)

    dump_debug(all_deals)

    written = await save_deals(all_deals)
    print(f"[main] discounts upserted: {written} | debug json: {len(all_deals)} "
          f"(campus {len(campus_deals)} + github {len(github_deals)}, deduped)")


if __name__ == "__main__":
    asyncio.run(main())
