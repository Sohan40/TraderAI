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
- Telegram alerts for milestones, warnings, and failures.

It does not place orders, call broker order/account endpoints, bypass Kite
login, mutate `MARKET_DATA_WATCHLIST`, retrieve news or fundamentals, invoke
OpenAI, or trigger P06 paper replay. Automation does not guarantee profits.

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
4. Force-recreate the API only at a safe operational time.

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
