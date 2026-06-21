import { useEffect, useRef, useState } from 'react'

interface Option<T extends string> {
  value: T
  label: string
}

interface SortDropdownProps<T extends string> {
  value: T
  options: Option<T>[]
  onChange: (value: T) => void
  label?: string
}

function SortDropdown<T extends string>({ value, options, onChange, label = 'Sort' }: SortDropdownProps<T>) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  // Close on outside click or Escape.
  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const current = options.find((o) => o.value === value)

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={label}
        className="flex w-full items-center justify-between gap-2 rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-gray-900 focus:outline-none dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100 dark:focus:border-gray-400 sm:w-48"
      >
        {current?.label ?? label}
        <svg viewBox="0 0 20 20" className={`h-4 w-4 transition ${open ? 'rotate-180' : ''}`} fill="currentColor">
          <path fillRule="evenodd" d="M5.25 7.5 10 12.25 14.75 7.5z" clipRule="evenodd" />
        </svg>
      </button>

      {open && (
        <ul
          role="listbox"
          className="absolute z-40 mt-1 w-full overflow-hidden rounded-lg border border-gray-200 bg-white shadow-lg dark:border-gray-700 dark:bg-gray-900"
        >
          {options.map((o) => (
            <li key={o.value}>
              <button
                type="button"
                role="option"
                aria-selected={o.value === value}
                onClick={() => {
                  onChange(o.value)
                  setOpen(false)
                }}
                className={`block w-full px-3 py-2 text-left text-sm transition hover:bg-gray-100 dark:hover:bg-gray-800 ${
                  o.value === value
                    ? 'font-medium text-gray-900 dark:text-gray-100'
                    : 'text-gray-600 dark:text-gray-300'
                }`}
              >
                {o.label}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export default SortDropdown
