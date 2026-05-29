# Market Data Module

Purpose: read-only Kite instrument sync, configured watchlist resolution, quote-stream lifecycle state, tick normalization, and completed one-minute candle storage for P04.

This module must remain separate from execution. It has no order, position, holdings, GTT, scanner, OpenAI, or live-trading functionality.

All ingestion flags default to disabled and require an active encrypted P03 Kite session before any real stream can be started.
