import { useEffect, useMemo, useRef, useState } from 'react'
import { supabase } from '../library/supabase'
import { useSession } from '../library/useSession'
import { useSavedDiscounts } from '../library/useSavedDiscounts'
import type { Discount } from '../types'
import DiscountCard from './DiscountCard'

const PAGE_SIZE = 9

type View = 'all' | 'saved'

function DiscountGrid() {
  const [discounts, setDiscounts] = useState<Discount[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [view, setView] = useState<View>('all')
  const [savedDiscounts, setSavedDiscounts] = useState<Discount[]>([])
  const [loadingSaved, setLoadingSaved] = useState(false)

  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE)

  const sentinelRef = useRef<HTMLDivElement | null>(null)

  const { session } = useSession()
  const userId = session?.user?.id
  const { savedIds, toggle } = useSavedDiscounts(userId)

  // Sign-out while viewing Saved sends you back to All.
  useEffect(() => {
    if (!userId && view === 'saved') setView('all')
  }, [userId, view])

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
    return source.filter((d) => {
      // In the saved view, reflect live un-hearts immediately.
      if (view === 'saved' && !savedIds.has(d.id)) return false
      const matchesCategory = selected.size === 0 || selected.has(d.category)
      const matchesQuery =
        q === '' ||
        d.brand.toLowerCase().includes(q) ||
        d.description.toLowerCase().includes(q)
      return matchesCategory && matchesQuery
    })
  }, [source, view, savedIds, query, selected])

  // Reset paging whenever the visible set changes.
  useEffect(() => {
    setVisibleCount(PAGE_SIZE)
  }, [query, selected, view])

  function toggleCategory(c: string) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(c)) next.delete(c)
      else next.add(c)
      return next
    })
  }

  const visible = filtered.slice(0, visibleCount)
  const hasMore = visibleCount < filtered.length

  // Auto-load the next page when the sentinel scrolls into view.
  useEffect(() => {
    if (!hasMore) return
    const node = sentinelRef.current
    if (!node) return

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting) {
          setVisibleCount((c) => c + PAGE_SIZE)
        }
      },
      { rootMargin: '200px' },
    )
    observer.observe(node)
    return () => observer.disconnect()
  }, [hasMore])

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
    `rounded-full border px-3 py-1 text-sm font-medium transition ${
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
          <button onClick={() => setView('saved')} className={tabClass(view === 'saved')}>
            Saved ({savedIds.size})
          </button>
        </div>
      )}

      <div className="mb-4">
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search by brand or description…"
          className={`${inputClass} w-full`}
        />
      </div>

      <div className="mb-6 flex flex-wrap gap-2">
        <button onClick={() => setSelected(new Set())} className={chipClass(selected.size === 0)}>
          All
        </button>
        {categories.map((c) => (
          <button key={c} onClick={() => toggleCategory(c)} className={`${chipClass(selected.has(c))} capitalize`}>
            {c}
          </button>
        ))}
      </div>

      {view === 'saved' && loadingSaved ? (
        <p className="py-12 text-center text-gray-500 dark:text-gray-400">Loading saved discounts…</p>
      ) : filtered.length === 0 ? (
        <p className="py-12 text-center text-gray-500 dark:text-gray-400">
          {view === 'saved'
            ? 'You haven’t saved any discounts yet.'
            : discounts.length === 0
              ? 'No discounts available yet.'
              : 'No discounts match your search.'}
        </p>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {visible.map((discount) => (
              <DiscountCard
                key={discount.id}
                discount={discount}
                saved={savedIds.has(discount.id)}
                onToggleSave={userId ? () => toggle(discount.id) : undefined}
              />
            ))}
          </div>

          {hasMore && (
            <div ref={sentinelRef} className="flex justify-center py-8">
              <button
                onClick={() => setVisibleCount((c) => c + PAGE_SIZE)}
                className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-100 dark:border-gray-600 dark:text-gray-200 dark:hover:bg-gray-800"
              >
                Load more
              </button>
            </div>
          )}
        </>
      )}
    </div>
  )
}

export default DiscountGrid
