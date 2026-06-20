import { useEffect, useState } from 'react'
import { supabase } from './supabase'

export function useSavedDiscounts(userId: string | undefined) {
  const [savedIds, setSavedIds] = useState<Set<string>>(new Set())

  useEffect(() => {
    if (!userId) {
      setSavedIds(new Set())
      return
    }

    let active = true
    supabase
      .from('saved_discounts')
      .select('discount_id')
      .eq('user_id', userId)
      .then(({ data, error }) => {
        if (!active) return
        if (error) {
          console.error(error)
          return
        }
        setSavedIds(new Set((data ?? []).map((r) => r.discount_id as string)))
      })

    return () => {
      active = false
    }
  }, [userId])

  async function toggle(discountId: string) {
    if (!userId) return

    const isSaved = savedIds.has(discountId)

    // Optimistic update.
    setSavedIds((prev) => {
      const next = new Set(prev)
      if (isSaved) next.delete(discountId)
      else next.add(discountId)
      return next
    })

    const { error } = isSaved
      ? await supabase
          .from('saved_discounts')
          .delete()
          .eq('user_id', userId)
          .eq('discount_id', discountId)
      : await supabase.from('saved_discounts').insert({ user_id: userId, discount_id: discountId })

    if (error) {
      // Revert on failure.
      console.error(error)
      setSavedIds((prev) => {
        const next = new Set(prev)
        if (isSaved) next.add(discountId)
        else next.delete(discountId)
        return next
      })
    }
  }

  return { savedIds, toggle }
}
