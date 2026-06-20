import AuthBar from './components/AuthBar'
import DiscountGrid from './components/DiscountGrid'

export default function App() {
  return (
    <div className="min-h-screen bg-gray-50">
      <header className="border-b border-gray-200 bg-white">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-4">
          <h1 className="text-xl font-bold text-gray-900">Student Discounts</h1>
          <AuthBar />
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-6 py-8">
        <DiscountGrid />
      </main>
    </div>
  )
}
