# Risk Rules and Live-Safety Contract

## Purpose

This document defines rules that remain deterministic even though candidate evaluation uses an AI model. Live autonomy means the system automatically accepts or rejects trades according to these controls after the owner explicitly arms a trading session.

## Default experimental allocation

| Control | Initial live value |
|---|---:|
| Allocated experiment capital | ₹2,000 |
| Maximum live trade notional | ₹500 |
| Maximum planned rupee risk per trade | ₹10 |
| Maximum daily realised plus protected open loss | ₹20 |
| Maximum trades per day | 1 |
| Maximum concurrent positions | 1 |
| Minimum unused reserve | ₹1,000 |
| Direction | Long only |
| Instrument class | Allowlisted NSE cash instruments only |
| Entry | Limit orders only |
| Overnight carry | Forbidden in MVP |
| Entry cutoff | 14:30 IST |
| Mandatory force-flat time | 15:10 IST |

These are risk caps, not performance assumptions. Do not increase any cap until the live rollout gates in `P12_MICRO_LIVE_ROLLOUT.md` pass.

## Absolute prohibitions in MVP

- Futures, options and commodities.
- Short entry trades.
- Overnight positions.
- Averaging down.
- Martingale or loss-recovery sizing.
- More than one open position.
- More than one live entry per day at initial limits.
- Live order creation from raw model output.
- Market orders for entry during initial live rollout.
- Trade entry when protective-stop placement is not available/healthy.

## Risk engine responsibilities

Before creating an approved order instruction, the risk engine verifies:

1. Valid authenticated broker session.
2. Mode is LIVE and session is armed for the current timestamp, or PAPER when simulating.
3. Kill switch inactive.
4. Live data heartbeat and candidate data are not stale.
5. Candidate symbol is in allowlist and instrument metadata is current.
6. Candidate strategy is enabled for the current mode.
7. AI verdict passes schema validation and is eligible.
8. Current open positions and pending entries do not violate limits.
9. Daily trade count and daily loss caps have not been hit.
10. Entry is before cutoff and exit can be managed before force-flat.
11. Spread/liquidity rules pass.
12. Stop price is valid, tick-size rounded and would bound planned loss.
13. Quantity is at least one and within risk/cash/notional caps.
14. Estimated friction or slippage policy does not make the planned risk irrational.
15. Approved instruction has short expiry and an idempotency key.

## Position sizing

Use decimal arithmetic and round price to the instrument tick size.

```text
unit_risk = abs(entry_limit_price - protective_stop_price)
qty_by_risk = floor(max_planned_risk_inr / unit_risk)
qty_by_notional = floor(max_trade_notional_inr / entry_limit_price)
qty_by_cash = floor((available_cash_inr - minimum_cash_reserve_inr) / entry_limit_price)

qty = min(qty_by_risk, qty_by_notional, qty_by_cash)
```

Reject if:

- `unit_risk <= 0`
- `qty < 1`
- stop price violates strategy bounds
- resulting notional or risk exceeds configured cap
- prices cannot be rounded safely to tick size

## Data-health vetoes

No entry order when:

- latest instrument quote is older than 3 seconds during market operation;
- WebSocket heartbeat/order update stream is unhealthy;
- candle sequence has gaps for the evaluated timeframe;
- margin/cash retrieval fails or is stale;
- Kite session is invalid;
- the worker has restarted without reconciling open/pending broker state.

## Protective exit contract

An entry is not considered safely managed until the protection state is confirmed.

When entry fills:

1. Persist fill event.
2. Immediately submit protective exit using the selected supported order strategy.
3. Verify broker acknowledgement/state.
4. If protection is rejected or missing beyond the permitted interval:
   - activate kill switch for new entries;
   - alert operator;
   - attempt configured emergency exit/force-flat path;
   - persist the incident.

The system must test protective-order logic in paper mode and during a tightly controlled live connectivity test before autonomous live trading.

## Kill switch

### Automatic triggers

- Daily loss threshold reached.
- Invalid or expired Kite session.
- Protective order rejection/failure.
- Missing/stale market-data or order-update health.
- Repeated broker rejection or API errors.
- Database unavailability while a live position exists.
- Risk-engine exception.
- Position remains open near force-flat time.

### Behaviour

- Immediately reject new entries.
- Cancel pending entry orders where safe and confirmed.
- Continue monitoring existing protective exits.
- Provide explicit operator force-flat control.
- Log trigger, state transitions and remediation steps.
- Require a new deliberate arm action after a kill event; never auto-rearm.

## AI-specific vetoes

Reject the candidate when:

- output is not schema-valid;
- model response is missing, timed out or says data is insufficient;
- action/template is not allowlisted;
- the AI references news, earnings, fundamentals or external facts not provided as input;
- confidence is below the configured threshold;
- warnings contain high-risk or contradictory reasoning.

## Progression gates

Do not raise initial limits until:

- SHADOW mode has run for at least five market sessions without data-health failures;
- PAPER mode has recorded at least twenty closed simulated trades with correct stop/exit handling;
- order API and protective-exit connectivity have been validated deliberately;
- kill switch tests pass;
- ten live micro-trades have completed without operational safety failure.

After that, any increase must be a documented risk-configuration change reviewed before deployment.
