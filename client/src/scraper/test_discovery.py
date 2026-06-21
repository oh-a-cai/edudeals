"""Trigger the discovery scout (READ-ONLY — no DB write) and print the candidate
directory URLs it finds for each seed query, plus the filtered shortlist.

Run: python test_discovery.py

Use this to audit what discovery surfaces before letting main.py scrape + save.
"""
import asyncio

from pipeline_global import discover_local_directories, filter_directories
from main import SEED_QUERIES


async def run():
    found: list[str] = []
    for query in SEED_QUERIES:
        print(f"\n[seed] {query}")
        urls = await discover_local_directories(query)
        for u in urls:
            print(f"   {u}")
        found.extend(urls)

    kept = filter_directories(found)
    print(f"\n===== DISCOVERY SUMMARY =====")
    print(f"raw results : {len(found)}")
    print(f"after filter: {len(kept)} (global brand/social pages removed)")
    for u in kept:
        print(f"  -> {u}")


if __name__ == "__main__":
    asyncio.run(run())
