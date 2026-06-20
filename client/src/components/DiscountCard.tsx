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

function DiscountCard({ discount }: { discount: Discount }) {
  const { brand, description, discount_percent, category, redemption_url, expires_at } = discount

  return (
    <div className="flex flex-col rounded-xl border border-gray-200 bg-white p-5 shadow-sm transition hover:shadow-md">
      <div className="flex items-start justify-between gap-3">
        <h3 className="text-lg font-semibold text-gray-900">{brand}</h3>
        <span className={`shrink-0 rounded-full px-2.5 py-0.5 text-xs font-medium ${categoryClass(category)}`}>
          {category}
        </span>
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
