import { useEffect, useState } from 'react'
import { supabase } from '../library/supabase'
import type { Discount } from '../types'
import DiscountCard from './DiscountCard'

function DiscountGrid() {
  const [discounts, setDiscounts] = useState<Discount[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

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

  if (loading) {
    return <p className="py-12 text-center text-gray-500">Loading discounts…</p>
  }

  if (error) {
    return <p className="py-12 text-center text-red-600">Couldn't load discounts: {error}</p>
  }

  if (discounts.length === 0) {
    return <p className="py-12 text-center text-gray-500">No discounts available yet.</p>
  }

  return (
    <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
      {discounts.map((discount) => (
        <DiscountCard key={discount.id} discount={discount} />
      ))}
    </div>
  )
}

export default DiscountGrid
