# P03 — Kite Authentication and Daily Session Lifecycle


## Objective

Implement Zerodha/Kite authentication, session status and logout without market scanning or orders.

## Deliverables

- Broker adapter abstraction plus a Kite implementation for authentication/profile/margins only.
- Endpoints:
  - `GET /auth/kite/login`;
  - `GET /auth/kite/callback`;
  - `GET /broker/session/status`;
  - `POST /broker/session/logout`.
- Backend-only checksum/token exchange.
- Session persistence with:
  - encrypted/protected access-token handling;
  - login time;
  - expiry at the documented next-day 6 AM boundary;
  - status and invalidation state.
- Automatic `LIVE_ARMED=false` when session invalidates/expires.
- Account/margin fetch read-only smoke route usable only by authenticated owner.
- Fake broker adapter for all tests.

## Safety requirements

- Never send API secret/access token to frontend or logs.
- No order routes or market-order methods.
- Callback errors must not arm trading.
- The dashboard/UI work is out of scope; simple API flows are enough.

## Tests

- Checksum flow uses fake credentials only.
- Token is redacted in logs/API output.
- Expired session reports invalid and disarms.
- Logout invalidates local session safely.
- Margin adapter errors are handled.

## Acceptance criteria

- Owner can complete the login flow against Kite in a controlled read-only environment.
- App can display connected/disconnected/expired state.
- No live order capability exists.

## Codex prompt

```text
Implement only P03_KITE_AUTH_AND_SESSIONS.

Add the typed broker interface, Kite auth/session/profile/margin read-only adapter, API endpoints,
protected session persistence, and fake adapter tests.

Do not implement quote streaming, scanning, AI calls or any order-writing API.
Ensure token/secret redaction and automatic disarm on invalid session.
Run tests and report any manual redirect-URL setup required.
```
