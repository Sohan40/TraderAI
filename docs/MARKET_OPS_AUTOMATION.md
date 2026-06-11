# Market Operations Automation

P05.9/P05.10 coordinate existing read-only market-data, readiness,
universe-selection, and scanner services. All automation remains disabled by
default.

It can automate:

- preopen safety, Kite-session, and watchlist checks;
- read-only market-data stream start, verification, and stop;
- deterministic universe selection over completed local candles;
- deterministic scanner batches over the latest selected universe or static
  market watchlist;
- repeated scanner batches during the configured intraday window;
- optional bounded P07 shadow evaluation of newly persisted scanner candidates;
- Telegram alerts for milestones, warnings, and failures.

It does not place orders, call broker order/account endpoints, bypass Kite
login, mutate `MARKET_DATA_WATCHLIST`, retrieve news or fundamentals, or
trigger P06 paper replay. Optional P07 evaluation is notification/report-only
and never gates replay or execution. Automation does not guarantee profits.

## Safe Defaults

```text
MARKET_OPS_AUTOMATION_ENABLED=false
MARKET_OPS_NOTIFY_ENABLED=false
MARKET_OPS_NOTIFY_PROVIDER=none
MARKET_OPS_TELEGRAM_BOT_TOKEN=
MARKET_OPS_TELEGRAM_CHAT_ID=
MARKET_OPS_NOTIFY_MIN_LEVEL=warning
MARKET_OPS_SEND_KITE_LOGIN_LINK=false
MARKET_OPS_LOGIN_RECOVERY_ENABLED=false
MARKET_OPS_LOGIN_RECOVERY_START_IST=09:00
MARKET_OPS_LOGIN_RECOVERY_STOP_IST=09:25
MARKET_OPS_LOGIN_RECOVERY_INTERVAL_SECONDS=30
MARKET_OPS_AUTOSTART_ENABLED=false
MARKET_OPS_DECISION_AUTO_EVALUATE_ENABLED=false
MARKET_OPS_DECISION_AUTO_EVALUATE_MAX_SIGNALS=5
MARKET_OPS_DECISION_AUTO_EVALUATE_ONLY_CANDIDATES=true
```

Keep these production safeguards unchanged:

```text
TRADING_MODE=OFF
LIVE_ARMED=false
PAPER_ENABLED=false
PAPER_MODE=OFF
```

The scheduler and recovery state are process-local. Recovery state resets on
every API restart. By default, enabling automation does not start the scheduler;
an authenticated operator must call `POST /api/v1/ops/market-ops/start`.
Autostart occurs only when both `MARKET_OPS_AUTOSTART_ENABLED=true` and
`MARKET_OPS_AUTOMATION_ENABLED=true`. Scheduler startup is idempotent, so
lifespan startup and operator requests cannot create duplicate loops.

## Daily Schedule

All times use `MARKET_OPS_TIMEZONE`, default `Asia/Kolkata`.

| Time | Action |
|---|---|
| 08:55 | Preopen readiness |
| 09:08 | Start read-only stream if local gates pass |
| 09:16 | Verify connection and subscriptions |
| 10:07 | Select universe |
| 10:08 | Run scanner batch |
| Every 5 minutes through 15:00 | Repeat scanner batch |
| 15:31 | Stop stream |

Kite daily login is still required when the stored session is missing or
expired. The preopen check sends `kite_session_missing`; it never performs or
bypasses login.

## Login Link And Recovery

When all of the following are enabled, a missing session can produce a
`kite_login_link_sent` Telegram notification:

- `MARKET_OPS_SEND_KITE_LOGIN_LINK=true`;
- Telegram notifications are enabled with provider `telegram`;
- Kite authentication is enabled and fully configured.

The URL is generated through the existing Kite authentication service. It is a
short-lived helper for the human login flow only. It is not stored in the
database or scheduler status and must not be logged. Telegram remains
notification-only, and the existing callback still completes the authenticated
session after the human logs in.

Only one link is sent per recovery episode. An episode begins when a missing
Kite session is detected and ends when recovery succeeds or the configured
window expires. An API restart resets process-local episode state.

With login recovery enabled, the scheduler retries only between
`MARKET_OPS_LOGIN_RECOVERY_START_IST` and
`MARKET_OPS_LOGIN_RECOVERY_STOP_IST`. Starting the scheduler inside that window
immediately performs a catch-up readiness attempt, even if the normal preopen
or stream-start minute was missed. Once login is ready, it requests stream
start through existing readiness gates and verifies the stream on a later
retry. At expiry it stops retrying and sends one warning.

Recovery never starts the stream outside the configured window, bypasses
watchlist/session checks, starts scanners before their existing data gates, or
invokes P06 paper replay.

## P07.1 Decision Evaluation

P07.1 can evaluate newly persisted `CANDIDATE` signals immediately after a
market-ops scanner batch. It is disabled by default and requires both:

```text
OPENAI_DECISION_ENABLED=true
MARKET_OPS_DECISION_AUTO_EVALUATE_ENABLED=true
```

Candidate discovery is limited to the scanner batch time window and scanned
symbols. Evaluation is oldest-first, idempotent, and capped by
`MARKET_OPS_DECISION_AUTO_EVALUATE_MAX_SIGNALS`, default `5`. Rejected scanner
signals, dry runs, duplicates, and already evaluated candidates do not cause
model calls.

New decisions may send one compact Telegram message each, up to the same cap.
`ELIGIBLE` and failed evaluations use warning level; `WATCH` and `REJECT` use
info. Messages contain signal identity, verdict, confidence, sufficiency,
model, prompt version, and at most two configured reasons and warnings. They
never contain raw model payloads or credentials.

Enable a deliberate real adapter only through ignored runtime configuration:

```text
OPENAI_DECISION_ENABLED=true
OPENAI_DECISION_ADAPTER=openai
OPENAI_MODEL=...
OPENAI_API_KEY=...
OPENAI_DECISION_STORE=false
OPENAI_DECISION_EVALUATION_MODE=LIVE_SHADOW
MARKET_OPS_DECISION_AUTO_EVALUATE_ENABLED=true
```

Immediately disable automatic calls with:

```text
MARKET_OPS_DECISION_AUTO_EVALUATE_ENABLED=false
```

The scheduler never invokes P06 paper replay, risk checks, order creation, or
broker account endpoints.

## Telegram Setup

1. Create a bot with BotFather.
2. Send `/start` to the bot from your personal Telegram account.
3. Use Telegram `getUpdates` and read `message.chat.id` from the human private
   chat update.
4. Test Telegram `sendMessage`.
5. Put the values only in `infra/gcp/env.prod` on the VM using:
   `MARKET_OPS_TELEGRAM_BOT_TOKEN` and `MARKET_OPS_TELEGRAM_CHAT_ID`.

Never commit, log, print, snapshot, or document the real token or chat ID.

The Telegram error `Forbidden: the bot can't send messages to the bot` means
the configured chat ID is the bot ID rather than the human private chat ID.
Use `message.chat.id` from the human account's update.

Notification levels are filtered by `MARKET_OPS_NOTIFY_MIN_LEVEL`:

- `info`: send info, warning, and error;
- `warning`: send warning and error;
- `error`: send error only.

Telegram failures are contained and do not crash an automation job. Messages
are plain text, bounded in length, and exclude configured secret fields.

## Operator Routes

All routes require `X-Operator-Token`.

```text
GET  /api/v1/ops/market-ops/status
POST /api/v1/ops/market-ops/start
POST /api/v1/ops/market-ops/stop
POST /api/v1/ops/market-ops/run-preopen-check
POST /api/v1/ops/market-ops/run-start-stream
POST /api/v1/ops/market-ops/run-verify-stream
POST /api/v1/ops/market-ops/run-universe-selection
POST /api/v1/ops/market-ops/run-scanner-batch
POST /api/v1/ops/market-ops/run-stop-stream
POST /api/v1/ops/market-ops/test-notification
GET  /api/v1/decision/auto-status
POST /api/v1/decision/evaluate-latest?limit=5
```

Use the one-shot routes to validate each operation before starting the
scheduler. The status response never includes Telegram credentials.

## VM-Local CLI

The standard-library CLI talks only to the operator-protected HTTP API. Its
default URL is `http://127.0.0.1:8000`; override it with `--base-url`.

Token precedence is:

1. `--operator-token`;
2. the `OPERATOR_AUTH_TOKEN` environment variable;
3. `--env-file`;
4. `infra/gcp/env.prod` when present.

Examples:

```text
python -m app.ops.cli status
python -m app.ops.cli kite-login-url
python -m app.ops.cli start-stream
python -m app.ops.cli scanner
python -m app.ops.cli paper-status
python -m app.ops.cli paper-replay --symbol NSE:SBIN --from 2026-06-09T05:00:00Z --to 2026-06-09T10:00:00Z
python -m app.ops.cli --base-url http://127.0.0.1:9000 status
```

Available commands are `status`, `start`, `stop`, `preopen`, `start-stream`,
`verify-stream`, `universe`, `scanner`, `stop-stream`, `test-telegram`,
`kite-status`, `kite-login-url`, `stream-status`, `paper-status`,
`paper-report`, `paper-trades`, and `paper-replay`.

P07.1 adds `decision-auto-status` and
`decision-evaluate-latest --limit 5`. Manual latest evaluation is bounded,
candidate-only, idempotent, and does not require automatic evaluation to be
enabled.

From the repository root, `scripts/traderctl` provides the same interface while
setting `PYTHONPATH=backend`. Paper commands remain explicit operator actions.
The market-ops scheduler has no paper route or paper-service integration and
never auto-runs replay.

## Safe Enablement

1. Keep trading and paper settings OFF.
2. Complete daily Kite login.
3. Validate the watchlist and instrument sync before market.
4. Configure Telegram credentials only in the uncommitted production env file.
5. Set `MARKET_OPS_NOTIFY_ENABLED=true` and provider `telegram`.
6. Force-recreate the API before market so changed env values are loaded.
7. Call the test-notification route.
8. Run the preopen one-shot route.
9. Set `MARKET_OPS_AUTOMATION_ENABLED=true`, force-recreate before market, then
   explicitly start the scheduler. Enable autostart separately only after
   validating the one-shot and manual-start paths.
10. Confirm status and the next scheduled action.

`docker compose restart api` does not reload changed environment values. Use:

```text
docker compose --env-file infra/gcp/env.prod -f infra/gcp/docker-compose.prod.yml up -d --force-recreate api
```

Do not deploy, restart, or recreate the API during market hours unless
absolutely necessary.

The public proxy/Caddy configuration remains unchanged. Operator routes remain
available only through the VM-local loopback binding or an explicit SSH tunnel.

## Immediate Disable

1. Call `POST /api/v1/ops/market-ops/stop`.
2. Set `MARKET_OPS_AUTOMATION_ENABLED=false`.
3. Set `MARKET_OPS_NOTIFY_ENABLED=false` if notifications must also stop.
4. Set `MARKET_OPS_DECISION_AUTO_EVALUATE_ENABLED=false` to stop automatic
   model calls while preserving scanner operation.
5. Force-recreate the API only at a safe operational time.

Stopping automation does not alter the watchlist, Kite session, paper settings,
or trading safety settings.

## Troubleshooting

- `kite_session_missing`: complete daily Kite login.
- `watchlist_not_ready`: validate format, sync missing instruments, and
  revalidate.
- `stream_start_skipped`: inspect stream readiness and its recommended action.
- `stream_not_connected`: compare configured and subscribed counts and inspect
  the safe `last_error` category.
- `candle_health_warning`: the stream reports stale activity; investigate
  connectivity before scanning.
- `universe_selection_skipped`: enable selection or collect the configured
  minimum completed candles.
- `scanner_batch_failed`: confirm scanner enablement and that a latest selected
  universe exists when selected-universe mode is configured.

P06 paper replay remains a separate, deliberate after-market operator action.

## Interactive Telegram Bot

P05.11 adds an optional private long-polling Telegram operator bot. It is
disabled by default and requires:

```text
MARKET_OPS_TELEGRAM_INTERACTIVE_ENABLED=true
MARKET_OPS_NOTIFY_PROVIDER=telegram
MARKET_OPS_TELEGRAM_BOT_TOKEN=...
MARKET_OPS_TELEGRAM_INTERACTIVE_ALLOWED_CHAT_ID=...
MARKET_OPS_TELEGRAM_INTERACTIVE_ALLOWED_USER_ID=...
```

Read the private human chat ID and user ID from a Telegram `getUpdates`
response after sending `/start` to the bot. Group chats, unknown chats, unknown
users, unknown callback actions, and over-limit actions are ignored or rejected.
The bot uses long polling and does not expose a webhook through Caddy.

`/start` and `/menu` show allowlisted buttons for:

- fresh Kite login link and non-sensitive Kite status;
- stream status, safe start, verify, stop, and emergency stop;
- scheduler status, start, and stop;
- preopen, universe-selection, and scanner jobs;
- P07 status, P07 auto status, and bounded latest-candidate evaluation;
- help.

Stop actions require confirmation by default. Start Stream always calls the
existing `MarketOpsScheduler.run_job("stream_start")` path. If another job is
running it returns `job already running`; if the stream is already connected it
returns `already running and connected`; if running but disconnected it
suggests Verify Stream or Stop/Start. It never creates a duplicate WebSocket,
changes scheduler completed slots, reschedules future jobs, or bypasses
readiness gates.

Fresh Kite Login Link creates new callback state through the existing
authentication service. Use it when an older Telegram link reports an invalid
callback. The URL is sent only to the allowed private chat and is not persisted
or included in bot status.

The Telegram bot cannot place orders, run paper replay, execute shell commands,
access a Docker socket, or restart the API. API restart is intentionally not
available from Telegram. For a manual VM process restart with unchanged
environment:

```text
docker compose --env-file infra/gcp/env.prod -f infra/gcp/docker-compose.prod.yml restart api
```

That command does not reload changed environment values. After environment
changes, continue using the documented `up -d --force-recreate api` command.

Operator-only bot status is available at:

```text
GET /api/v1/ops/market-ops/telegram-bot/status
```

Polling offset and rate-limit state are process-local. On startup the bot
discards pending historical updates before processing new ones.
