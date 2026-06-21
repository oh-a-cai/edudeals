"""Discovery scout via SerpApi.

- discover_local_directories(query): search → candidate directory URLs
- filter_directories(urls): drop global brand/landing/social pages
"""
import httpx

from config import SERPAPI_KEY

# Global brand / aggregator / social domains — these are landing pages, not the
# city/campus directories we want, so the scout drops them.
_SKIP_DOMAINS = (
    "apple.com", "nike.com", "spotify.com", "amazon.com", "adobe.com",
    "samsung.com", "microsoft.com", "bestbuy.com", "target.com",
    "unidays.com", "studentbeans.com", "myunidays.com",
    "youtube.com", "facebook.com", "instagram.com", "twitter.com",
    "reddit.com", "linkedin.com", "tiktok.com", "pinterest.com",
)

# Editorial/listicle path segments — these are articles, not deal directories.
_DENY_PATHS = (
    "/blog/", "/news/", "/press/", "/events/", "/event/", "/article/",
    "/articles/", "/story/", "/stories/", "/learn/", "/guide/", "/guides/",
    "/post/", "/posts/", "/2019/", "/2020/", "/2021/", "/2022/", "/2023/",
    "/2024/", "/2025/", "/2026/",  # dated paths are almost always blog posts
)

# High-intent keywords — a real directory URL almost always contains one.
_INTENT_KEYWORDS = (
    "discount", "perks", "deals", "benefits", "student", "merchant",
)


def _is_high_intent(url: str) -> bool:
    """A clean directory candidate: no editorial path, and at least one
    high-intent keyword somewhere in the URL."""
    low = url.lower()
    if any(seg in low for seg in _DENY_PATHS):
        return False
    return any(kw in low for kw in _INTENT_KEYWORDS)


async def discover_local_directories(query: str) -> list[str]:
    """Run one search query and return the unique result URLs (directory
    candidates). Returns [] (never raises) on missing key / quota / network."""
    if not SERPAPI_KEY:
        print("[scout] SERPAPI_KEY not set — skipping discovery.")
        return []

    params = {"engine": "google", "q": query, "api_key": SERPAPI_KEY, "num": 10}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get("https://serpapi.com/search", params=params)
            r.raise_for_status()
            results = r.json().get("organic_results", [])
    except Exception as e:
        print(f"[scout] query failed ({query!r}): {type(e).__name__}: {e}")
        return []

    urls: list[str] = []
    for item in results:
        link = item.get("link")
        if link and link not in urls:
            urls.append(link)
    print(f"[scout] {query!r} -> {len(urls)} urls")
    return urls


def filter_directories(urls: list[str]) -> list[str]:
    """Keep only clean directory candidates: drop global brand/social domains and
    editorial pages, require a high-intent keyword. Dedupe, preserve order, and
    log how many noisy links were skipped."""
    kept: list[str] = []
    skipped = 0
    for u in urls:
        if any(domain in u for domain in _SKIP_DOMAINS) or not _is_high_intent(u):
            skipped += 1
            continue
        if u not in kept:
            kept.append(u)
    print(f"[scout] filter: kept {len(kept)}, skipped {skipped} noisy links")
    return kept
