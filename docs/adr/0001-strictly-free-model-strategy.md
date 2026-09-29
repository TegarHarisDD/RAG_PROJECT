# Strictly-free OpenRouter model strategy with a config fallback chain

The demo is a public portfolio piece that must cost $0 to run, so both embedding and LLM calls use OpenRouter `:free` model variants. Free variants rotate, disappear, and share one account-wide daily counter (50 requests/day without purchase history), so the mitigation lives in code and config: model IDs are a config-ordered fallback list tried in sequence, never hardcoded, plus a clear UI error with retry when every model fails. Application-level limits (5 questions/hour/IP, 500-char max, ~40/day global stop) keep real traffic under the provider cap so a visitor's first question always has quota left. Swapping to a paid model later is a config edit, not a code change — no credits will be purchased for the MVP.

## Considered Options

- *Paid cheap LLM (~$0.10/M in, $0.40/M out)*: more reliable, rejected because the owner set a strictly-$0 budget.
- *One-time $10 credit top-up*: raises the free daily limit to 1,000 req/day and stays $0/month, rejected for MVP to honor the $0 rule; can be adopted any day without code changes.

## Consequences

- The live demo can fail during review if free models are rate-limited or rotate away; the UI must communicate this gracefully rather than looking broken.
- Embedding-model quality is unproven (small free variants); the Eval Set is the gate, and swapping embedding models means a full re-ingest and re-index (see ADR-0002).
