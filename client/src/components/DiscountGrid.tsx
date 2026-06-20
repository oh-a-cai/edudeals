import { useEffect, useMemo, useRef, useState } from 'react'
import { supabase } from '../library/supabase'
import { useSession } from '../library/useSession'
import { useSavedDiscounts } from '../library/useSavedDiscounts'
import type { Discount } from '../types'
import DiscountCard from './DiscountCard'

const ALL = 'all'
const PAGE_SIZE = 9

function DiscountGrid() {
  const [discounts, setDiscounts] = useState<Discount[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [query, setQuery] = useState('')
  const [category, setCategory] = useState(ALL)
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE)

  const sentinelRef = useRef<HTMLDivElement | null>(null)

  const { session } = useSession()
  const userId = session?.user?.id
  const { savedIds, toggle } = useSavedDiscounts(userId)

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

  const categories = useMemo(() => {
    const set = new Set(discounts.map((d) => d.category))
    return Array.from(set).sort()
  }, [discounts])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    return discounts.filter((d) => {
      const matchesCategory = category === ALL || d.category === category
      const matchesQuery =
        q === '' ||
        d.brand.toLowerCase().includes(q) ||
        d.description.toLowerCase().includes(q)
      return matchesCategory && matchesQuery
    })
  }, [discounts, query, category])

  // Reset paging whenever the filtered set changes.
  useEffect(() => {
    setVisibleCount(PAGE_SIZE)
  }, [query, category])

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
    return <p className="py-12 text-center text-gray-500">Loading discounts…</p>
  }

  if (error) {
    return <p className="py-12 text-center text-red-600">Couldn't load discounts: {error}</p>
  }

  const inputClass =
    'rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-gray-900 focus:outline-none'

  return (
    <div>
      <div className="mb-6 flex flex-col gap-3 sm:flex-row">
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search by brand or description…"
          className={`${inputClass} flex-1`}
        />
        <select
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          className={`${inputClass} capitalize`}
        >
          <option value={ALL}>All categories</option>
          {categories.map((c) => (
            <option key={c} value={c} className="capitalize">
              {c}
            </option>
          ))}
        </select>
      </div>

      {filtered.length === 0 ? (
        <p className="py-12 text-center text-gray-500">
          {discounts.length === 0 ? 'No discounts available yet.' : 'No discounts match your search.'}
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
                className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-100"
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
