import { useCallback, useRef, useState } from 'react'
import { askQuestion } from './ask'
import { ChatMessage, type AssistantMessage, type Message } from './components/ChatMessage'
import { DarkModeToggle } from './components/DarkModeToggle'

/** The question cap is the backend's abuse config (spec: 500 chars); kept in
step manually — a longer question is rejected server-side with a 422. */
const QUESTION_MAX_CHARS = 500

/** The landing-page Questions a visitor can ask with zero effort (spec:
3–5 clickable example Questions). The last is deliberately out of scope so a
visitor can see the honest Refusal without typing anything. */
const EXAMPLE_QUESTIONS = [
  'Which obligations apply to providers of high-risk AI systems?',
  'When does the EU AI Act apply?',
  'What are the penalties for non-compliance?',
  'What risks does the EU AI Act classify as unacceptable?',
  'What is the capital of France?',
]

/** The Corpus notice on the landing page (spec: corpus + attribution + fixed
corpus limit). */
function CorpusNotice() {
  return (
    <section className="text-center">
      <h1 className="text-3xl font-bold tracking-tight text-zinc-900 sm:text-4xl dark:text-zinc-50">
        Ask the EU AI Act
      </h1>
      <p className="mx-auto mt-4 max-w-xl text-zinc-600 dark:text-zinc-400">
        This demo answers only from one fixed Corpus:{' '}
        <span className="font-medium text-zinc-800 dark:text-zinc-200">
          Regulation (EU) 2024/1689 — the EU AI Act
        </span>
        . There are no uploads; questions outside the documents get an honest refusal.
      </p>
      <p className="mt-3 text-sm text-zinc-500 dark:text-zinc-500">
        Source: official EU publication (OJ L, 12.7.2024) — licensed{' '}
        <a
          className="underline underline-offset-2 hover:text-zinc-700 dark:hover:text-zinc-300"
          href="https://eur-lex.europa.eu/eli/reg/2024/1689/oj"
          target="_blank"
          rel="noreferrer"
        >
          CC BY 4.0
        </a>{' '}
        / reusable per Decision 2011/833/EU.
      </p>
    </section>
  )
}

export default function App() {
  const [messages, setMessages] = useState<Message[]>([])
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [wakingUp, setWakingUp] = useState(false)
  const nextId = useRef(1)

  const ask = useCallback(
    async (question: string) => {
      setBusy(true)
      setWakingUp(false)
      setDraft('')
      const userMessage: Message = { id: nextId.current++, role: 'user', text: question }
      const answerId = nextId.current++
      const answerMessage: Message = {
        id: answerId,
        role: 'assistant',
        phase: 'pending',
        text: '',
      }
      setMessages((prev) => [...prev, userMessage, answerMessage])

      // The one assistant-message patch path for both streaming appends and
      // final outcomes, so the two can't drift apart.
      const patchAnswer = (
        transform: (message: AssistantMessage) => AssistantMessage,
      ) =>
        setMessages((prev) =>
          prev.map((message) =>
            message.id === answerId && message.role === 'assistant'
              ? transform(message)
              : message,
          ),
        )

      try {
        const result = await askQuestion(question, {
          onToken: (text) =>
            patchAnswer((message) => ({
              ...message,
              phase: 'streaming',
              text: message.text + text,
            })),
          onWakingUp: () => setWakingUp(true),
        })
        if (result.refused) {
          patchAnswer((message) => ({ ...message, phase: 'done', text: result.message, refused: true }))
        } else {
          // The answer text is the tokens accumulated via onToken; the
          // citations payload terminates the stream (spec user story 14).
          patchAnswer((message) => ({ ...message, phase: 'done', citations: result.citations }))
        }
      } catch (error) {
        patchAnswer((message) => ({
          ...message,
          phase: 'done',
          error: error instanceof Error ? error.message : 'Something went wrong.',
          retryQuestion: question,
        }))
      } finally {
        setBusy(false)
        setWakingUp(false)
      }
    },
    [],
  )

  return (
    <div className="flex min-h-screen flex-col bg-zinc-50 text-zinc-900 dark:bg-zinc-950 dark:text-zinc-100">
      <header className="flex items-center justify-end p-4">
        <DarkModeToggle />
      </header>
      <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col px-4 pb-6">
        <CorpusNotice />

        {wakingUp && (
          <p role="status" className="mt-6 rounded-lg bg-zinc-200 px-4 py-2 text-center text-sm text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
            The free-tier server is waking up — this can take about a minute.
          </p>
        )}

        {messages.length > 0 && (
          <div className="mt-8 flex flex-1 flex-col gap-3" aria-label="Conversation">
            {messages.map((message) => (
              <ChatMessage key={message.id} message={message} onRetry={ask} />
            ))}
          </div>
        )}

        {messages.length === 0 && (
          <div className="mt-8 grid gap-2 sm:grid-cols-2">
            {EXAMPLE_QUESTIONS.map((question) => (
              <button
                key={question}
                type="button"
                disabled={busy}
                onClick={() => ask(question)}
                className="rounded-xl border border-zinc-300 px-4 py-3 text-left text-sm text-zinc-700 hover:border-zinc-400 hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:text-zinc-300 dark:hover:border-zinc-600 dark:hover:bg-zinc-900"
              >
                {question}
              </button>
            ))}
          </div>
        )}

        <form
          className="mt-8 flex items-end gap-2"
          onSubmit={(event) => {
            event.preventDefault()
            const question = draft.trim()
            if (question && !busy) ask(question)
          }}
        >
          <div className="flex-1">
            <label htmlFor="question" className="sr-only">
              Your question
            </label>
            <textarea
              id="question"
              rows={1}
              value={draft}
              maxLength={QUESTION_MAX_CHARS}
              disabled={busy}
              placeholder="Ask about the EU AI Act…"
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                // Enter submits (Shift+Enter is a newline); Enter that only
                // confirms an IME composition must not.
                if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
                  event.preventDefault()
                  event.currentTarget.form?.requestSubmit()
                }
              }}
              className="w-full resize-none rounded-xl border border-zinc-300 px-3 py-2 dark:border-zinc-700 dark:bg-zinc-900"
            />
            <p className="mt-1 text-right text-xs text-zinc-400">
              {draft.length}/{QUESTION_MAX_CHARS}
            </p>
          </div>
          <button
            type="submit"
            disabled={busy || draft.trim().length === 0}
            className="rounded-xl bg-sky-600 px-4 py-2 font-medium text-white hover:bg-sky-700 disabled:opacity-50"
          >
            Ask
          </button>
        </form>
      </main>
    </div>
  )
}
