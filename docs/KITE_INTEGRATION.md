# Kite Integration

## P03 Scope

P03 adds Zerodha Kite authentication and daily session handling only.

Implemented capabilities:

- Operator-protected login URL creation.
- Callback state validation.
- Backend-only request-token exchange through the official Kite client wrapper.
- Encrypted-at-rest access-token persistence.
- Non-sensitive session status.
- Session logout/invalidation through the narrow auth wrapper.

Not implemented in P03:

- WebSocket market data.
- Historical candles.
- Instrument sync.
- Margins, positions, holdings or portfolio monitoring.
- Orders, order modification, cancellation or GTT.
- OpenAI, scanners, risk engine behavior or trading decisions.

Live trading remains disabled. Runtime defaults remain `TRADING_MODE=OFF`, `LIVE_ARMED=false` and `KITE_AUTH_ENABLED=false`.

## Authentication Flow

1. Operator calls `POST /api/v1/broker/kite/login-url` with `X-Operator-Token`.
2. Backend creates a short-lived state token in Redis and returns a Kite login URL.
3. Operator completes the Kite login in a browser.
4. Zerodha redirects to the configured callback URL with `request_token` and state.
5. Backend validates state, exchanges the request token, encrypts the access token, and stores only non-secret session metadata.
6. Access token expiry is treated as the next 6:00 AM Asia/Kolkata boundary.

The `api_secret`, raw `request_token`, raw `access_token`, encrypted token value, checksum and operator token must never appear in logs, API responses or committed files.

## Configuration

Use placeholders in Git only:

```env
KITE_AUTH_ENABLED=false
KITE_API_KEY=
KITE_API_SECRET=
KITE_REDIRECT_URL=
KITE_SESSION_ENCRYPTION_KEY=
OPERATOR_AUTH_TOKEN=
```

Actual Kite credentials and encryption keys must be provided only through secure non-committed VM configuration or future Google Secret Manager wiring.

## Deployment Note

Real Kite login testing needs a registered redirect URL that Zerodha can reach securely. The P02 VM API currently binds to `127.0.0.1` for safe health checks; do not simply open it publicly. Add HTTPS, reverse proxy and suitable access control before exposing the callback externally.

## P04 Market Data Scope

P04 adds read-only market data only:

- Instrument sync stores configured NSE watchlist instruments from Kite's daily instrument dump. The dump is reference data, not a live-price source.
- Live quotes use Kite WebSocket streaming and default to `quote` mode.
- WebSocket subscription and mode selection are installed only after Kite invokes the successful `on_connect` callback.
- Streaming requires an active, non-expired P03 Kite session. The backend decrypts the access token only internally to create the read-only data client.
- Completed one-minute UTC candles are stored from normalized ticks. Kite quote volume is cumulative for the trading day, so candle volume is derived by adding positive cross-tick cumulative-volume deltas into the current tick's minute bucket. The first partial minute after stream startup is deliberately discarded because no earlier cumulative-volume baseline exists. A WebSocket gap invalidates cumulative-volume baselines and discards the affected partial candle. The current in-progress candle is not flushed on stop or restart.
- Candle persistence from ticker callbacks is submitted back onto the FastAPI application event loop; callback threads must not create independent asyncio loops for database writes.
- The P04 stream controller is process-local. Keep the API deployment to a single Uvicorn worker while this controller owns the stream; do not enable multi-worker API deployment until market streaming is moved to a dedicated coordinated runtime.
- Logout invalidates the Kite access token, so future sync or streaming attempts require reauthentication.

All P04 flags remain disabled by default:

```env
MARKET_DATA_ENABLED=false
INSTRUMENT_SYNC_ENABLED=false
KITE_WEBSOCKET_ENABLED=false
```

Caddy and public HTTPS exposure remain callback-focused in this phase. Do not expose operator market-data controls publicly without later dashboard authentication and reverse-proxy hardening.

## P05 Scanner Data Semantics

P05 scanner records are deterministic observations only. A `CANDIDATE` in `SCANNER_OBSERVATION_MODE=SHADOW` means the completed-candle technical setup passed; it is not a paper trade, live eligibility decision or broker instruction.

Spread validation is tracked separately from shadow observation. If no quote/spread context is available, the scanner may still persist an otherwise valid SHADOW technical `CANDIDATE`, but the immutable feature snapshot marks future-live spread validation as missing and not qualified. When a future-live eligibility mode requires spread validation, missing spread remains a hard veto, and supplied wide spreads are rejected.

Live/latest-bar scanner runs compare the latest completed candle end time against `SCANNER_STALE_AFTER_SECONDS` and persist `stale_quote_or_data` when data is stale. Historical replay runs do not use wall-clock freshness because replayed bars are intentionally old.

One-minute candle continuity is enforced within the same IST trading session. Expected gaps across different IST trading dates, such as overnight gaps between sessions, are allowed; missing candles inside a session remain a data-quality veto. Opening-range calculations use only the current IST session.
