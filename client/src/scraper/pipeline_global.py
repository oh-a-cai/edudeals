"""Brand discovery via SerpApi — finds an offer page per seed brand."""
import httpx

from config import SERPAPI_KEY, GLOBAL_BRANDS
from database import Deal


async def discover() -> list[Deal]:
    if not SERPAPI_KEY:
        print("[global] SERPAPI_KEY not set — skipping brand discovery.")
        return []

    deals: list[Deal] = []
    async with httpx.AsyncClient(timeout=20) as client:
        for brand in GLOBAL_BRANDS:
            params = {
                "engine": "google",
                "q": f"{brand} student discount",
                "api_key": SERPAPI_KEY,
                "num": 1,
            }
            try:
                r = await client.get("https://serpapi.com/search", params=params)
                r.raise_for_status()
                results = r.json().get("organic_results", [])
            except Exception as e:  # network / quota / parse — log and move on
                print(f"[global] {brand}: SERP query failed: {e}")
                continue

            if not results:
                print(f"[global] {brand}: no results")
                continue

            top = results[0]
            deals.append(Deal(
                brand=brand,
                description=top.get("snippet") or f"{brand} student discount",
                category="brand",
                redemption_url=top.get("link"),
            ))
            print(f"[global] {brand} -> {top.get('link')}")

    return deals
