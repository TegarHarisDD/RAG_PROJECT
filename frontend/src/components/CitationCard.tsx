import { useState } from 'react'
import type { Citation } from '../types'

/** One expandable Citation card (spec: Document, page, verbatim Chunk text
on expand). Collapsed reads "source.pdf, p. N"; expanded shows the Chunk. */
export function CitationCard({ citation }: { citation: Citation }) {
  const [open, setOpen] = useState(false)

  return (
    <div className="rounded-lg border border-zinc-200 text-sm dark:border-zinc-700">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left font-medium text-zinc-700 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-zinc-800"
      >
        <span>
          {citation.source}, p. {citation.page}
        </span>
        <span aria-hidden="true">{open ? '▾' : '▸'}</span>
      </button>
      {open && (
        <p className="border-t border-zinc-200 px-3 py-2 whitespace-pre-wrap text-zinc-600 dark:border-zinc-700 dark:text-zinc-400">
          {citation.text}
        </p>
      )}
    </div>
  )
}
