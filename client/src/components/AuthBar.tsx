import { useState } from 'react'
import type { FormEvent } from 'react'
import { supabase } from '../library/supabase'
import { useSession } from '../library/useSession'

const EDU_EMAIL = /^[^\s@]+@[^\s@]+\.edu$/i

function AuthBar() {
  const { session, loading } = useSession()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<{ kind: 'error' | 'success'; text: string } | null>(null)

  function fail(text: string) {
    setMessage({ kind: 'error', text })
    setBusy(false)
  }

  function validEduEmail() {
    if (!EDU_EMAIL.test(email.trim())) {
      fail('Please use a valid .edu email address.')
      return false
    }
    return true
  }

  async function handleSignIn(e: FormEvent) {
    e.preventDefault()
    setMessage(null)
    if (!validEduEmail()) return

    setBusy(true)
    const { error } = await supabase.auth.signInWithPassword({
      email: email.trim(),
      password,
    })
    if (error) return fail(error.message)
    setBusy(false)
  }

  async function handleSignUp() {
    setMessage(null)
    if (!validEduEmail()) return
    if (password.length < 6) return fail('Password must be at least 6 characters.')

    setBusy(true)
    const { data, error } = await supabase.auth.signUp({
      email: email.trim(),
      password,
      options: { emailRedirectTo: window.location.origin },
    })
    if (error) return fail(error.message)
    setBusy(false)
    // When email confirmation is on, no session is returned until the user confirms.
    if (!data.session) {
      setMessage({ kind: 'success', text: `Check ${email.trim()} to confirm your account.` })
    }
  }

  async function handleSignOut() {
    await supabase.auth.signOut()
  }

  if (loading) return null

  if (session?.user) {
    return (
      <div className="flex items-center gap-3 text-sm">
        <span className="text-gray-600 dark:text-gray-300">{session.user.email}</span>
        <button
          onClick={handleSignOut}
          className="rounded-lg border border-gray-300 px-3 py-1.5 font-medium text-gray-700 transition hover:bg-gray-100 dark:border-gray-600 dark:text-gray-200 dark:hover:bg-gray-800"
        >
          Sign out
        </button>
      </div>
    )
  }

  const inputClass =
    'rounded-lg border border-gray-300 px-3 py-1.5 text-sm focus:border-gray-900 focus:outline-none dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100 dark:focus:border-gray-400'

  return (
    <form onSubmit={handleSignIn} className="flex flex-col items-end gap-2">
      <div className="flex items-center gap-2">
        <input
          type="email"
          value={email}
          onChange={(e) => {
            setEmail(e.target.value)
            setMessage(null)
          }}
          placeholder="you@school.edu"
          className={inputClass}
        />
        <input
          type="password"
          value={password}
          onChange={(e) => {
            setPassword(e.target.value)
            setMessage(null)
          }}
          placeholder="Password"
          className={inputClass}
        />
        <button
          type="submit"
          disabled={busy}
          className="rounded-lg bg-gray-900 px-3 py-1.5 text-sm font-medium text-white transition hover:bg-gray-700 disabled:opacity-50"
        >
          {busy ? '…' : 'Sign in'}
        </button>
        <button
          type="button"
          onClick={handleSignUp}
          disabled={busy}
          className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 transition hover:bg-gray-100 disabled:opacity-50 dark:border-gray-600 dark:text-gray-200 dark:hover:bg-gray-800"
        >
          Sign up
        </button>
      </div>

      {message && (
        <span className={`text-xs ${message.kind === 'error' ? 'text-red-600' : 'text-emerald-600'}`}>
          {message.text}
        </span>
      )}
    </form>
  )
}

export default AuthBar
