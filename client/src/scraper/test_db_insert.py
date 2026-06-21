"""Isolated DB insertion diagnostic — bypasses all scraping logic.

Run: python test_db_insert.py
Inserts one static row into public.discounts to prove the DB layer works.
"""
import asyncio

from config import env_status
from database import save_deals


class MockDeal:
    brand = "Connection Test Brand"
    description = "Diagnostic test to verify database insertion layer works."
    discount_percent = "99%"
    category = "Diagnostics"
    redemption_url = "https://test-connection.io/debug-run"
    expires_at = None


async def run_test():
    env_status()
    print("Executing force-insert test using MockDeal profile...")
    written = await save_deals([MockDeal()])
    print(f"Database insertion call completed. Rows written: {written}")


if __name__ == "__main__":
    asyncio.run(run_test())
