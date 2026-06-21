"""Local static pages → semantic cleaning → LLM structural extraction.

We strip boilerplate, flatten the content to a text dump, then let an LLM pull
out merchants. This is layout-agnostic: it works whether names live in <h2>,
<h3>, table cells, or <div>s — no per-page tag conventions.
"""
import asyncio
import json
import random
import re
import unicodedata

import httpx
from bs4 import BeautifulSoup
from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel

from config import SCRAPERAPI_KEY, GEMINI_API_KEY
from database import Deal

# Smarter model, but free tier is ~1 RPM — hence the batch path (all pages in one
# call) so a full run stays under the limit.
_MODEL = "gemini-3.1-flash-lite"

# Per-page text cap inside a batch payload (keeps the combined prompt bounded).
# 50k holds the full curated GitHub lists without clipping trailing deals.
_BATCH_PAGE_CAP = 50_000


class DealBlock(BaseModel):
    """LLM output schema for one merchant (drives Gemini structured output).
    Flat — no scope/locality fields."""
    brand: str
    description: str
    discount_percent: str  # '' when none stated
    category: str          # e.g. 'Food and Drink', 'Retail', 'Services'
    redemption_url: str    # copied from the parent <scraped_site url='...'> tag
    expires_at: str        # ISO date ('2026-12-31') or '' when none stated


def slugify(name: str) -> str:
    """Brand name → URL-safe anchor slug, accents folded and specials stripped.
    'Bench Café • Pâtisserie' → 'bench-cafe-patisserie'."""
    ascii_name = (unicodedata.normalize("NFKD", name)
                  .encode("ascii", "ignore").decode("ascii"))
    return re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")

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


# Shared extraction rules for the batched prompt.
_RULES = (
    "Return one entry per MERCHANT only. For each merchant:\n"
    "- brand: the business name\n"
    "- description: the full offer text, keeping multi-item offers intact\n"
    "- discount_percent: e.g. '10%', or '' if no percentage is stated\n"
    "- category: e.g. 'Food and Drink', 'Retail', 'Services', 'Entertainment'\n"
    "- redemption_url: copy the exact URL from the parent <scraped_site> tag\n"
    "- expires_at: the offer's expiry date as 'YYYY-MM-DD', or '' if none stated\n"
    "Skip navigation, how-it-works steps, and section headers that aren't merchants.\n"
    "If a merchant or brand name cannot be conclusively determined from the "
    "surrounding text context for a specific discount record, DO NOT generate a "
    "fallback 'N/A' object. Omit the record from the output JSON array entirely.\n"
    "CRITICAL: Do not extract a merchant if the source text only mentions that a "
    "discount exists but fails to provide specific details about what the discount "
    "actually is (e.g., a percentage, a dollar amount, a free item, or clear "
    "promotional terms). If a merchant lacks explicit perk details, omit it from "
    "the JSON array entirely. Do not generate rows with generic descriptions like "
    "'Offers discounts' or null value fields.\n"
    "EXCEPTION: If the source text is clearly a flat directory, list, or menu of "
    "business specials (indicated by a sequence of merchant names followed "
    "immediately by concise values like '10% off' or 'BOGO'), these are "
    "HIGH-QUALITY records. You must map the line containing the company name to the "
    "'brand' key, and pair it with the subsequent discount line as the "
    "'description' and 'discount_percent'. Only enforce the strict vagueness filter "
    "to skip records when reading narrative news articles, blog posts, or editorial "
    "prose.\n"
)

_BATCH_PROMPT = (
    "You are receiving a combined payload of multiple scraped web pages, each "
    "enclosed in a <scraped_site url='...'> tag. Extract every discount and return "
    "a single, flat JSON array of raw deals. For each deal, set 'redemption_url' to "
    "the exact URL attribute copied from its parent <scraped_site> tag.\n"
    + _RULES + "\nPAGES:\n"
)


_MAX_RETRIES = 3


def _is_retryable(e: Exception) -> bool:
    """429 (rate limit) and 5xx (transient server) are worth retrying; 4xx auth/
    bad-request errors are not — retrying those just burns the same failure."""
    return isinstance(e, genai_errors.APIError) and (e.code == 429 or 500 <= e.code < 600)


async def _generate_json(contents: str, schema) -> list[dict]:
    """One Gemini call returning parsed JSON. Retries 429/5xx up to _MAX_RETRIES
    with exponential backoff + jitter; non-retryable or final failure bubbles up."""
    if not GEMINI_API_KEY:
        print("[local] GEMINI_API_KEY not set — cannot run LLM extraction.")
        return []
    client = genai.Client(api_key=GEMINI_API_KEY)
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            resp = await client.aio.models.generate_content(
                model=_MODEL,
                contents=contents,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=schema,
                ),
            )
            return json.loads(resp.text)
        except Exception as e:
            if not _is_retryable(e) or attempt == _MAX_RETRIES:
                raise  # non-retryable, or out of attempts -> let the trace surface
            delay = (2 ** attempt) * random.uniform(0.5, 1.5)
            print(f"[gemini] Encountered rate limit/server error. Retrying in "
                  f"{delay:.2f} seconds (Attempt {attempt}/{_MAX_RETRIES})...")
            await asyncio.sleep(delay)


async def extract_deals_llm_batch(pages: list[dict]) -> list[dict]:
    """Batch extraction: wrap each page in a <scraped_site> tag and parse all in
    ONE call. `pages` = [{"url": ..., "html_text": ...}, ...]."""
    if not pages:
        return []
    payload = "\n".join(
        f"<scraped_site url='{p['url']}'>\n{p['html_text'][:_BATCH_PAGE_CAP]}\n</scraped_site>"
        for p in pages
    )
    return await _generate_json(_BATCH_PROMPT + payload, list[DealBlock])


# Placeholder brand values the LLM emits when it can't identify a merchant —
# anonymous deals are useless, so we drop them before they reach the DB.
_BAD_BRANDS = {"n/a", "na", "none", "null", "unknown"}

# A concrete perk has at least one of: a number, a dollar sign, a percent, or a
# concise special term (free / BOGO / buy-one / half off|price / complimentary).
# We use this instead of a raw length cutoff because legit perks can be short
# ("Free Admission", "$5 off", "BOGO") — a <35-char rule would wrongly drop those
# while still missing long-but-vague text ("the shop offers discounts to all
# students who show a valid ID").
_PERK_SIGNAL = re.compile(
    r"\d|\$|%|\bfree\b|\bbogo\b|buy[\s-]?one|half[\s-]?(off|price)|complimentary",
    re.I,
)


def _is_low_quality(discount_percent: str | None, description: str) -> bool:
    """A deal is low-quality (drop it) only when it has NO explicit percent AND no
    concrete perk terms in the description — i.e. vague 'offers discounts' rows."""
    if discount_percent:
        return False  # explicit percent is itself a concrete perk
    return not _PERK_SIGNAL.search(description)


def _block_to_deal(b: dict) -> Deal | None:
    """Map one LLM block → Deal, applying all guards. Returns None to drop it.
    Pure (no network) so it's unit-testable."""
    brand = (b.get("brand") or "").strip()
    description = (b.get("description") or "").strip()
    # Drop null/empty/placeholder brands (N/A etc.) — anonymous deals are junk.
    if not brand or brand.lower() in _BAD_BRANDS or not description:
        return None  # brand/description are NOT NULL in the schema

    # redemption_url comes from the parent <scraped_site> tag. Without it we can't
    # dedupe (NULLs never conflict), so drop the row.
    base = (b.get("redemption_url") or "").strip()
    if not base:
        return None

    discount_percent = (b.get("discount_percent") or "").strip() or None
    # Drop vague no-detail rows (e.g. "offers discounts" with no % / $ / free).
    if _is_low_quality(discount_percent, description):
        return None

    # One directory page lists many merchants → all share the page URL. Append a
    # per-brand anchor so each row is unique and the upsert never collapses them.
    url = base if "#" in base else f"{base}#{slugify(brand)}"
    return Deal(
        brand=brand,
        description=description,
        discount_percent=discount_percent,
        category=(b.get("category") or "").strip().lower() or None,
        redemption_url=url,
        expires_at=(b.get("expires_at") or "").strip() or None,
    )


def _deals_from_llm_json(blocks: list[dict]) -> list[Deal]:
    """Map LLM blocks → Deals, dropping anything the guards reject."""
    return [d for b in blocks if (d := _block_to_deal(b))]


def page_text(html: str) -> str:
    """Raw HTML -> chrome-stripped, tag-flattened text ready for a batch payload."""
    return BeautifulSoup(clean_content(html), "html.parser").get_text("\n", strip=True)


async def parse_deals_batch(pages: list[dict]) -> list[Deal]:
    """Batch extraction: ONE LLM call across all pages. `pages` =
    [{"url": ..., "html_text": ...}, ...]. Each deal carries its page's URL."""
    blocks = await extract_deals_llm_batch(pages)
    deals = _deals_from_llm_json(blocks)
    print(f"[local] batch LLM extracted {len(deals)} merchants from {len(pages)} pages")
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

    # LLM JSON → Deal mapping (pure, no network): per-brand anchor appended to the
    # page URL, category lowercased, empty discount_percent/expires_at -> None,
    # junk rows dropped, and rows without a redemption_url dropped (can't dedupe).
    base = "https://x.test/d/"
    blocks = [
        {"brand": "Vendor One", "description": "5% off", "discount_percent": "5%",
         "category": "Food and Drink", "redemption_url": base, "expires_at": "2026-12-31"},
        {"brand": "Vendor Two", "description": "Free coffee", "discount_percent": "",
         "category": "Services", "redemption_url": base, "expires_at": ""},
        {"brand": "", "description": "no brand", "discount_percent": "",
         "category": "", "redemption_url": base},          # dropped (empty brand)
        {"brand": "N/A", "description": "anon deal", "discount_percent": "5%",
         "category": "Retail", "redemption_url": base},     # dropped (N/A placeholder)
        {"brand": "No URL", "description": "5% off", "discount_percent": "5%",
         "category": "Retail", "redemption_url": ""},       # dropped (no redemption_url)
        {"brand": "Twisted Palm Yogurt", "description": "offers discounts",
         "discount_percent": "", "category": "Food", "redemption_url": base},  # dropped (vague)
        {"brand": "City Museum", "description": "Free Admission",
         "discount_percent": "", "category": "Entertainment", "redemption_url": base},  # kept (free)
        {"brand": "Slice Co", "description": "BOGO", "discount_percent": "",
         "category": "Food", "redemption_url": base},       # kept (concise special)
    ]
    deals = _deals_from_llm_json(blocks)
    assert [d.brand for d in deals] == ["Vendor One", "Vendor Two", "City Museum", "Slice Co"], deals
    assert deals[0].redemption_url == "https://x.test/d/#vendor-one"
    assert deals[1].redemption_url == "https://x.test/d/#vendor-two"
    assert deals[0].category == "food and drink"
    assert deals[0].expires_at == "2026-12-31"
    assert deals[1].discount_percent is None and deals[1].expires_at is None  # '' -> None
    print("ok: LLM JSON drops empty/N/A/urlless brands + vague rows, keeps short perks")

    # Retry classifier: 429/5xx retryable, 4xx/other not.
    assert _is_retryable(genai_errors.APIError(429, {"message": "rate"}))
    assert _is_retryable(genai_errors.APIError(503, {"message": "down"}))
    assert not _is_retryable(genai_errors.APIError(400, {"message": "bad"}))
    assert not _is_retryable(ValueError("nope"))
    print("ok: retry classifier flags only 429/5xx")
