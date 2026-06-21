"""Orchestrates the local pipeline across all targets, then writes to DB.

Accumulates every site's deals into one master list, writes the JSON dump once
AFTER the loop (so sites append, never overwrite), and upserts in one batch.
"""
import asyncio
import json
import os
from dataclasses import asdict

import httpx

from config import LOCAL_URLS
from pipeline_local import fetch, clean_content, parse_deals
from database import Deal, save_deals

# Anchored to this file (not cwd) so the dump always lands in the scraper folder.
_DEBUG_PATH = os.path.join(os.path.dirname(__file__), "scraped_output_debug.json")


def dump_debug(deals: list[Deal]) -> None:
    """Write the standardized payload to disk for a human eyeball before it hits
    the DB — runs first, so we keep a record even if the upsert fails."""
    with open(_DEBUG_PATH, "w", encoding="utf-8") as f:
        json.dump([asdict(d) for d in deals], f, indent=2, ensure_ascii=False)
    print(f"[main] Wrote {len(deals)} deals -> {_DEBUG_PATH}")


async def main():
    all_deals: list[Deal] = []  # master accumulator across every target

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        for url in LOCAL_URLS:
            html = await fetch(url, client)
            if not html:
                print(f"[main] {url} -> unreachable, skipping")
                continue
            deals = await parse_deals(clean_content(html), url)
            print(f"[main] {url} -> {len(deals)} deals")
            all_deals.extend(deals)  # append, don't overwrite

    # File write + DB upsert happen ONCE, on the complete combined collection.
    dump_debug(all_deals)
    written = await save_deals(all_deals)
    print(f"[main] TOTAL combined: {len(all_deals)} deals | upserted: {written}")


if __name__ == "__main__":
    asyncio.run(main())
