import { useLayoutEffect, useRef, useState } from 'react'
import type { Discount } from '../types'

const categoryStyles: Record<string, string> = {
  'design': 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-300',
  'education': 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300',
  'entertainment': 'bg-pink-100 text-pink-700 dark:bg-pink-900/30 dark:text-pink-300',
  'food & drink': 'bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-300',
  'health & wellness': 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300',
  'other': 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300',
  'retail': 'bg-lime-100 text-lime-700 dark:bg-lime-900/30 dark:text-lime-300',
  'services': 'bg-cyan-100 text-cyan-700 dark:bg-cyan-900/30 dark:text-cyan-300',
  'tech & software': 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300',
}

function categoryClass(category: string | null | undefined) {
  return categoryStyles[(category ?? '').toLowerCase()] ?? 'bg-gray-100 text-gray-700'
}

function HeartButton({ saved, onToggle }: { saved: boolean; onToggle: () => void }) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-pressed={saved}
      aria-label={saved ? 'Remove from saved' : 'Save discount'}
      className="shrink-0 text-gray-300 transition hover:text-red-400"
    >
      <svg
        viewBox="0 0 24 24"
        className={`h-5 w-5 ${saved ? 'fill-red-500 text-red-500' : 'fill-none'}`}
        stroke="currentColor"
        strokeWidth="2"
      >
        <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 1 0-7.78 7.78L12 21.23l8.84-8.84a5.5 5.5 0 0 0 0-7.78z" />
      </svg>
    </button>
  )
}

interface DiscountCardProps {
  discount: Discount
  saved?: boolean
  onToggleSave?: () => void
  onReadMore?: () => void
  onRedeem?: (url: string) => void
}

const WEEK_MS = 7 * 24 * 60 * 60 * 1000

function DiscountCard({ discount, saved = false, onToggleSave, onReadMore, onRedeem }: DiscountCardProps) {
  const { brand, description, discount_percent, category, redemption_url, expires_at } = discount

  const expiringSoon =
    expires_at != null && new Date(expires_at).getTime() - Date.now() < WEEK_MS

  // Show "Read more" only when the clamped description is actually truncated.
  const descRef = useRef<HTMLParagraphElement>(null)
  const [overflows, setOverflows] = useState(false)
  useLayoutEffect(() => {
    const el = descRef.current
    if (el) setOverflows(el.scrollHeight > el.clientHeight + 1)
  }, [description])

  return (
    <div className="flex h-56 flex-col rounded-xl border border-gray-200 bg-white p-4 shadow-sm transition hover:shadow-lg dark:border-gray-700 dark:bg-gray-900 dark:hover:border-emerald-500/50 dark:hover:shadow-[0_0_20px_rgba(16,185,129,0.35)]">
      <div className="flex items-start justify-between gap-3">
        <h3 className="line-clamp-1 text-base font-semibold text-gray-900 dark:text-gray-100">{brand}</h3>
        <div className="flex shrink-0 items-center gap-2">
          <span className={`whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ${categoryClass(category)}`}>
            {category}
          </span>
          {onToggleSave && <HeartButton saved={saved} onToggle={onToggleSave} />}
        </div>
      </div>

      <p className="mt-1 text-xl font-bold text-emerald-600 dark:text-emerald-400">{discount_percent}</p>

      <div className="mt-1 flex-1 overflow-hidden">
        <p ref={descRef} className="line-clamp-2 text-sm text-gray-600 dark:text-gray-300">{description}</p>
      </div>

      {overflows && onReadMore && (
        <button
          type="button"
          onClick={onReadMore}
          className="mt-2 self-start text-sm font-medium text-gray-900 underline dark:text-gray-100"
        >
          Read more
        </button>
      )}

      {expires_at && (
        <p
          className={`mt-2 text-xs ${
            expiringSoon ? 'font-medium text-amber-600 dark:text-amber-400' : 'text-gray-400 dark:text-gray-500'
          }`}
        >
          {expiringSoon ? 'Expiring soon · ' : 'Expires '}
          {new Date(expires_at).toLocaleDateString()}
        </p>
      )}

      <button
        type="button"
        onClick={() => onRedeem?.(redemption_url)}
        className="mt-3 inline-flex items-center justify-center rounded-lg bg-gray-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-gray-700 dark:bg-gray-100 dark:text-gray-900 dark:hover:bg-gray-300"
      >
        Redeem
      </button>
    </div>
  )
}

export default DiscountCard
