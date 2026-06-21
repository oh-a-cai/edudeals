# EduDeals

A student-discount finder web application built with React, TypeScript, and Supabase. EduDeals helps students browse, search, and save verified discounts — with a personalized feed that surfaces deals for your school based on your `.edu` email. Discounts are populated automatically by a Python scraping pipeline.

---

## Overview

Students sign in with a `.edu` email and land on a searchable grid of discounts. From there, they can:

- **Browse all deals** — paginated grid of discount cards, 9 per page
- **Search & filter** — match by brand/description, filter by one or more categories, and sort by name, expiry, or highest % off
- **View your university-specific deals** — a dedicated tab matches discounts against the user's email domain (e.g. `@g.ucla.edu` → schools containing "ucla"); deals marked `school = all` show for every account
- **Save favorites** — heart any deal to add it to a personal "Saved" tab, persisted per user
- **Read full details** — long descriptions are clamped on the card, with a "Read more" link that opens a detail modal when text actually overflows
- **Toggle dark mode** — toggle persisted to `localStorage`, defaulting to OS preference, with a glow-on-hover card effect

Filtered/sorted views are written to the URL, so a search can be shared or survives a page reload. The last-viewed tab is also remembered across sessions.

Behind the scenes, a standalone Python pipeline discovers deals from campus pages and seed lists, extracts them with Gemini, and upserts them into the same Postgres database the frontend reads from.

---

## Tech Stack

- **Frontend:** React 19, TypeScript, Tailwind CSS v4 (`@tailwindcss/vite`)
- **Backend:** Supabase (Postgres database + email/password auth) — the React app talks to Supabase directly
- **Data pipeline:** Python, `httpx` + `BeautifulSoup` for fetching/parsing, **Google Gemini** for deal extraction, `psycopg` for writing straight to Postgres
- **Build tooling:** Vite, ESLint

The scraper writes to the same database out of band — the frontend never runs it directly.

---

## Project Structure

```
client/
└── src/
    ├── components/   # DiscountGrid, DiscountCard, AuthBar, ThemeToggle, Toast, ResetPassword
    ├── library/      # Supabase client + useSession / useSavedDiscounts hooks
    ├── scraper/      # Python pipeline (main.py, config.py, database.py, pipeline_*.py, tests)
    ├── types.ts      # the Discount type
    └── App.tsx       # app shell
```

---

## How to Run

### Prerequisites

- [Node.js](https://nodejs.org/) (v18+ recommended)
- npm
- Python 3.10+ (for the scraper)
- A [Supabase](https://supabase.com) project

### Frontend

**1. Clone the repository**
```bash
git clone https://github.com/yourusername/edudeals.git
```

**2. Navigate to the client directory**
```bash
cd edudeals/client
```

**3. Install dependencies**
```bash
npm install
```

**4. Configure environment variables**

Create a `.env` (or `.env.local`) in `client/` with your Supabase project credentials:
```
VITE_SUPABASE_URL=https://<your-project>.supabase.co
VITE_SUPABASE_ANON_KEY=<your-anon-key>
```

**5. Set up the database**

Supabase needs two tables:

| Table | Columns |
|---|---|
| `discounts` | `id`, `brand`, `description`, `discount_percent` (text, e.g. `"50% off"`), `category`, `redemption_url` (unique — the scraper upserts on it), `expires_at` (nullable), `created_at`, `school` (nullable — a school name, an email domain like `chapman.edu`, or the literal `all`), `tags` (text array) |
| `saved_discounts` | `user_id`, `discount_id` (a user's hearted discounts) |

Enable **Email/Password** auth in Supabase for sign-in, favoriting, and the school feed.

**6. Start the dev server**
```bash
npm run dev
```
> Runs at `http://localhost:5173`.

---

### Other Commands

```bash
npm run build     # type-check + production build to dist/
npm run preview   # serve the production build locally
npm run lint      # run ESLint
```

---

## Data Pipeline (Python Scraper)

`src/scraper/` is a standalone pipeline that discovers student-discount listings, extracts structured deals, and upserts them into the `discounts` table. The frontend never runs it — it's a separate batch job, run on demand or on a schedule.

`main.py` orchestrates four stages:

1. **Collect pages** — fetches a curated list of campus/city deal pages (`LOCAL_URLS` in `config.py`), raw GitHub markdown deal lists (`GITHUB_SEED_URLS`), and search-discovered directory pages. `httpx` handles fetching, with **ScraperAPI** as a 403 fallback.
2. **Extract deals** — messy campus HTML is cleaned and sent in a single batched call to **Google Gemini**, which returns structured deals; clean GitHub markdown lists are parsed deterministically with regex (no LLM quota used).
3. **Dedupe & merge** — collapses the same merchant repeated on one site (by normalized brand + host) while keeping genuinely distinct deals; GitHub wins on cross-source brand collisions.
4. **Upsert** — writes to `public.discounts` via a `psycopg` async connection pool, using `ON CONFLICT (redemption_url)` so re-runs update existing rows instead of duplicating. A `scraped_output_debug.json` dump is written alongside for inspection.

### Running the Scraper

**1. Navigate to the scraper directory**
```bash
cd src/scraper
```

**2. Install dependencies**
```bash
pip install -r requirements.txt
```

**3. Run the pipeline**
```bash
python main.py
```
> Reads `client/.env` (two levels up).

**Required and optional environment variables:**
```
DATABASE_URL=postgresql://...      # required — Supabase → Project Settings → Database → Connection string (URI), NOT the REST URL
GEMINI_API_KEY=...                 # required for LLM extraction of campus HTML
SERPAPI_KEY=...                    # optional — brand/directory discovery
SCRAPERAPI_KEY=...                 # optional — fallback for pages that return 403
```

To add a source, add its URL to `LOCAL_URLS` or `GITHUB_SEED_URLS` in `config.py` — the semantic extractor generalizes across layouts, so no per-site CSS selectors are needed. The `test_*.py` files cover DB connectivity, inserts, and discovery in isolation.

---

## Deployment (Vercel)

The app lives in the `client/` directory, not the repo root. In your Vercel project settings, set **Root Directory** to `client` and add the two `VITE_SUPABASE_*` environment variables. Vite is auto-detected — no further build configuration needed.

---

## License

MIT