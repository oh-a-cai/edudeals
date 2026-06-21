"""Local static pages → semantic cleaning → LLM structural extraction.

We strip boilerplate, flatten the content to a text dump, then let an LLM pull
out merchants. This is layout-agnostic: it works whether names live in <h2>,
<h3>, table cells, or <div>s — no per-page tag conventions.
"""
import json
import re
import unicodedata

import httpx
from bs4 import BeautifulSoup
from google import genai
from google.genai import types
from pydantic import BaseModel

from config import LOCAL_URLS, SCRAPERAPI_KEY, GEMINI_API_KEY
from database import Deal


class DealBlock(BaseModel):
    """LLM output schema for one merchant (drives Gemini structured output)."""
    brand: str
    description: str
    discount_percent: str  # '' when none stated
    category: str          # e.g. 'Food and Drink', 'Retail', 'Services'
    anchor_slug: str       # slugified brand name


def slugify(name: str) -> str:
    """Brand name → URL-safe anchor slug, accents folded and specials stripped.
    'Bench Café • Pâtisserie' → 'bench-cafe-patisserie'."""
    ascii_name = (unicodedata.normalize("NFKD", name)
                  .encode("ascii", "ignore").decode("ascii"))
    return re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")


def deal_url(base_url: str, brand: str) -> str:
    """Local directories list many merchants on one page. Append a per-brand
    anchor fragment so each row gets a unique, non-null redemption_url and
    discounts_url_unique never collides on upsert."""
    return f"{base_url}#{slugify(brand)}"

# Tags that are never page content — removed wholesale.
_NOISE_TAGS = ["script", "style", "nav", "footer", "header",
               "aside", "form", "noscript", "svg", "iframe"]

# id/class substrings that flag chrome even on generic <div>/<section> nodes.
_NOISE_HINTS = ["sidebar", "menu", "footer", "header", "nav",
                "cookie", "banner", "social", "share", "newsletter", "comment"]

_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) "
                     "Chrome/125.0.0.0 Safari/537.36"}


async def _via_proxy(url: str, client: httpx.AsyncClient) -> str | None:
    """Fetch through ScraperAPI's egress — used when the direct request is blocked
    (403) or never connects (timeout / IP-level block). SerpApi can't do this:
    it only scrapes search engines, not arbitrary URLs."""
    if not SCRAPERAPI_KEY:
        print(f"[local] cannot proxy {url}: SCRAPERAPI_KEY not set in .env")
        return None
    print(f"[local] routing {url} via ScraperAPI proxy (premium/us)")
    try:
        # premium=true → residential/carrier IPs (datacenter IPs get blacklisted
        # by hosts like Davis); country_code=us pins routing to US exit nodes.
        # This path only runs for already-failing hosts, so the extra credits
        # are spent only when a plain fetch couldn't connect.
        r = await client.get("https://api.scraperapi.com",
                             params={
                                 "api_key": SCRAPERAPI_KEY,
                                 "url": url,
                                 "premium": "true",
                                 "country_code": "us",
                             },
                             timeout=70)
        r.raise_for_status()
        return r.text
    except Exception as e:
        print(f"[local] proxy fetch failed for {url}: {type(e).__name__}: {e}")
        return None


async def fetch(url: str, client: httpx.AsyncClient) -> str | None:
    """Fetch via httpx. Fall back to the proxy on a 403 or any connection failure
    (ConnectTimeout / network error), e.g. when the host blocks our IP."""
    try:
        r = await client.get(url, headers=_UA)
    except httpx.TransportError as e:
        # ConnectTimeout, ConnectError, ReadTimeout, etc. all subclass this.
        print(f"[local] direct fetch failed for {url}: {type(e).__name__} — trying proxy")
        return await _via_proxy(url, client)

    if r.status_code == 403:
        print(f"[local] 403 on {url} — trying proxy")
        return await _via_proxy(url, client)

    try:
        r.raise_for_status()
    except httpx.HTTPStatusError as e:
        print(f"[local] HTTP {r.status_code} for {url}: {e}")
        return None
    return r.text


def clean_content(html: str) -> str:
    """Generalized semantic cleaner — no page-specific selectors.

    1. Drop non-content tags (nav/footer/script/style/aside/...).
    2. Drop nodes whose id/class hints at chrome (sidebar, banner, ...).
    3. Isolate the main content region (main → article → body), strongest first.
    4. Return the streamlined markup so the LLM still sees headings and lists.
    """
    soup = BeautifulSoup(html, "html.parser")

    # 1. Isolate the main content region FIRST, by semantic strength. Doing this
    #    before noise removal means we can never decompose an ancestor of the
    #    content — page <body> classes often contain tokens like "menu"/"header".
    container = soup.find("main") or soup.find("article") or soup.body or soup

    # 2. Whole-tag noise, scoped to the container.
    for tag in container(_NOISE_TAGS):
        tag.decompose()

    # 3. Hinted-chrome noise, scoped to the container. Snapshot first; a node may
    #    already be detached (attrs is None) if an ancestor was decomposed.
    for node in container.find_all(attrs={"class": True}) + container.find_all(id=True):
        if node.attrs is None:
            continue
        ident = (" ".join(node.get("class", [])) + " " + (node.get("id") or "")).lower()
        if any(hint in ident for hint in _NOISE_HINTS):
            node.decompose()

    # 4. Streamlined markup (tags retained for structure).
    return container.decode().strip()


_LLM_PROMPT = (
    "You extract student/local discounts from the text of a deals directory page.\n"
    "Return one entry per MERCHANT only. For each merchant:\n"
    "- brand: the business name\n"
    "- description: the full offer text, keeping multi-item offers intact\n"
    "- discount_percent: e.g. '10%', or '' if no percentage is stated\n"
    "- category: e.g. 'Food and Drink', 'Retail', 'Services', 'Entertainment'\n"
    "- anchor_slug: the brand name lowercased and hyphenated\n"
    "Skip navigation, how-it-works steps, and section headers that aren't merchants.\n\n"
    "PAGE TEXT:\n"
)


async def extract_deals_llm(text: str) -> list[dict]:
    """Send the cleaned page text to Gemini, get back structured deal blocks.
    Returns [] (never raises) if the key is missing or the call fails."""
    if not GEMINI_API_KEY:
        print("[local] GEMINI_API_KEY not set — cannot run LLM extraction.")
        return []
    client = genai.Client(api_key=GEMINI_API_KEY)
    try:
        resp = await client.aio.models.generate_content(
            model="gemini-2.5-flash-lite",  # this key has free-tier quota here
            contents=_LLM_PROMPT + text[:30_000],  # cap tokens for the flash tier
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=list[DealBlock],
            ),
        )
        return json.loads(resp.text)
    except Exception as e:
        print(f"[local] LLM extraction failed: {type(e).__name__}: {e}")
        return []


def _deals_from_llm_json(blocks: list[dict], source_url: str) -> list[Deal]:
    """Map LLM blocks → Deal rows. Pure (no network) so it's unit-testable.
    Builds redemption_url from the base URL + a re-slugified anchor."""
    deals: list[Deal] = []
    for b in blocks:
        brand = (b.get("brand") or "").strip()
        description = (b.get("description") or "").strip()
        if not brand or not description:
            continue  # brand/description are NOT NULL in the schema
        slug = slugify(b.get("anchor_slug") or brand)  # re-slug to guarantee URL-safe
        deals.append(Deal(
            brand=brand,
            description=description,
            discount_percent=(b.get("discount_percent") or "").strip() or None,
            category=(b.get("category") or "").strip().lower() or None,
            redemption_url=f"{source_url}#{slug}",
        ))
    return deals


async def parse_deals(cleaned_markup: str, source_url: str) -> list[Deal]:
    """Layout-agnostic extraction: flatten the cleaned markup to text, hand it to
    the LLM, map the structured result to Deal rows. No tag conventions assumed."""
    text = BeautifulSoup(cleaned_markup, "html.parser").get_text("\n", strip=True)
    blocks = await extract_deals_llm(text)
    deals = _deals_from_llm_json(blocks, source_url)
    print(f"[local] LLM extracted {len(deals)} merchants from {source_url}")
    return deals


async def extract() -> list[Deal]:
    if not LOCAL_URLS:
        print("[local] No LOCAL_URLS configured — skipping.")
        return []

    deals: list[Deal] = []
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        for url in LOCAL_URLS:
            html = await fetch(url, client)
            if not html:
                continue
            cleaned = clean_content(html)
            deals.extend(await parse_deals(cleaned, url))

    return deals


# ── No-network self-checks ─────────────────────────────────────────────────────
if __name__ == "__main__":
    # slugger: accents folded, specials stripped
    assert slugify("Test Café • Bakery") == "test-cafe-bakery"
    assert slugify("Pizza Place & Co.") == "pizza-place-co"
    print("ok: slugify folds accents + strips specials")

    # cleaner: keeps content, drops chrome
    sample = """
    <html><body>
      <nav class="menu">HOME ABOUT</nav>
      <div id="sidebar">ads ads ads</div>
      <article><h2>Mock Vendor</h2><p>Discount: 5% off</p></article>
      <footer>copyright</footer>
      <script>tracking()</script>
    </body></html>
    """
    out = clean_content(sample)
    assert "Mock Vendor" in out and "5% off" in out, out
    assert "HOME ABOUT" not in out and "ads ads" not in out, out
    assert "tracking()" not in out and "copyright" not in out, out
    print("ok: cleaner keeps content, strips nav/sidebar/footer/script")

    # LLM JSON → Deal mapping (pure, no network): URL built from base + slug,
    # category lowercased, empty discount_percent -> None, junk rows dropped.
    blocks = [
        {"brand": "Vendor One", "description": "5% off", "discount_percent": "5%",
         "category": "Food and Drink", "anchor_slug": "vendor-one"},
        {"brand": "Vendor Two", "description": "Free coffee", "discount_percent": "",
         "category": "Services", "anchor_slug": "vendor two"},  # bad slug -> re-slugged
        {"brand": "", "description": "no brand", "discount_percent": "",
         "category": "", "anchor_slug": ""},  # dropped (NOT NULL)
    ]
    deals = _deals_from_llm_json(blocks, "https://x.test/d/")
    assert [d.brand for d in deals] == ["Vendor One", "Vendor Two"], deals
    assert deals[0].redemption_url == "https://x.test/d/#vendor-one"
    assert deals[1].redemption_url == "https://x.test/d/#vendor-two"  # re-slugged
    assert deals[0].category == "food and drink"
    assert deals[1].discount_percent is None  # '' -> None
    print("ok: LLM JSON maps to Deal rows with clean URLs + nullable fields")
