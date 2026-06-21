import { useEffect, useMemo, useState } from 'react'
import { supabase } from '../library/supabase'
import { useSession } from '../library/useSession'
import { useSavedDiscounts } from '../library/useSavedDiscounts'
import type { Discount } from '../types'
import DiscountCard from './DiscountCard'

const PAGE_SIZE = 9

type View = 'all' | 'saved' | 'school'
type Sort = 'alpha' | 'expiring' | 'percent'

// School column is inconsistent (display names like "UC Davis" vs domains like
// "chapman.edu"), so match loosely: strip punctuation and look for the email's
// domain core (e.g. olivercai@g.ucla.edu -> "ucla") inside the school value.
// ponytail: domain-core heuristic; won't catch display-name schools whose name
// shares nothing with the email domain. Add a domain->school map if that matters.
function norm(s: string | null | undefined) {
  return String(s ?? '').toLowerCase().trim().replace(/\.edu$/, '').replace(/[^a-z0-9]/g, '')
}
function schoolTokenFromEmail(email: string | undefined) {
  const domain = email?.split('@')[1]?.toLowerCase() ?? ''
  const labels = domain.split('.')
  return { domain, core: labels.length >= 2 ? labels[labels.length - 2] : '' }
}

// Pull the leading number out of strings like "50%" or "20% off".
function percentValue(s: string | null | undefined) {
  return parseFloat(String(s ?? '').replace(/[^0-9.]/g, '')) || 0
}

function DiscountGrid() {
  const params = new URLSearchParams(window.location.search)
  const [discounts, setDiscounts] = useState<Discount[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [view, setView] = useState<View>(() => (localStorage.getItem('view') as View) ?? 'all')
  const [savedDiscounts, setSavedDiscounts] = useState<Discount[]>([])
  const [loadingSaved, setLoadingSaved] = useState(false)

  const [query, setQuery] = useState(params.get('q') ?? '')
  const [selected, setSelected] = useState<Set<string>>(
    new Set(params.get('cat')?.split(',').filter(Boolean) ?? []),
  )
  const [sort, setSort] = useState<Sort>((params.get('sort') as Sort) ?? 'alpha')
  const [page, setPage] = useState(0)
  const [active, setActive] = useState<Discount | null>(null)

  const { session } = useSession()
  const userId = session?.user?.id
  const { savedIds, toggle } = useSavedDiscounts(userId)

  const { domain, core } = schoolTokenFromEmail(session?.user?.email)
  const matchesSchool = (d: Discount) => {
    if (!core && !domain) return false
    const ns = norm(d.school)
    // "all" discounts show for any .edu account.
    if (ns === 'all' && domain.endsWith('.edu')) return true
    return (core !== '' && ns.includes(core)) || (domain !== '' && ns.includes(norm(domain)))
  }

  // Sign-out while viewing a logged-in-only tab sends you back to All.
  useEffect(() => {
    if (!userId && (view === 'saved' || view === 'school')) setView('all')
  }, [userId, view])

  // Remember the last tab across reloads.
  useEffect(() => {
    localStorage.setItem('view', view)
  }, [view])

  // All discounts.
  useEffect(() => {
    supabase
      .from('discounts')
      .select('*')
      .order('brand')
      .then(({ data, error }) => {
        if (error) {
          setError(error.message)
        } else {
          setDiscounts((data as Discount[]) ?? [])
        }
        setLoading(false)
      })
  }, [])

  // Saved discounts, joined from saved_discounts → discounts for the current user.
  useEffect(() => {
    if (view !== 'saved' || !userId) return

    let active = true
    setLoadingSaved(true)
    supabase
      .from('saved_discounts')
      .select('discount:discounts(*)')
      .eq('user_id', userId)
      .then(({ data, error }) => {
        if (!active) return
        if (error) {
          console.error(error)
        } else {
          const rows = (data ?? []) as unknown as { discount: Discount | null }[]
          setSavedDiscounts(rows.map((r) => r.discount).filter((d): d is Discount => d !== null))
        }
        setLoadingSaved(false)
      })

    return () => {
      active = false
    }
  }, [view, userId])

  const source = view === 'saved' ? savedDiscounts : discounts

  const categories = useMemo(() => {
    const set = new Set(source.map((d) => d.category))
    return Array.from(set).sort()
  }, [source])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    const now = Date.now()
    const byExpiring = (a: Discount, b: Discount) => {
      // Soonest expiry first; no-expiry items sink to the bottom.
      const ea = a.expires_at ? new Date(a.expires_at).getTime() : Infinity
      const eb = b.expires_at ? new Date(b.expires_at).getTime() : Infinity
      return ea - eb
    }
    return source
      .filter((d) => {
        // In the saved view, reflect live un-hearts immediately.
        if (view === 'saved' && !savedIds.has(d.id)) return false
        // In the school view, only show discounts for the user's school.
        if (view === 'school' && !matchesSchool(d)) return false
        // Hide expired discounts everywhere.
        if (d.expires_at && new Date(d.expires_at).getTime() < now) return false
        const matchesCategory = selected.size === 0 || selected.has(d.category)
        const matchesQuery =
          q === '' ||
          d.brand.toLowerCase().includes(q) ||
          d.description.toLowerCase().includes(q)
        return matchesCategory && matchesQuery
      })
      .sort((a, b) => {
        if (sort === 'percent') return percentValue(b.discount_percent) - percentValue(a.discount_percent)
        if (sort === 'expiring') return byExpiring(a, b)
        // alpha
        return a.brand.localeCompare(b.brand)
      })
  }, [source, view, savedIds, query, selected, sort, core, domain])

  // Reset paging whenever the visible set changes.
  useEffect(() => {
    setPage(0)
  }, [query, selected, view, sort])

  // Keep filters in the URL so views are shareable / survive reload.
  useEffect(() => {
    const p = new URLSearchParams()
    if (query) p.set('q', query)
    if (selected.size) p.set('cat', [...selected].join(','))
    if (sort !== 'alpha') p.set('sort', sort)
    const qs = p.toString()
    window.history.replaceState(null, '', qs ? `?${qs}` : window.location.pathname)
  }, [query, selected, sort])

  function toggleCategory(c: string) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(c)) next.delete(c)
      else next.add(c)
      return next
    })
  }

  const hasFilters = query.trim() !== '' || selected.size > 0 || sort !== 'alpha'
  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  // Clamp in case the filtered set shrank below the current page.
  const safePage = Math.min(page, pageCount - 1)
  const visible = filtered.slice(safePage * PAGE_SIZE, safePage * PAGE_SIZE + PAGE_SIZE)

  if (loading) {
    return <p className="py-12 text-center text-gray-500 dark:text-gray-400">Loading discounts…</p>
  }

  if (error) {
    return <p className="py-12 text-center text-red-600">Couldn't load discounts: {error}</p>
  }

  const inputClass =
    'rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-gray-900 focus:outline-none dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100 dark:focus:border-gray-400'

  const tabClass = (active: boolean) =>
    `rounded-lg px-4 py-2 text-sm font-medium transition ${
      active
        ? 'bg-gray-900 text-white dark:bg-gray-100 dark:text-gray-900'
        : 'text-gray-600 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-800'
    }`

  const chipClass = (active: boolean) =>
    `shrink-0 whitespace-nowrap rounded-full border px-2.5 py-1.5 text-sm font-medium transition ${
      active
        ? 'border-gray-900 bg-gray-900 text-white dark:border-gray-100 dark:bg-gray-100 dark:text-gray-900'
        : 'border-gray-300 text-gray-600 hover:bg-gray-100 dark:border-gray-600 dark:text-gray-300 dark:hover:bg-gray-800'
    }`

  return (
    <div>
      {userId && (
        <div className="mb-5 flex gap-2">
          <button onClick={() => setView('all')} className={tabClass(view === 'all')}>
            All discounts
          </button>
          <button onClick={() => setView('school')} className={tabClass(view === 'school')}>
            For your school
          </button>
          <button onClick={() => setView('saved')} className={tabClass(view === 'saved')}>
            Saved ({savedIds.size})
          </button>
        </div>
      )}

      <div className="mb-4 flex flex-col gap-3 sm:flex-row">
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search by brand or description…"
          className={`${inputClass} flex-1`}
        />
        <select
          value={sort}
          onChange={(e) => setSort(e.target.value as Sort)}
          className={inputClass}
          aria-label="Sort discounts"
        >
          <option value="alpha">Alphabetical</option>
          <option value="expiring">Expiring soon</option>
          <option value="percent">Highest % off</option>
        </select>
      </div>

      <div className="mb-6 flex flex-nowrap gap-2 overflow-x-auto pb-1">
        <button onClick={() => setSelected(new Set())} className={chipClass(selected.size === 0)}>
          All
        </button>
        {categories.map((c) => (
          <button key={c} onClick={() => toggleCategory(c)} className={`${chipClass(selected.has(c))} capitalize`}>
            {c}
          </button>
        ))}
      </div>

      <div className="mb-4 flex items-center justify-between text-sm text-gray-500 dark:text-gray-400">
        <span>
          {filtered.length} {filtered.length === 1 ? 'discount' : 'discounts'}
        </span>
        {hasFilters && (
          <button
            onClick={() => {
              setQuery('')
              setSelected(new Set())
              setSort('alpha')
            }}
            className="font-medium text-gray-900 underline underline-offset-2 hover:text-gray-600 dark:text-gray-100 dark:hover:text-gray-300"
          >
            Clear filters
          </button>
        )}
      </div>

      {view === 'saved' && loadingSaved ? (
        <p className="py-12 text-center text-gray-500 dark:text-gray-400">Loading saved discounts…</p>
      ) : filtered.length === 0 ? (
        <div className="py-12 text-center text-gray-500 dark:text-gray-400">
          {view === 'saved' ? (
            <>
              <p>You haven’t saved any discounts yet.</p>
              <button
                onClick={() => setView('all')}
                className="mt-3 rounded-lg bg-gray-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-gray-700 dark:bg-gray-100 dark:text-gray-900 dark:hover:bg-gray-300"
              >
                Browse all discounts
              </button>
            </>
          ) : view === 'school' ? (
            <>
              <p>No discounts found for your school{domain ? ` (${domain})` : ''} yet.</p>
              <button
                onClick={() => setView('all')}
                className="mt-3 rounded-lg bg-gray-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-gray-700 dark:bg-gray-100 dark:text-gray-900 dark:hover:bg-gray-300"
              >
                Browse all discounts
              </button>
            </>
          ) : discounts.length === 0 ? (
            <p>No discounts available yet.</p>
          ) : (
            <p>No discounts match your search.</p>
          )}
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {visible.map((discount) => (
              <DiscountCard
                key={discount.id}
                discount={discount}
                saved={savedIds.has(discount.id)}
                onToggleSave={userId ? () => toggle(discount.id) : undefined}
                onReadMore={() => setActive(discount)}
              />
            ))}
          </div>

          <div className="flex items-center justify-center gap-4 py-8">
            <button
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={safePage === 0}
              className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-40 dark:border-gray-600 dark:text-gray-200 dark:hover:bg-gray-800"
            >
              ← Previous
            </button>
            <span className="flex items-center gap-1.5 text-sm text-gray-500 dark:text-gray-400">
              Page
              <input
                type="text"
                inputMode="numeric"
                defaultValue={safePage + 1}
                key={safePage}
                onKeyDown={(e) => e.key === 'Enter' && (e.target as HTMLInputElement).blur()}
                onBlur={(e) => {
                  const n = Number(e.target.value)
                  if (n) setPage(Math.min(pageCount, Math.max(1, n)) - 1)
                  e.target.value = String(Math.min(pageCount, Math.max(1, n || 1)))
                }}
                className="w-14 rounded-lg border border-gray-300 px-2 py-1 text-center text-sm focus:border-gray-900 focus:outline-none dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100"
                aria-label="Jump to page"
              />
              of {pageCount}
            </span>
            <button
              onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}
              disabled={safePage >= pageCount - 1}
              className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-40 dark:border-gray-600 dark:text-gray-200 dark:hover:bg-gray-800"
            >
              Next →
            </button>
          </div>
        </>
      )}

      {active && (
        <div
          onClick={() => setActive(null)}
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
        >
          <div
            onClick={(e) => e.stopPropagation()}
            className="relative max-h-[85vh] w-full max-w-lg overflow-y-auto rounded-2xl bg-white p-6 shadow-xl dark:bg-gray-900"
          >
            <button
              onClick={() => setActive(null)}
              aria-label="Close"
              className="absolute right-4 top-4 text-2xl leading-none text-gray-400 hover:text-gray-700 dark:hover:text-gray-200"
            >
              ×
            </button>
            <h3 className="pr-8 text-2xl font-semibold text-gray-900 dark:text-gray-100">{active.brand}</h3>
            <p className="mt-1 text-3xl font-bold text-emerald-600 dark:text-emerald-400">
              {active.discount_percent}
            </p>
            <p className="mt-4 whitespace-pre-line text-gray-600 dark:text-gray-300">{active.description}</p>
            {active.expires_at && (
              <p className="mt-4 text-sm text-gray-400 dark:text-gray-500">
                Expires {new Date(active.expires_at).toLocaleDateString()}
              </p>
            )}
            <a
              href={active.redemption_url}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-6 inline-flex items-center justify-center rounded-lg bg-gray-900 px-5 py-2.5 text-sm font-medium text-white transition hover:bg-gray-700 dark:bg-gray-100 dark:text-gray-900 dark:hover:bg-gray-300"
            >
              Redeem
            </a>
          </div>
        </div>
      )}
    </div>
  )
}

export default DiscountGrid
