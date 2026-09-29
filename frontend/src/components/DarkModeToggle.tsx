import { useEffect, useState } from 'react'

/** Dark mode toggle (spec MVP decision). The `dark` class is set before
first paint by the inline script in index.html (OS preference or the
visitor's remembered choice); this toggle only persists a choice the
visitor actually made, so OS-preference followers keep following. */
export function DarkModeToggle() {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains('dark'))

  useEffect(() => {
    document.documentElement.classList.toggle('dark', dark)
  }, [dark])

  const toggle = () => {
    setDark((value) => {
      const next = !value
      localStorage.setItem('theme', next ? 'dark' : 'light')
      return next
    })
  }

  return (
    <button
      type="button"
      aria-label="Toggle dark mode"
      aria-pressed={dark}
      onClick={toggle}
      className="rounded-lg p-2 text-xl text-zinc-600 hover:bg-zinc-200 dark:text-zinc-300 dark:hover:bg-zinc-800"
    >
      {dark ? '☀️' : '🌙'}
    </button>
  )
}
