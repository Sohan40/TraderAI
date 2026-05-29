# P00 — Product Scope and Prerequisites


## Objective

Convert the idea into explicit, reviewable constraints before code begins. At the end of this plan there is no trading code; there is a repository with agreed safety rules, selected strategy scope, required accounts and a purchase/deployment checklist.

## Deliverables

- Repository initialized and this planning pack committed.
- A local `docs/DECISIONS.md` that records:
  - personal-use-only scope;
  - approximately ₹2,000 experiment allocation;
  - live start caps from `docs/RISK_RULES.md`;
  - long-only, cash-instrument, intraday-only MVP;
  - no OpenAI web search;
  - Kite Connect direct integration;
  - GCP VM/static IP deployment;
  - daily login/arming expectation.
- A `docs/WATCHLIST_POLICY.md` defining how symbols are allowlisted and excluded.
- A `docs/INCIDENT_LOG_TEMPLATE.md` for any live or paper operational fault.
- `.env.example` reviewed with no real secrets.
- Kite/GCP/OpenAI prerequisites checklist completed manually.

## Manual prerequisites checklist

- Active Zerodha account and required authentication enabled.
- Kite Connect developer app/subscription decision reviewed against current official pricing and entitlements.
- Google Cloud billing/project available.
- GitHub repository created.
- Codex available in the local development workflow.
- Personal decision: accept that the ₹2,000 experiment may lose money and operating costs may exceed returns.

## Watchlist policy starter constraints

Define a tiny allowlist, not a broad scanner universe. Initially require:

- NSE cash-equity/ETF only;
- no penny/circuit-prone/illiquid names;
- price affordable under the ₹500 first-trade notional;
- spread and volume checked by scanner at runtime;
- symbol added manually with a written rationale.

Do not hardcode final symbols in plan documents; decide them after reviewing live liquidity and affordable price.

## Acceptance criteria

- The scope cannot be misunderstood as public advice or a multi-user platform.
- A reviewer can read the decisions and identify all prohibited live behaviours.
- No real credentials are in git.
- All later plan files are present and ordered.

## Codex prompt

```text
Read AGENTS.md, docs/RISK_RULES.md and docs/plans/P00_PRODUCT_SCOPE_AND_PREREQUISITES.md.

Create only the documentation and repository scaffolding described in P00:
docs/DECISIONS.md, docs/WATCHLIST_POLICY.md and docs/INCIDENT_LOG_TEMPLATE.md.
Preserve all safety constraints.
Do not create broker, AI or live trading code.
Commit-ready output only; report files created and any unresolved manual prerequisites.
```
