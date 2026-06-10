# Structured Decision Agent

P07 evaluates persisted P05 `CANDIDATE` signals and stores structured
recommendations. It is disabled by default and runs only through the
operator-protected decision API unless P07.1 market-ops evaluation is
explicitly enabled.

Safety boundaries:

- no broker, order, WebSocket, risk, or paper-replay calls;
- no quantity, broker payload, or risk-limit authority;
- no web search, file search, retrieval, function tools, browser tools, MCP, or
  external facts;
- malformed, prohibited, insufficient, timed-out, or failed output persists as
  a failed model run plus safe `REJECT`;
- recommendations only decorate P06 reports and never gate replay.

The fake adapter is the default and returns deterministic `WATCH`. The OpenAI
adapter uses strict Responses API parsing and sends no tools. Real evaluation
requires an operator to enable P07, select adapter `openai`, configure a model,
and provide `OPENAI_API_KEY` outside tracked files.

P07.1 can evaluate bounded, newly persisted scanner candidates after a
market-ops batch. This path is candidate-only, idempotent, disabled by default,
and notification/report-only. Sanitized raw model output remains in
`model_runs`; normalized safe output remains in `recommendations`.
