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
from datetime import date

import httpx
from urllib.parse import urlsplit
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
    blocks = []
    for p in pages:
        # Curated GitHub lists are dense and trustworthy — never clip them, or we
        # lose trailing deals. HTML pages still get capped to bound the payload.
        text = p["html_text"]
        if "githubusercontent.com" not in p["url"]:
            text = text[:_BATCH_PAGE_CAP]
        blocks.append(f"<scraped_site url='{p['url']}'>\n{text}\n</scraped_site>")
    return await _generate_json(_BATCH_PROMPT + "\n".join(blocks), list[DealBlock])


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


def _is_expired(expires_at: str) -> bool:
    """True only if expires_at is a valid date strictly before today. Unparseable
    dates are kept (don't drop a good deal over a format quirk)."""
    try:
        return date.fromisoformat(expires_at) < date.today()
    except ValueError:
        return False


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
        print(f"[Filter] Skipped no-signal deal: {brand}")
        return None

    # Drop deals that have already lapsed — a stale row is worse than no row.
    expires_at = (b.get("expires_at") or "").strip() or None
    if expires_at and _is_expired(expires_at):
        print(f"[Filter] Skipped expired deal: {brand}")
        return None

    # Drop region-locked foreign-currency prices (not real US student deals).
    if is_non_usd(description):
        print(f"[Filter] Skipped non-USD deal: {brand}")
        return None

    # One directory page lists many merchants → all share the page URL. Append a
    # per-brand anchor so each row is unique and the upsert never collapses them.
    url = base if "#" in base else f"{base}#{slugify(brand)}"
    url = localize_url(url)  # remap known foreign locales (e.g. /in-en/ -> /us/)
    if is_foreign_url(url):
        print(f"[Filter] Skipped non-US deal: {brand}")
        return None
    tags = canonical_tags(b.get("category"), description)
    return Deal(
        brand=brand,
        description=description,
        discount_percent=discount_percent,
        category=tags[0],
        tags=tags,
        redemption_url=url,
        expires_at=expires_at,
        school=school_for(url),
    )


def _deals_from_llm_json(blocks: list[dict]) -> list[Deal]:
    """Map LLM blocks → Deals, dropping anything the guards reject."""
    return [d for b in blocks if (d := _block_to_deal(b))]


# ── Deterministic parsers for curated GitHub markdown lists ─────────────────────
# These files are clean, pre-curated structured markdown, so regex beats an LLM:
# 100% recall, zero quota, no model variance. We skip the no-signal guard here —
# by construction every row is a real, verified deal, and many are perks without a
# % or $ ("Lifetime Pro", "Annual Subscription") that the guard would wrongly drop.

_MD_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")  # [text](url)


# Non-USD currency amounts. Only INR (INR / Rs / ₹) appears in the curated lists.
# Such offers are region-locked (e.g. India Spotify) and aren't real US student
# prices, so we drop them rather than show a misleading converted figure.
_NON_USD_RE = re.compile(r"(?:₹|\bINR|\bRs\.?)\s?\d", re.I)


def is_non_usd(text: str) -> bool:
    """True if the offer is priced in a non-USD currency we don't localize."""
    return bool(_NON_USD_RE.search(text))


# Foreign-region indicators -> drop (so we never prioritize foreign pricing).
# Path hints match anywhere in the URL; TLDs are matched against the host so we
# don't false-positive on '.info'/'.industries' etc.
_FOREIGN_PATH_HINTS = ("/in-en/", "/uk/", "/ca/", "/au/")
_FOREIGN_TLDS = (".in", ".co.uk")

# Known foreign locale segments we can safely remap to the US storefront instead
# of dropping — keeps the deal, fixes the link (e.g. Spotify /in-en/ -> /us/).
_LOCALE_REMAP = {"/in-en/": "/us/"}


def localize_url(url: str) -> str:
    """Rewrite a known foreign locale path to its US equivalent (English/US)."""
    for foreign, us in _LOCALE_REMAP.items():
        url = url.replace(foreign, us)
    return url


def is_foreign_url(url: str) -> bool:
    """True if the URL points at a non-US storefront (host TLD or locale path)."""
    host = urlsplit(url if "//" in url else "//" + url).netloc.lower()
    if host.endswith(_FOREIGN_TLDS):
        return True
    return any(hint in url.lower() for hint in _FOREIGN_PATH_HINTS)


# Curated source-host -> school abbreviation. Hosts not listed here aren't a known
# campus, so school_for() labels them 'All' (a general/non-campus offer).
_SCHOOL_BY_HOST = {
    "downtownberkeley.com": "UCB",
    "davisdowntown.com": "UCD",
    "downtownsantacruz.com": "UCSC",
    "sjsu.edu": "SJSU",
    "ucsd.edu": "UCSD",
    "ucsf.edu": "UCSF",
    "fresnocitycollege.edu": "FCC",
    "frc.edu": "FRC",
    "northcentralcollege.edu": "NCC",
    "ucr.edu": "UCR",
    "uoregon.edu": "UO",
}

# GitHub-list deals aren't tied to a campus — they're national/online offers.
_ONLINE_SCHOOL = "All"


# Canonical tag vocabulary — kept small and short. A deal can carry several tags;
# we map the source's free-form category + description onto this fixed set so the
# stored vocabulary stays low-cardinality instead of the dozens of raw labels.
_TAG_KEYWORDS = {
    "Food & Drink": ("food", "drink", "restaurant", "cafe", "coffee", "pizza",
                     "bakery", "dining", "bar", "grill", "kitchen", "yogurt",
                     "ice cream", "tea", "bagel", "sandwich", "snack", "eatery", "brew"),
    "Retail": ("retail", "shop", "shopping", "store", "clothing", "apparel",
               "boutique", "fashion", "jewelry", "gift", "shoe", "eyewear",
               "book", "vintage", "electronics"),
    "Services": ("service", "salon", "repair", "automotive", "cleaning", "tax",
                 "translation", "printing", "barber", "hair", "laundry", "legal"),
    "Entertainment": ("entertainment", "theater", "theatre", "museum", "movie",
                      "film", "game", "gaming", "aquarium", "bowling", "tour",
                      "arcade", "concert", "event", "art",
                      "music", "spotify", "audio", "song", "vinyl", "record"),
    "Education": ("education", "learn", "course", "study", "certification",
                  "tutoring", "academic", "exam", "class"),
    "Tech & Software": ("software", "app", "productivity", "note", "password",
                        "survey", "editor", "saas", "tool", "subscription",
                        "license", "mobile", "marketing", "analytics", "security",
                        "privacy", "social", "collaboration",
                        "cloud", "hosting", "server", "domain", "infrastructure",
                        "vps", "storage", "database",
                        "developer", "develop", "git", "code", "coding", "api",
                        "programming", "ide", "devops", "sdk", "repo", "crash"),
    "Design": ("design", "graphic", "icon", "illustration", "creative", "photo",
               "video", "flowchart", "prototype", "diagram"),
    "Health & Wellness": ("health", "wellness", "fitness", "gym", "yoga",
                          "pilates", "massage", "spa", "nutrition", "dental",
                          "medical", "clinic", "meditation"),
    "Travel": ("travel", "hotel", "flight", "airline", "transport", "rental",
               "parking", "lodging", "trip"),
}
# 9 tags above + the "Other" fallback = a 10-label universal vocabulary. Separator
# style ("Food & Drink" / "Food and Drink" / "Food, Retail") never matters: we
# keyword-match the raw text, so comma/&/and lists all resolve to the same tags.

# Word-boundary match with optional common suffix (plural/-ing/-er/-ment) so
# "learn" hits "Learning" and "develop" hits "developer/development" — while the
# leading \b still avoids "bar" inside "library" or "app" inside "happy".
_TAG_RE = {
    tag: re.compile(
        r"\b(?:" + "|".join(re.escape(k) for k in kws) + r")(?:s|ing|er|ers|ment)?\b",
        re.I)
    for tag, kws in _TAG_KEYWORDS.items()
}


def canonical_tags(raw: str | None, description: str = "") -> list[str]:
    """Map a free-form category + description onto the canonical tag set. Tags from
    the category come first (so tags[0] is the best primary), then any extra tags
    the description implies. Falls back to the cleaned raw label if nothing matches."""
    raw_tags = [t for t, rx in _TAG_RE.items() if rx.search(raw or "")]
    desc_tags = [t for t, rx in _TAG_RE.items() if rx.search(description)]
    tags = raw_tags + [t for t in desc_tags if t not in raw_tags]
    return tags or ["Other"]  # unmatched -> single catch-all (keeps vocab bounded)


def school_for(url: str) -> str:
    """Friendly school label from the deal's host. Known campus sources map to a
    curated abbreviation; anything else is a general/non-campus source -> 'All'."""
    host = urlsplit(url if "//" in url else "//" + url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    for frag, name in _SCHOOL_BY_HOST.items():
        if frag in host:
            return name
    return _ONLINE_SCHOOL  # not a known campus (e.g. secretdc.com) -> 'All'


def _unescape_md(s: str) -> str:
    """Drop backslash escapes markdown uses for literals, e.g. '\\$200' -> '$200'."""
    return re.sub(r"\\([$|*_`~])", r"\1", s).strip()


def _md_deal(brand: str, url: str, description: str, category: str | None = None) -> Deal | None:
    """Build a Deal from a curated row. The product's own link is the redemption
    URL (each is unique), so no anchor fragment is needed."""
    brand = _unescape_md(brand)
    description = _unescape_md(description)
    if not brand or brand.lower() in _BAD_BRANDS or not description or not url.strip():
        return None
    if is_non_usd(description):  # region-locked foreign price, not a US deal
        print(f"[Filter] Skipped non-USD deal: {brand}")
        return None
    url = localize_url(url.strip())  # remap known foreign locales (e.g. /in-en/ -> /us/)
    if is_foreign_url(url):
        print(f"[Filter] Skipped non-US deal: {brand}")
        return None
    tags = canonical_tags(category, description)
    return Deal(
        brand=brand,
        description=description,
        category=tags[0],
        tags=tags,
        redemption_url=url,
        school=_ONLINE_SCHOOL,
    )


def parse_markdown_deals(text: str) -> list[Deal]:
    """Extract deals from both curated layouts in one pass:
    - pipe table:  | [Brand](url) | Offer | Type |
    - bullet list: - [Brand](url) - description
    A line only matches one shape, so running both and concatenating is safe.
    Bullet lists carry no per-row type, so the current `##` section heading is used
    as their category (e.g. '## Design & Creative' -> Design)."""
    deals: list[Deal] = []
    section: str | None = None
    for raw in text.splitlines():
        line = raw.strip()

        if line.startswith("#"):  # section heading -> category for following bullets
            section = line.lstrip("#").strip()

        elif line.startswith("|"):  # table row
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) < 2:
                continue
            m = _MD_LINK.search(cells[0])
            if not m:  # header / separator / unlinked row
                continue
            cat = cells[2] if len(cells) > 2 else section  # Type cell, else section
            d = _md_deal(m.group(1), m.group(2), cells[1], cat)
            if d:
                deals.append(d)

        elif line.startswith("- ") or line.startswith("* "):  # bullet row
            body = line[2:].strip()
            m = _MD_LINK.match(body)
            if not m:
                continue
            description = body[m.end():].lstrip(" -–—:").strip()
            d = _md_deal(m.group(1), m.group(2), description, section)
            if d:
                deals.append(d)

    return deals


def parse_github_markdown(pages: list[dict]) -> list[Deal]:
    """Deterministic (no-LLM) extraction for the curated GitHub seed lists.
    `pages` = [{"url": ..., "html_text": ...}, ...]."""
    deals: list[Deal] = []
    for p in pages:
        found = parse_markdown_deals(p["html_text"])
        print(f"[github] {p['url'].rsplit('/', 1)[-1]} -> {len(found)} deals (regex)")
        deals.extend(found)
    return deals


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
    assert deals[0].category == "Food & Drink" and deals[0].tags == ["Food & Drink"]
    assert deals[0].expires_at == "2026-12-31"
    assert deals[1].discount_percent is None and deals[1].expires_at is None  # '' -> None
    print("ok: LLM JSON drops empty/N/A/urlless brands + vague rows, keeps short perks")

    # Freshness guard: past expiry dropped, future/empty/garbage kept.
    assert _is_expired("2020-01-01")
    assert not _is_expired("2099-12-31")
    assert not _is_expired("whenever")  # unparseable -> keep
    fresh = _deals_from_llm_json([
        {"brand": "Stale Co", "description": "20% off", "discount_percent": "20%",
         "category": "Retail", "redemption_url": base, "expires_at": "2020-01-01"},  # dropped
        {"brand": "Future Co", "description": "20% off", "discount_percent": "20%",
         "category": "Retail", "redemption_url": base, "expires_at": "2099-12-31"},  # kept
    ])
    assert [d.brand for d in fresh] == ["Future Co"], fresh
    print("ok: freshness guard drops lapsed deals, keeps future/unparseable")

    # Markdown parsers: pipe table + bullet list, skip headers/separators, unescape.
    md = """
| Product | Offer Benefits | Type |
|:--------|:---------------|:-----|
| [Notion Pro](https://notion.so/edu) | Notion Pro for lifetime for students | Note Taking |
| [Azure](https://azure.com/students) | 25+ services + \\$100 in credit | Cloud |
| Plain Header Row | no link here | skip |
- [Figma](https://figma.com/education) - Free Professional plan for students
- [Wix](https://wix.com/students) — 50% off Yearly Premium
* not a link bullet
"""
    mdeals = parse_markdown_deals(md)
    assert [d.brand for d in mdeals] == ["Notion Pro", "Azure", "Figma", "Wix"], mdeals
    assert mdeals[0].redemption_url == "https://notion.so/edu"      # product url, no #anchor
    assert mdeals[0].description == "Notion Pro for lifetime for students"  # kept (no signal)
    assert mdeals[1].description == "25+ services + $100 in credit"  # \$ unescaped
    assert mdeals[1].category == "Tech & Software" and "Tech & Software" in mdeals[1].tags
    assert mdeals[2].description == "Free Professional plan for students"
    assert mdeals[3].description == "50% off Yearly Premium"         # em-dash separator stripped
    print("ok: markdown parser reads tables + bullets at full recall, no LLM")

    # Currency: flag non-USD (INR/Rs/₹) offers; plain USD/percent untouched.
    assert is_non_usd("as low as INR66/month")
    assert is_non_usd("Learn Rs 700 at Udemy")
    assert is_non_usd("free trial and ₹79.00/month after")
    assert not is_non_usd("10% off and a $5 deal")
    assert not _md_deal("Spotify IN", "https://spotify.com", "as low as INR66/month")  # dropped
    print("ok: non-USD (INR) offers flagged and dropped")

    # Region: foreign TLD/locale URLs dropped, /in-en/ remapped to /us/, .info safe.
    assert localize_url("https://www.spotify.com/in-en/student/") == "https://www.spotify.com/us/student/"
    assert is_foreign_url("https://www.amazon.in/b?node=1")
    assert is_foreign_url("https://shop.co.uk/x") and is_foreign_url("https://s.com/uk/x")
    assert not is_foreign_url("https://www.spotify.com/us/student/")
    assert not is_foreign_url("https://berlin.info/students")  # .in must not match .info
    assert _md_deal("Spotify", "https://www.spotify.com/in-en/student/", "50% off") \
        .redemption_url == "https://www.spotify.com/us/student/"   # localized, kept
    assert not _md_deal("AmazonIN", "https://www.amazon.in/x", "10% off")  # foreign, dropped
    print("ok: region filter drops foreign URLs, remaps /in-en/ -> /us/")

    # School tag: curated campus hosts -> abbreviation, everything else -> 'All'.
    assert school_for("https://sfs.ucsd.edu/campus-cards/x#a") == "UCSD"
    assert school_for("https://www.downtownberkeley.com/student-discounts/#b") == "UCB"
    assert school_for("https://secretdc.com/deals#c") == "All"  # non-campus -> All
    assert _md_deal("Figma", "https://figma.com/edu", "Free").school == "All"
    campus = _deals_from_llm_json([{"brand": "Cafe", "description": "10% off",
        "discount_percent": "10%", "category": "Food",
        "redemption_url": "https://www.downtownberkeley.com/student-discounts/"}])
    assert campus[0].school == "UCB", campus
    print("ok: school tag set from source host (campus abbr / All)")

    # Canonical tags: small vocabulary, multiple per deal, category = primary.
    assert canonical_tags("Food and Drink", "10% off pizza") == ["Food & Drink"]
    yoga = canonical_tags("Services", "yoga membership 10% off")
    assert yoga == ["Services", "Health & Wellness"], yoga          # multi-tag
    cloud = canonical_tags("Cloud", "Free hosting and domain for developers")
    assert cloud == ["Tech & Software"], cloud  # cloud/hosting/dev all one tag now
    assert canonical_tags("Zxqwv Nonsense", "") == ["Other"]  # unmatched -> Other
    assert canonical_tags("", "") == ["Other"]
    assert canonical_tags("Learning & Resources", "") == ["Education"]  # -ing suffix
    assert not _TAG_RE["Food & Drink"].search("library bartender")     # no false 'bar'
    print("ok: canonical tags reduce vocabulary, allow multiple, set primary")

    # Retry classifier: 429/5xx retryable, 4xx/other not.
    assert _is_retryable(genai_errors.APIError(429, {"message": "rate"}))
    assert _is_retryable(genai_errors.APIError(503, {"message": "down"}))
    assert not _is_retryable(genai_errors.APIError(400, {"message": "bad"}))
    assert not _is_retryable(ValueError("nope"))
    print("ok: retry classifier flags only 429/5xx")
