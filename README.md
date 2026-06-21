# EduDeals

A student-discount finder web application built with React, TypeScript, and Supabase. EduDeals helps students browse, search, and save verified discounts — with a personalized feed that surfaces deals for your school based on your `.edu` email.

---

## Overview

Students sign in with a `.edu` email and land on a searchable grid of discounts. From there, they can:

- **Browse all deals** — paginated grid of discount cards, 9 per page
- **Search & filter** — match by brand/description, filter by one or more categories, and sort by name, expiry, or highest % off
- **View school specific discounts** — a dedicated tab matches discounts against the user's email domain (e.g. `@ucla.edu` → schools containing "ucla"); deals marked `school = all` show for every account
- **Save favorites** — heart any deal to add it to a personal "Saved" tab, persisted per user
- **Read full details** — long descriptions are clamped on the card, with a "Read more" link that opens a detail modal when text actually overflows
- **Toggle dark mode** — persisted to `localStorage`, defaulting to OS preference, with a glow-on-hover card effect

Filtered/sorted views are written to the URL, so a search can be shared or survives a page reload. The last-viewed tab is also remembered across sessions.

---

## Tech Stack

- **Frontend:** React 19, TypeScript, Tailwind CSS v4 (`@tailwindcss/vite`)
- **Backend:** Supabase (Postgres database + email/password auth) — no backend of our own; the React app talks to Supabase directly
- **Build tooling:** Vite, ESLint

---

## Project Structure

```
client/
└── src/
    ├── components/   # DiscountGrid, DiscountCard, AuthBar, ThemeToggle, Toast, ResetPassword
    ├── library/      # Supabase client + useSession / useSavedDiscounts hooks
    ├── types.ts      # the Discount type
    └── App.tsx       # app shell
```

---

## How to Run

### Prerequisites

- [Node.js](https://nodejs.org/) (v18+ recommended)
- npm
- A [Supabase](https://supabase.com) project

### Development

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
| `discounts` | `id`, `brand`, `description`, `discount_percent` (text, e.g. `"50% off"`), `category`, `redemption_url`, `expires_at` (nullable), `created_at`, `school` (nullable — a school name, an email domain like `chapman.edu`, or the literal `all`) |
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

## Deployment (Vercel)

The app lives in the `client/` directory, not the repo root. In your Vercel project settings, set **Root Directory** to `client` and add the two `VITE_SUPABASE_*` environment variables. Vite is auto-detected — no further build configuration needed.

---

## License

MIT