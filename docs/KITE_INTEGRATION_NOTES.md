# Kite Connect Integration Notes

This document is an implementation checklist, not a substitute for the current official Kite documentation.

## Authentication

- Kite Connect requires backend authentication handling.
- The redirect login flow returns a short-lived `request_token`.
- Backend computes checksum using API key, request token and API secret and exchanges it for an access token.
- Never expose the API secret or session access token to the browser.
- A session access token expires at 6 AM on the next day unless invalidated earlier.
- Dashboard must show session status and refuse live arming without a valid session.

## Live data

- Use the official client library where practical.
- Consume live market data from WebSocket, not repeated REST polling.
- Store instrument-token mapping from daily instruments sync.
- Store only completed bars initially; do not create a high-volume tick lake in MVP.
- Persist data-health heartbeats.
- Start with five to ten allowlisted liquid instruments; expand only after stability.

## Order handling

- Execution Gateway is the only order-writing module.
- Create a local approved-order instruction first; use it to generate broker payload.
- Place only limit entries in the initial live stage.
- Track every broker order state update and fill.
- Submit protective exit after confirmed fill; verify it.
- Build idempotency against retries/restarts.
- Reconcile broker orders/positions on startup and before arming.

## Static IP and API-policy verification

Broker API requirements and exchange/broker operating procedures can change. The deployment plan assumes that live order requests must originate from the static IP registered for the account/API workflow. Confirm the exact current rule in the Zerodha developer console/support documentation immediately before live order testing.

## Official reference links

- API overview: `https://kite.trade/docs/connect/v3/`
- User/authentication: `https://kite.trade/docs/connect/v3/user/`
- Orders: `https://kite.trade/docs/connect/v3/orders/`
- WebSocket: `https://kite.trade/docs/connect/v3/websocket/`
