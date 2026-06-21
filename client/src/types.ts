export interface Discount {
  id: string
  brand: string
  description: string
  discount_percent: string
  category: string
  redemption_url: string
  expires_at: string | null
  created_at: string
  school: string | null
}
