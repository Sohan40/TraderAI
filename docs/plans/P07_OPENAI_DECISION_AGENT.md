# P07 — Structured OpenAI Trade Decision Agent


## Objective

Add an OpenAI decision layer that can approve/veto scanner candidates using only structured Kite-derived technical context. It cannot place orders or create quantity.

## Deliverables

- Decision-agent interface and fake adapter.
- OpenAI Responses API adapter with:
  - strict structured output schema defined in `docs/PROMPT_CONTRACTS.md`;
  - configurable model name;
  - timeouts/retries bounded;
  - `store: false` where supported/configured for private account context;
  - no web-search tool and no external retrieval.
- Prompt versioning.
- Input sanitization and hash/persistence in `model_runs`.
- Output validation:
  - enum allowlist;
  - no quantity/broker payload;
  - reject on invalid JSON, timeout, missing data or external-fact claim.
- Integration into PAPER pipeline only.
- Endpoint/report to compare scanner signals with model verdicts.

## Safety requirements

- The agent has no broker tool/function.
- The agent never receives a capability to write orders.
- `ELIGIBLE` means “send to risk engine” in later plans, not “trade.”
- Model output cannot change configured risk limits.

## Tests

- Fake model eligible/watch/reject outputs.
- Malformed and prohibited-field outputs become rejection.
- Timeout/no-key/no-model failure becomes no-trade.
- Verify no web tool appears in request configuration.
- PAPER pipeline persists model run and verdict.

## Acceptance criteria

- Operator-triggered evaluation runs only on persisted scanner candidates.
- All outcomes are traceable to prompt version and input snapshot.
- A model failure cannot cause an action.
- Paper replay remains deterministic and unchanged; existing recommendations
  appear only as read-only report comparison.

## Operator validation

P07 defaults to the deterministic fake adapter:

```text
OPENAI_DECISION_ENABLED=false
OPENAI_DECISION_ADAPTER=fake
OPENAI_DECISION_STORE=false
```

After explicitly enabling fake mode, evaluate a stored candidate:

```text
scripts/traderctl decision-status
scripts/traderctl decision-evaluate --signal-id 15
scripts/traderctl decision-recommendations --limit 20
```

For a deliberate real test, configure `OPENAI_DECISION_ADAPTER=openai`,
`OPENAI_MODEL`, and `OPENAI_API_KEY` in an ignored runtime env file, then
force-recreate the API outside market hours. `WATCH` or `REJECT` is acceptable
for historical signal 15 because its stored quote/spread context is incomplete.
The model is never called by market-ops and never starts paper replay.

## Codex prompt

```text
Implement only P07_OPENAI_DECISION_AGENT.

Use docs/PROMPT_CONTRACTS.md. Add a strict structured decision adapter with OpenAI Responses API
and fake tests. Configure no web-search tools. Integrate only into PAPER mode.

The model must not create quantity, order payloads, live requests or risk overrides.
Treat any parse/schema/timeout failure as REJECT.
```
