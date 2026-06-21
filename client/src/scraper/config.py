"""Environment + shared config for the Python discounts pipeline.

Runs alongside the existing Node scraper.js — both write to public.discounts.
"""
import os
from dotenv import load_dotenv

# .env lives at client/.env (two levels up from this file), same as scraper.js.
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

# Postgres connection string for psycopg. Get it from Supabase →
# Project Settings → Database → Connection string (URI). NOT the REST URL.
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# SerpApi key for brand discovery (serpapi.com).
SERPAPI_KEY = os.environ.get("SERPAPI_KEY", "")

# Gemini key for LLM-based deal extraction (pipeline_local).
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# ScraperAPI key — used only as a fallback when a local page returns 403.
SCRAPERAPI_KEY = os.environ.get("SCRAPERAPI_KEY", "")

# pipeline_local pages. Just URLs — the semantic cleaner generalizes across
# layouts, so no per-page CSS selectors needed. Add a site = add a URL.
LOCAL_URLS = [
    "https://www.downtownberkeley.com/student-discounts/",
    "https://davisdowntown.com/aggie-deals/",
    "https://www.sjsu.edu/alumni/join/member-benefits.php",
]

# Curated open-source student-deal lists (raw markdown). Plain text, so the native
# fetch handles them — no ScraperAPI needed. They flow into the same batch call.
GITHUB_SEED_URLS = [
    "https://raw.githubusercontent.com/couponswift/awesome-student-software-deals/main/README.md",
    # The deals live in Database/database.md (a ~195-row table), NOT the README.
    "https://raw.githubusercontent.com/ShreyamMaity/student-offers/main/Database/database.md",
]


def _mask(value: str) -> str:
    """Show enough to confirm a value loaded without leaking the secret."""
    if not value:
        return "(empty)"
    return f"{value[:8]}...{value[-4:]}" if len(value) > 14 else value[:3] + "***"


def env_status() -> None:
    """Print which env vars loaded, secrets masked. This pipeline talks to
    Postgres directly via DATABASE_URL — the Supabase REST URL/anon key are NOT
    used here, so DATABASE_URL being empty means inserts have nowhere to go."""
    print("[config] .env load status (secrets masked):")
    print(f"  DATABASE_URL   : {_mask(DATABASE_URL)}   <- required for DB writes")
    print(f"  SERPAPI_KEY    : {_mask(SERPAPI_KEY)}")
    print(f"  SCRAPERAPI_KEY : {_mask(SCRAPERAPI_KEY)}")
    if not DATABASE_URL:
        print("  ! DATABASE_URL is empty - set it to your Supabase Postgres URI "
              "(Project Settings -> Database -> Connection string).")


if __name__ == "__main__":
    env_status()
