import { describe, expect, it, vi } from 'vitest'
import { askQuestion } from './ask'
import { sseResponse } from './test-helpers'

describe('askQuestion', () => {
  it('streams tokens in order and resolves with the citations payload', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      sseResponse([
        'event: token\ndata: {"text": "The "}\n\n',
        'event: token\ndata: {"text": "answer"}\n\n',
        'event: citations\ndata: {"citations": [{"source": "eu-ai-act.pdf", "page": 12, "chunk_index": 0, "text": "obligations text", "score": 0.9}]}\n\n',
      ]),
    )
    vi.stubGlobal('fetch', fetchMock)

    const tokens: string[] = []
    const result = await askQuestion('Which obligations apply?', {
      onToken: (text) => tokens.push(text),
    })

    expect(tokens).toEqual(['The ', 'answer'])
    expect(result).toEqual({
      refused: false,
      citations: [
        {
          source: 'eu-ai-act.pdf',
          page: 12,
          chunk_index: 0,
          text: 'obligations text',
          score: 0.9,
        },
      ],
    })
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('http://localhost:8000/ask')
    expect(init.method).toBe('POST')
    expect(JSON.parse(String(init.body))).toEqual({ text: 'Which obligations apply?' })
  })

  it('resolves a refusal as its own outcome, not an error', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        sseResponse(['event: refusal\ndata: {"message": "I couldn\'t find that in the documents."}\n\n']),
      ),
    )

    const tokens: string[] = []
    const result = await askQuestion('What is the capital of France?', {
      onToken: (text) => tokens.push(text),
    })

    expect(tokens).toEqual([])
    expect(result).toEqual({ refused: true, message: "I couldn't find that in the documents." })
  })

  it('maps a 429 abuse-limit rejection to a rate_limit error with the server message', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ error: 'rate_limit', message: 'Too many questions this hour — please try again later.' }), {
          status: 429,
          headers: { 'content-type': 'application/json' },
        }),
      ),
    )

    await expect(askQuestion('Which obligations apply?')).rejects.toMatchObject({
      kind: 'rate_limit',
      message: 'Too many questions this hour — please try again later.',
    })
  })

  it('maps an in-stream error event to an error carrying its kind and message', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        sseResponse(['event: error\ndata: {"kind": "generation", "message": "All fallback models failed: llm-a:free: HTTP 429"}\n\n']),
      ),
    )

    await expect(askQuestion('Which obligations apply?')).rejects.toMatchObject({
      kind: 'generation',
      message: 'All fallback models failed: llm-a:free: HTTP 429',
    })
  })

  it('maps a network failure to a handled error the UI can render', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))

    await expect(askQuestion('Which obligations apply?')).rejects.toMatchObject({
      kind: 'network',
    })
  })

  it('signals a cold start when the response takes longer than the wakeup delay', async () => {
    vi.useFakeTimers()
    try {
      const fetchMock = vi.fn().mockImplementation(
        () =>
          new Promise<Response>((resolve) => {
            // Headers arrive only after the wakeup delay has fired — a
            // free-tier backend cold start.
            setTimeout(
              () =>
                resolve(
                  sseResponse([
                    'event: token\ndata: {"text": "hi"}\n\n',
                    'event: citations\ndata: {"citations": []}\n\n',
                  ]),
                ),
              6000,
            )
          }),
      )
      vi.stubGlobal('fetch', fetchMock)
      const onWakingUp = vi.fn()
      const pending = askQuestion('Which obligations apply?', { onWakingUp })

      await vi.advanceTimersByTimeAsync(4001)
      expect(onWakingUp).toHaveBeenCalledOnce()

      await vi.advanceTimersByTimeAsync(3000)
      await pending
      expect(onWakingUp).toHaveBeenCalledOnce() // not re-fired once headers arrived
    } finally {
      vi.useRealTimers()
    }
  })

  it('maps a malformed payload in the stream to a handled error, not a SyntaxError', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(sseResponse(['data: <html>proxy error page</html>\n\n'])),
    )

    await expect(askQuestion('Which obligations apply?')).rejects.toMatchObject({
      kind: 'internal',
      message: 'The server sent a malformed response.',
    })
  })

  it('parses CRLF-terminated frames, as an intermediary might normalize them', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        sseResponse([
          'event: token\r\ndata: {"text": "CRLF "}\r\n\r\n',
          'event: citations\r\ndata: {"citations": []}\r\n\r\n',
        ]),
      ),
    )

    const tokens: string[] = []
    const result = await askQuestion('Which obligations apply?', {
      onToken: (text) => tokens.push(text),
    })

    expect(tokens).toEqual(['CRLF '])
    expect(result).toEqual({ refused: false, citations: [] })
  })

  it('keeps the friendly rate-limit message when a 429 body is not JSON', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response('<html>blocked</html>', { status: 429, headers: { 'content-type': 'text/html' } }),
      ),
    )

    await expect(askQuestion('Which obligations apply?')).rejects.toMatchObject({
      kind: 'rate_limit',
      message: 'Too many questions — please try again later.',
    })
  })
})
