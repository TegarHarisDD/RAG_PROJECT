# RAG Portfolio Demo

A public web app where visitors ask questions about a fixed set of documents and receive streamed answers with citations. The domain covers ingestion, retrieval, generation, and evaluation of that one pipeline.

## Language

### Corpus and content

**Corpus**:
The single, fixed, publicly licensed document set the demo answers from. The corpus never changes at runtime; there are no user uploads.
_Avoid_: knowledge base, database, data set, index

**Document**:
One source file (PDF) in the corpus, identified by its source name and page numbers. The unit visitors see named in a citation.
_Avoid_: file, resource

**Chunk**:
A contiguous span of a Document, produced by splitting it for embedding. The unit that is retrieved and shown verbatim in a citation snippet.
_Avoid_: passage, segment, fragment, snippet (a snippet is the visible excerpt of a Chunk, not the stored unit)

### Retrieval and answering

**Question**:
What a visitor types into the chat: one turn, length-capped, no history dependence for retrieval.
_Avoid_: query, prompt (a Prompt is the assembled instruction sent to the LLM, not the visitor's input)

**Prompt**:
The assembled message (system rules + Question + retrieved Chunks) sent to the LLM.
_Avoid_: request, context

**Citation**:
The pointer shown with an answer naming the Document, page, and the verbatim Chunk text the answer drew from.
_Avoid_: source, reference (alone — "citations payload" is fine as compound)

**Refusal**:
The explicit "I couldn't find that in the documents" answer, produced when the retrieved Chunks don't support answering. A correct Refusal is an eval pass, not a failure.
_Avoid_: rejection, "I don't know" fallback

### Evaluation

**Eval Question**:
A curated Question with a known expected answer or expected Refusal, used to measure accuracy offline before changes ship.
_Avoid_: test case, golden question

**Eval Set**:
The collection of ~50 Eval Questions (in-scope and out-of-scope) backing the README results table.
_Avoid_: benchmark, test suite
