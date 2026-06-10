# Market Operations Automation

P05.9 coordinates existing read-only market-data, readiness, universe-selection,
and scanner services. It is disabled by default and must be started explicitly
through an operator-protected route.

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
```

Keep these production safeguards unchanged:

```text
TRADING_MODE=OFF
LIVE_ARMED=false
PAPER_ENABLED=false
PAPER_MODE=OFF
```

The scheduler is process-local. Enabling the config flag does not start it at
API startup. An authenticated operator must call `POST
/api/v1/ops/market-ops/start`.

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

The optional CLI was not added in P05.9. The operator API already exposes every
one-shot action and scheduler control, while a CLI would duplicate production
dependency and authentication construction.

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
   explicitly start the scheduler.
10. Confirm status and the next scheduled action.

`docker compose restart api` does not reload changed environment values. Use:

```text
docker compose --env-file infra/gcp/env.prod -f infra/gcp/docker-compose.prod.yml up -d --force-recreate api
```

Do not deploy, restart, or recreate the API during market hours unless
absolutely necessary.

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
