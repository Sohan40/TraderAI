# Project Rules

This is a personal autonomous trading experiment using Zerodha Kite Connect.

Critical safety rules:
- Never place a real broker order during development or tests.
- All broker calls must be mocked unless TRADING_MODE=LIVE and LIVE_ARMED=true.
- Never hardcode or commit API keys, API secrets, access tokens, or OpenAI credentials.
- Order execution must always pass through the deterministic risk engine.
- AI modules must never directly call broker order endpoints.
- AI modules must never compute order quantity.
- Never enable F&O, leverage, short selling, averaging down, or overnight trades in the MVP.
- Every order proposal, rejection, broker response, fill and exit must be stored in the journal.
- Run unit tests before completing each implementation plan.