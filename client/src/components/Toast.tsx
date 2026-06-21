import { useSyncExternalStore } from 'react'

type Toast = { id: number; text: string; leaving?: boolean }

let toasts: Toast[] = []
let nextId = 1
const listeners = new Set<() => void>()

function emit() {
  listeners.forEach((l) => l())
}

export function toast(text: string) {
  const id = nextId++
  toasts = [...toasts, { id, text }]
  emit()
  setTimeout(() => dismiss(id), 3000)
}

function dismiss(id: number) {
  // Mark leaving so it can fade out, then remove after the transition.
  toasts = toasts.map((t) => (t.id === id ? { ...t, leaving: true } : t))
  emit()
  setTimeout(() => {
    toasts = toasts.filter((t) => t.id !== id)
    emit()
  }, 200)
}

function useToasts() {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb)
      return () => listeners.delete(cb)
    },
    () => toasts,
  )
}

export function ToastContainer() {
  const items = useToasts()
  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2">
      {items.map((t) => (
        <button
          key={t.id}
          onClick={() => dismiss(t.id)}
          className={`cursor-pointer rounded-lg bg-gray-900 px-4 py-2 text-left text-sm font-medium text-white shadow-lg transition-opacity duration-200 dark:bg-gray-100 dark:text-gray-900 ${
            t.leaving ? 'opacity-0' : 'opacity-100 animate-[fade-in_0.2s_ease-out]'
          }`}
        >
          {t.text}
        </button>
      ))}
    </div>
  )
}
