"""Orchestrates the scraper: curated + discovered URLs -> Gemini -> public.discounts.

Curated LOCAL_URLS and discovery-scout URLs are scraped, batched into ONE Gemini
call, then upserted into the single flat public.discounts table — no scope split.
scraped_output_debug.json keeps an on-disk copy for debugging.
"""
import asyncio
import json
import os
from dataclasses import asdict

import httpx

from config import LOCAL_URLS, GITHUB_SEED_URLS
from pipeline_global import discover_local_directories, filter_directories
from pipeline_local import fetch, page_text, parse_deals_batch
from database import Deal, save_deals

# Anchored to this file (not cwd) so the dump always lands in the scraper folder.
_DEBUG_PATH = os.path.join(os.path.dirname(__file__), "scraped_output_debug.json")

# Intent-driven seeds: find regional / campus student-deal directories, not
# individual brand offers.
SEED_QUERIES = [
    "site:.edu 'student discounts' OR 'campus perks' California",
    "downtown association 'student deals' OR 'local discounts'",
]


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

    # ONE Gemini call for every page (stays under the ~1 RPM limit of the model).
    all_deals = await parse_deals_batch(local_pages + github_pages + global_pages)

    dump_debug(all_deals)

    written = await save_deals(all_deals)
    print(f"[main] discounts upserted: {written} | debug json: {len(all_deals)}")


if __name__ == "__main__":
    asyncio.run(main())
