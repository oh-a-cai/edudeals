import AuthBar from './components/AuthBar'
import DiscountGrid from './components/DiscountGrid'
import ThemeToggle from './components/ThemeToggle'
import { ToastContainer } from './components/Toast'
import ResetPassword from './components/ResetPassword'

export default function App() {
  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-950">
      <header className="border-b border-gray-200 bg-white dark:border-gray-800 dark:bg-gray-900">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-4">
          <h1 className="text-xl font-bold text-gray-900 dark:text-gray-100">Student Discounts</h1>
          <div className="flex items-start gap-3">
            <AuthBar />
            <ThemeToggle />
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-6 py-8">
        <DiscountGrid />
      </main>

      <ToastContainer />
      <ResetPassword />
    </div>
  )
}
