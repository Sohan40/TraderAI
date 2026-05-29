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
- Streaming requires an active, non-expired P03 Kite session. The backend decrypts the access token only internally to create the read-only data client.
- Completed one-minute candles are stored from normalized ticks. The current in-progress candle is not flushed on stop or restart.
- Logout invalidates the Kite access token, so future sync or streaming attempts require reauthentication.

All P04 flags remain disabled by default:

```env
MARKET_DATA_ENABLED=false
INSTRUMENT_SYNC_ENABLED=false
KITE_WEBSOCKET_ENABLED=false
```

Caddy and public HTTPS exposure remain callback-focused in this phase. Do not expose operator market-data controls publicly without later dashboard authentication and reverse-proxy hardening.
