"""Read-only Kite instrument master synchronization."""

from __future__ import annotations

import logging

from app.broker.session_provider import AccessSessionProvider
from app.core.config import Settings
from app.market_data.exceptions import InstrumentSyncDisabledError, MarketDataSessionError
from app.market_data.kite_market_client import KiteMarketClient
from app.market_data.repository import MarketDataRepository
from app.market_data.schemas import InstrumentSyncResult
from app.market_data.watchlist import parse_watchlist

logger = logging.getLogger(__name__)


class InstrumentSyncService:
    """Synchronize only configured read-only NSE reference instruments."""

    def __init__(
        self,
        *,
        settings: Settings,
        market_client: KiteMarketClient,
        repository: MarketDataRepository,
        session_provider: AccessSessionProvider,
    ) -> None:
        self._settings = settings
        self._market_client = market_client
        self._repository = repository
        self._session_provider = session_provider

    async def sync(self) -> InstrumentSyncResult:
        """Fetch the daily instrument dump and upsert configured watchlist rows."""
        if not self._settings.instrument_sync_enabled:
            raise InstrumentSyncDisabledError("Instrument sync is disabled.")

        watchlist = parse_watchlist(
            self._settings.market_data_watchlist,
            self._settings.market_data_max_instruments,
        )
        try:
            kite_session = await self._session_provider.get_active_session()
        except Exception as exc:
            raise MarketDataSessionError("Active Kite session is required for instrument sync.") from exc

        logger.info("instrument sync requested", extra={"symbol_count": len(watchlist)})
        broker_instruments = self._market_client.fetch_instruments(
            api_key=kite_session.api_key,
            access_token=kite_session.access_token,
        )
        result = await self._repository.upsert_instruments(broker_instruments, watchlist)
        logger.info(
            "instrument sync completed fetched=%s inserted=%s updated=%s skipped=%s failed=%s",
            result.fetched,
            result.inserted,
            result.updated,
            result.skipped,
            result.failed,
        )
        return result
