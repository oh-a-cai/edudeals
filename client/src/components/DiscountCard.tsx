import type { Discount } from '../types'

const categoryStyles: Record<string, string> = {
  entertainment: 'bg-pink-100 text-pink-700',
  software: 'bg-indigo-100 text-indigo-700',
  shopping: 'bg-amber-100 text-amber-700',
  food: 'bg-green-100 text-green-700',
  travel: 'bg-sky-100 text-sky-700',
}

function categoryClass(category: string) {
  return categoryStyles[category.toLowerCase()] ?? 'bg-gray-100 text-gray-700'
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
}

function DiscountCard({ discount, saved = false, onToggleSave }: DiscountCardProps) {
  const { brand, description, discount_percent, category, redemption_url, expires_at } = discount

  return (
    <div className="flex flex-col rounded-xl border border-gray-200 bg-white p-5 shadow-sm transition hover:shadow-md">
      <div className="flex items-start justify-between gap-3">
        <h3 className="text-lg font-semibold text-gray-900">{brand}</h3>
        <div className="flex shrink-0 items-center gap-2">
          <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${categoryClass(category)}`}>
            {category}
          </span>
          {onToggleSave && <HeartButton saved={saved} onToggle={onToggleSave} />}
        </div>
      </div>

      <p className="mt-1 text-2xl font-bold text-emerald-600">{discount_percent}</p>

      <p className="mt-2 flex-1 text-sm text-gray-600">{description}</p>

      {expires_at && (
        <p className="mt-3 text-xs text-gray-400">
          Expires {new Date(expires_at).toLocaleDateString()}
        </p>
      )}

      <a
        href={redemption_url}
        target="_blank"
        rel="noopener noreferrer"
        className="mt-4 inline-flex items-center justify-center rounded-lg bg-gray-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-gray-700"
      >
        Redeem
      </a>
    </div>
  )
}

export default DiscountCard
