# Codex Workflow

## Branching model

Implement one plan in one feature branch:

```text
main
  ├─ plan/p01-bootstrap
  ├─ plan/p02-gcp-infra
  └─ ...
```

Do not combine execution-gateway or live-arming work with unrelated UI or refactoring.

## Prompt template

Paste this into Codex for each plan:

```text
Read AGENTS.md, docs/ARCHITECTURE.md, docs/RISK_RULES.md and docs/plans/<PLAN_FILE>.md completely.

Implement only the requested plan. Do not implement later-plan functionality.

Safety requirements:
- Preserve TRADING_MODE=OFF and LIVE_ARMED=false defaults.
- Never insert real secrets.
- Mock all broker and OpenAI calls in tests.
- Never create an AI-to-broker direct order path.
- Do not weaken risk rules.

Complete the plan's deliverables and acceptance criteria.
Run tests, linting and type checks.
At the end, report changed files, commands run, test results and remaining risks.
```

## Review checklist after each Codex run

- Does the diff stay inside the plan scope?
- Did it add secrets or access-token logging?
- Did it introduce any possible real broker call in tests?
- Did it bypass the risk engine?
- Are migrations reversible/reviewable?
- Are error cases logged and persisted where required?
- Are all new paths covered by tests?
- Does deployment still start with trading OFF?

## Recommended commits

```text
docs: add product scope and safety constraints
feat: bootstrap FastAPI application and storage
infra: add GCP VM deployment and secret loading
feat: add Kite authentication session lifecycle
feat: ingest Kite market data and completed candles
feat: compute indicators and scanner signals
feat: add paper trading journal engine
feat: add structured OpenAI decision adapter
feat: enforce deterministic risk checks
feat: add locked execution gateway
feat: add arming dashboard and kill switch
feat: add monitoring and daily analytics
test: validate micro-live rollout gates
```
