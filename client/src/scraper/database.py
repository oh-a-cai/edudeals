"""Async Postgres upsert via a psycopg v3 connection pool."""
import asyncio
import sys
from dataclasses import dataclass, field

from config import DATABASE_URL

# psycopg's async mode cannot use Windows' default ProactorEventLoop. Select the
# selector loop at import so every entry point (main, diagnostics) inherits it
# before asyncio.run() builds its loop.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@dataclass
class Deal:
    """One row of public.discounts. brand/description are NOT NULL in the schema."""
    brand: str
    description: str
    discount_percent: str | None = None
    category: str | None = None    # primary tag (tags[0]); kept for the frontend grid
    redemption_url: str | None = None
    expires_at: str | None = None  # ISO date string ('2026-12-31') or None
    school: str | None = None      # source campus/school label, e.g. 'UC Berkeley'
    tags: list[str] = field(default_factory=list)  # canonical multi-tag set


_UPSERT_SQL = """
    INSERT INTO public.discounts
        (brand, description, discount_percent, category, redemption_url, expires_at, school, tags)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (redemption_url)
    DO UPDATE SET
        description = EXCLUDED.description,
        discount_percent = EXCLUDED.discount_percent,
        school = EXCLUDED.school,
        category = EXCLUDED.category,
        tags = EXCLUDED.tags;
"""


def _ensure_scheme(url: str) -> str:
    """Frontend needs absolute links — prepend https:// to any scheme-less URL
    (e.g. a raw 'stripe.com' from a markdown list) so it isn't read as relative."""
    return url if url.startswith(("http://", "https://")) else "https://" + url


def drop_unconflictable(deals: list[Deal]) -> list[Deal]:
    """Postgres treats NULLs as distinct, so ON CONFLICT (redemption_url) can't
    dedupe null-URL rows — they'd insert unbounded. Drop them before the batch."""
    return [d for d in deals if d.redemption_url]


async def save_deals(deals: list[Deal]) -> int:
    """Bulk upsert every deal into public.discounts on the redemption_url unique
    constraint. One flat table — no scope/locality split."""
    # Lazy import: keeps Deal/drop_unconflictable usable without the DB driver.
    from psycopg_pool import AsyncConnectionPool

    # Fail fast on a missing connection string — otherwise the pool retries a
    # bad/empty DSN in a noisy loop before giving up.
    if not DATABASE_URL:
        print("[db] DATABASE_URL is empty - cannot write. Set it in client/.env "
              "(Supabase -> Settings -> Database -> Connection string).")
        return 0

    rows = drop_unconflictable(deals)
    if not rows:
        print("[db] No deals with a valid redemption_url to write.")
        return 0

    # ponytail: pool opened per run — fine for a batch CLI. Hoist to a module-level
    # pool if main ever becomes a long-running service.
    async with AsyncConnectionPool(DATABASE_URL, open=False) as pool:
        await pool.open()
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.executemany(_UPSERT_SQL, [
                    (d.brand, d.description, d.discount_percent, d.category,
                     _ensure_scheme(d.redemption_url), d.expires_at, d.school, d.tags)
                    for d in rows
                ])
            await conn.commit()

    print(f"[db] Upserted {len(rows)} deals -> public.discounts")
    return len(rows)
