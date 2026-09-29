import type { Citation } from '../types'
import { CitationCard } from './CitationCard'

/** One conversation turn in the session-only history. */
export type Message =
  | { id: number; role: 'user'; text: string }
  | {
      id: number
      role: 'assistant'
      /** pending: retrieval under way; streaming/done: text has arrived. */
      phase: 'pending' | 'streaming' | 'done'
      text: string
      refused?: boolean
      citations?: Citation[]
      error?: string
      /** The Question to re-ask when the visitor hits Retry on this error. */
      retryQuestion?: string
    }

export type AssistantMessage = Extract<Message, { role: 'assistant' }>

/** The bubble for one turn: the visitor's Question or the assistant's answer
with its loading phase, Refusal styling, or error + retry. */
export function ChatMessage({
  message,
  onRetry,
}: {
  message: Message
  onRetry?: (text: string) => void
}) {
  if (message.role === 'user') {
    return (
      <div className="flex justify-end">
        <p className="max-w-[85%] rounded-2xl rounded-br-md bg-sky-600 px-4 py-2 text-white sm:max-w-[70%]">
          {message.text}
        </p>
      </div>
    )
  }

  if (message.error !== undefined) {
    return (
      <div
        role="alert"
        className="max-w-[85%] rounded-2xl rounded-bl-md border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800 sm:max-w-[70%] dark:border-red-900 dark:bg-red-950 dark:text-red-300"
      >
        <p>{message.error}</p>
        {onRetry && message.retryQuestion && (
          <button
            type="button"
            onClick={() => onRetry(message.retryQuestion ?? '')}
            className="mt-2 rounded-lg bg-red-600 px-3 py-1.5 font-medium text-white hover:bg-red-700"
          >
            Retry
          </button>
        )}
      </div>
    )
  }

  return (
    <div
      className={
        message.refused
          ? 'max-w-[85%] rounded-2xl rounded-bl-md border border-amber-300 bg-amber-50 px-4 py-3 sm:max-w-[70%] dark:border-amber-800 dark:bg-amber-950'
          : 'max-w-[85%] rounded-2xl rounded-bl-md bg-zinc-200 px-4 py-3 sm:max-w-[70%] dark:bg-zinc-800'
      }
    >
      {message.phase === 'pending' ? (
        <p className="animate-pulse text-sm text-zinc-500 dark:text-zinc-400">
          Searching the documents…
        </p>
      ) : (
        <p className="whitespace-pre-wrap">{message.text}</p>
      )}
      {message.citations && message.citations.length > 0 && (
        <div className="mt-3 space-y-1.5">
          {message.citations.map((citation) => (
            <CitationCard key={`${citation.source}-${citation.chunk_index}`} citation={citation} />
          ))}
        </div>
      )}
    </div>
  )
}
