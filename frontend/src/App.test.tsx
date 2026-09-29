import { act, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { sseResponse } from './test-helpers'

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn())
  localStorage.clear()
  document.documentElement.classList.remove('dark')
})

describe('landing page', () => {
  it('states the corpus, its attribution, and the fixed-corpus limit', () => {
    render(<App />)

    expect(screen.getByText(/Regulation \(EU\) 2024\/1689/)).toBeInTheDocument()
    expect(screen.getByText(/official EU publication/i)).toBeInTheDocument()
    expect(screen.getByText(/CC BY 4\.0/)).toBeInTheDocument()
    expect(screen.getByText(/no uploads/i)).toBeInTheDocument()
  })
})

/** A fresh happy-path stream per call — a Response body can be read once. */
const happyStream = () =>
  sseResponse([
    'event: token\ndata: {"text": "Providers must "}\n\n',
    'event: token\ndata: {"text": "comply."}\n\n',
    'event: citations\ndata: {"citations": [{"source": "eu-ai-act.pdf", "page": 12, "chunk_index": 0, "text": "obligations text", "score": 0.9}]}\n\n',
  ])

describe('asking', () => {
  it('asks an example question instantly and streams the answer with its citation', async () => {
    const user = userEvent.setup()
    const fetchMock = vi.fn().mockResolvedValue(happyStream())
    vi.stubGlobal('fetch', fetchMock)
    render(<App />)

    await user.click(screen.getByRole('button', { name: /obligations apply to providers/i }))

    expect(await screen.findByText('Providers must comply.')).toBeInTheDocument()
    expect(screen.getByText('eu-ai-act.pdf, p. 12')).toBeInTheDocument()
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toContain('/ask')
    expect(JSON.parse(String(init.body))).toEqual({
      text: 'Which obligations apply to providers of high-risk AI systems?',
    })
  })

  it('expands a citation card to show the verbatim Chunk text', async () => {
    const user = userEvent.setup()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(happyStream()))
    render(<App />)

    await user.click(screen.getByRole('button', { name: /obligations apply to providers/i }))
    const card = await screen.findByRole('button', { name: /eu-ai-act\.pdf, p\. 12/ })
    expect(screen.queryByText('obligations text')).not.toBeInTheDocument()

    await user.click(card)

    expect(screen.getByText('obligations text')).toBeInTheDocument()
  })

  it('renders a refusal as its own honest message, with no citations', async () => {
    const user = userEvent.setup()
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        sseResponse(['event: refusal\ndata: {"message": "I couldn\'t find that in the documents."}\n\n']),
      ),
    )
    render(<App />)

    await user.click(screen.getByRole('button', { name: /capital of France/i }))

    expect(await screen.findByText("I couldn't find that in the documents.")).toBeInTheDocument()
    expect(screen.queryByText(/p\. \d+/)).not.toBeInTheDocument()
  })

  it('renders a failure with a retry button that asks the same question again', async () => {
    const user = userEvent.setup()
    const failing = () =>
      sseResponse(['event: error\ndata: {"kind": "generation", "message": "All fallback models failed."}\n\n'])
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(failing())
      .mockResolvedValueOnce(happyStream())
    vi.stubGlobal('fetch', fetchMock)
    render(<App />)

    await user.click(screen.getByRole('button', { name: /obligations apply to providers/i }))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('All fallback models failed.')

    await user.click(screen.getByRole('button', { name: 'Retry' }))

    expect(await screen.findByText('Providers must comply.')).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledTimes(2)
    const [, secondCall] = fetchMock.mock.calls as [[string, RequestInit], [string, RequestInit]]
    expect(JSON.parse(String(secondCall[1].body))).toEqual({
      text: 'Which obligations apply to providers of high-risk AI systems?',
    })
  })

  it('asks a typed question via the composer (Enter to submit)', async () => {
    const user = userEvent.setup()
    const fetchMock = vi.fn().mockResolvedValue(happyStream())
    vi.stubGlobal('fetch', fetchMock)
    render(<App />)

    await user.type(screen.getByLabelText(/your question/i), 'When does the Act apply?{Enter}')

    expect(await screen.findByText('Providers must comply.')).toBeInTheDocument()
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toContain('/ask')
    expect(JSON.parse(String(init.body))).toEqual({ text: 'When does the Act apply?' })
  })

  it('does not submit while an IME composition is being confirmed', async () => {
    const user = userEvent.setup()
    const fetchMock = vi.fn().mockResolvedValue(happyStream())
    vi.stubGlobal('fetch', fetchMock)
    render(<App />)

    const textarea = screen.getByLabelText(/your question/i)
    await user.type(textarea, 'いつ適用される？')
    // Enter confirming a composition candidate: not a submit.
    textarea.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'Enter', isComposing: true, bubbles: true, cancelable: true }),
    )

    expect(fetchMock).not.toHaveBeenCalled()

    // The same key after the composition ended submits.
    fireEvent.keyDown(textarea, { key: 'Enter' })
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('shows the server-waking-up state during a free-tier cold start', async () => {
    vi.useFakeTimers()
    try {
      vi.stubGlobal(
        'fetch',
        vi.fn().mockImplementation(
          () =>
            new Promise<Response>((resolve) => {
              // A Render free-tier cold start: headers only after ~a minute.
              setTimeout(() => resolve(happyStream()), 6000)
            }),
        ),
      )
      render(<App />)

      // fireEvent (not user-event) here: the pending fetch would otherwise
      // stall user-event's internal waits under fake timers. act() flushes
      // the React state updates the timers trigger.
      act(() => {
        fireEvent.click(screen.getByRole('button', { name: /obligations apply to providers/i }))
      })
      expect(screen.getByText('Searching the documents…')).toBeInTheDocument()

      await act(async () => {
        await vi.advanceTimersByTimeAsync(4001)
      })
      expect(screen.getByRole('status')).toHaveTextContent(/server is waking up/i)

      await act(async () => {
        await vi.runAllTimersAsync() // the cold start ends; the stream completes
      })
      expect(screen.getByText('Providers must comply.')).toBeInTheDocument()
      expect(screen.queryByRole('status')).not.toBeInTheDocument()
    } finally {
      vi.useRealTimers()
    }
  })
})

describe('dark mode', () => {
  it('toggles the dark class on <html> and remembers the choice', async () => {
    const user = userEvent.setup()
    render(<App />)
    const toggle = screen.getByRole('button', { name: 'Toggle dark mode' })

    await user.click(toggle)

    expect(document.documentElement).toHaveClass('dark')
    expect(localStorage.getItem('theme')).toBe('dark')

    await user.click(toggle)

    expect(document.documentElement).not.toHaveClass('dark')
    expect(localStorage.getItem('theme')).toBe('light')
  })
})
