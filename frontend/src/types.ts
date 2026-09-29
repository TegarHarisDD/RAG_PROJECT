/** Shared domain vocabulary (see CONTEXT.md) for the chat UI. */

/** The pointer shown with an answer: Document, page, verbatim Chunk text. */
export interface Citation {
  source: string
  page: number
  chunk_index: number
  text: string
  score: number
}

/** How one ask turn resolved: a cited answer or an honest Refusal. */
export type AskResult =
  | { refused: false; citations: Citation[] }
  | { refused: true; message: string }
