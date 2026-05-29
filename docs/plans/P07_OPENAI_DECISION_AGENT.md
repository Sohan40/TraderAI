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

- Paper mode runs the model only on scanner candidates.
- All outcomes are traceable to prompt version and input snapshot.
- A model failure cannot cause an action.

## Codex prompt

```text
Implement only P07_OPENAI_DECISION_AGENT.

Use docs/PROMPT_CONTRACTS.md. Add a strict structured decision adapter with OpenAI Responses API
and fake tests. Configure no web-search tools. Integrate only into PAPER mode.

The model must not create quantity, order payloads, live requests or risk overrides.
Treat any parse/schema/timeout failure as REJECT.
```
