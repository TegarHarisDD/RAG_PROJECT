/** The ask client: POST /ask streamed as Server-Sent Events, parsed by hand.

The backend cannot be consumed with ``EventSource`` (it requires POST), so the
stream is read off ``fetch``'s body and the named events — ``token``,
``refusal``, ``citations``, ``error`` — are parsed from the wire format the
same way the backend tests assert it (backend ``tests/test_ask.py``).
*/
import type { AskResult, Citation } from './types'

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

export interface AskCallbacks {
  onToken?: (text: string) => void
  /** Fired once when the backend hasn't answered after WAKEUP_DELAY_MS — the
  free tier sleeps after 15 min idle and takes ~1 min to wake (spec). */
  onWakingUp?: () => void
}

const WAKEUP_DELAY_MS = 4000

/** One ask turn: streams answer tokens through ``onToken`` and resolves with
the turn's outcome. Rejects with an ``AskError`` for anything the UI renders
as a failure: abuse limits, in-stream errors, network faults. */
export async function askQuestion(
  question: string,
  { onToken, onWakingUp }: AskCallbacks = {},
): Promise<AskResult> {
  let response: Response
  const wakeupTimer = onWakingUp
    ? setTimeout(onWakingUp, WAKEUP_DELAY_MS)
    : undefined
  try {
    response = await fetch(`${API_URL}/ask`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: question }),
    })
  } catch {
    // The backend being down (cold start, crash, CORS) is a handled state —
    // the UI shows a "server unreachable" message with retry, never a trace.
    clearTimeout(wakeupTimer)
    throw new AskError('network', 'Could not reach the server. It may be waking up — try again.')
  }
  // Headers have arrived; the wake-up window is over (fired or not).
  clearTimeout(wakeupTimer)

  if (!response.ok) {
    // Abuse limits arrive before the stream starts: an explicit 429 naming
    // which limit bit (rate_limit | daily_limit) plus a readable message. The
    // body may not be JSON (a proxy's block page), so the friendly default
    // survives a failed parse.
    if (response.status === 429) {
      let message = 'Too many questions — please try again later.'
      try {
        const body = (await response.json()) as { message?: string }
        if (typeof body.message === 'string') message = body.message
      } catch {
        // keep the default message
      }
      throw new AskError('rate_limit', message)
    }
    if (response.status === 422) {
      throw new AskError('internal', 'The question was rejected — it may be too long or empty.')
    }
    throw new AskError('internal', `The server rejected the question (HTTP ${response.status}).`)
  }

  if (!response.body) {
    throw new AskError('internal', 'The server sent no response body.')
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let result: AskResult | null = null

  // SSE frames are separated by blank lines; a chunk boundary can split a
  // frame, so only complete trailing frames are consumed from the buffer.
  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')
      const frames = buffer.split('\n\n')
      buffer = frames.pop() ?? ''
      for (const frame of frames) {
        const event = parseFrame(frame)
        if (!event) continue
        if (event.name === 'token') {
          onToken?.((event.data as { text: string }).text)
        } else if (event.name === 'refusal') {
          result = { refused: true, message: (event.data as { message: string }).message }
        } else if (event.name === 'citations') {
          result = {
            refused: false,
            citations: (event.data as { citations: Citation[] }).citations,
          }
        } else if (event.name === 'error') {
          const { kind, message } = event.data as { kind: AskErrorKind; message: string }
          throw new AskError(kind, message)
        }
      }
    }
  } finally {
    // An in-stream throw must not leave the connection open against the
    // free-tier backend's connection budget.
    await reader.cancel().catch(() => {})
  }

  if (!result) {
    throw new AskError('internal', 'The answer stream ended without a result.')
  }
  return result
}

function parseFrame(frame: string): { name: string; data: unknown } | null {
  let name = 'message'
  const dataLines: string[] = []
  for (const line of frame.split('\n')) {
    const field = line.replace(/\r$/, '') // tolerate a stray CR from the wire
    if (field.startsWith('event: ')) name = field.slice('event: '.length)
    else if (field.startsWith('data: ')) dataLines.push(field.slice('data: '.length))
  }
  if (dataLines.length === 0) return null
  try {
    // Multi-line data fields are one payload joined by newlines (SSE spec).
    return { name, data: JSON.parse(dataLines.join('\n')) }
  } catch {
    throw new AskError('internal', 'The server sent a malformed response.')
  }
}

/** A failure the UI renders as a handled error state, never a stack trace. */
export type AskErrorKind = 'provider' | 'generation' | 'store' | 'internal' | 'rate_limit' | 'network'

export class AskError extends Error {
  kind: AskErrorKind

  constructor(kind: AskErrorKind, message: string) {
    super(message)
    this.name = 'AskError'
    this.kind = kind
  }
}
