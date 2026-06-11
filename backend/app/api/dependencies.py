"""Shared FastAPI dependencies."""

from hmac import compare_digest

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.broker.kite_auth_service import KiteAuthService, RedisStateStore
from app.broker.kite_client import KiteConnectAuthClient
from app.broker.session_provider import KiteAccessSessionProvider
from app.broker.session_store import SQLAlchemySessionStore, SessionFactorySessionStore
from app.broker.token_cipher import TokenCipher
from app.cache.redis import get_redis_client
from app.core.config import settings
from app.db.session import async_session_factory, get_session
from app.decision.automation import DecisionAutomationService
from app.decision.fake_adapter import FakeDecisionAdapter
from app.decision.openai_adapter import OpenAIDecisionAdapter
from app.decision.repository import (
    SQLAlchemyDecisionRepository,
    SessionFactoryDecisionRepository,
)
from app.decision.service import DecisionService
from app.market_data.instrument_sync import InstrumentSyncService
from app.market_data.kite_market_client import KiteConnectMarketClient
from app.market_data.repository import (
    SQLAlchemyMarketDataRepository,
    SessionFactoryMarketDataRepository,
)
from app.market_data.stream_readiness import StreamReadinessService
from app.market_data.watchlist_validation import WatchlistValidationService
from app.market_data.websocket_service import MarketDataStreamService
from app.ops.morning_readiness import MorningReadinessService
from app.ops.market_ops import MarketOpsOrchestrator
from app.ops.market_ops_scheduler import MarketOpsScheduler
from app.ops.notifier import Notifier
from app.ops.telegram_actions import TelegramActionService
from app.ops.telegram_bot import TelegramInteractiveBot
from app.paper.repository import SQLAlchemyPaperRepository
from app.paper.service import PaperService
from app.scanners.auto_loop import ScannerAutoLoopService
from app.scanners.repository import SQLAlchemyScannerRepository, SessionFactoryScannerRepository
from app.scanners.service import ScannerService
from app.universe.repository import (
    SQLAlchemyUniverseRepository,
    SessionFactoryUniverseRepository,
)
from app.universe.service import UniverseSelectionService

_market_data_stream_service: MarketDataStreamService | None = None
_scanner_auto_loop_service: ScannerAutoLoopService | None = None
_market_ops_notifier: Notifier | None = None
_market_ops_orchestrator: MarketOpsOrchestrator | None = None
_market_ops_scheduler: MarketOpsScheduler | None = None
_decision_automation_service: DecisionAutomationService | None = None
_telegram_interactive_bot: TelegramInteractiveBot | None = None


def require_operator_token(x_operator_token: str | None = Header(default=None)) -> None:
    """Authenticate operator-only endpoints with a configured header token."""
    if not settings.operator_auth_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="operator authentication is not configured",
        )
    if x_operator_token is None or not compare_digest(x_operator_token, settings.operator_auth_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid operator token",
        )


async def get_kite_auth_service(
    session: AsyncSession = Depends(get_session),
) -> KiteAuthService:
    """Build the Kite auth service from configured production dependencies."""
    token_cipher = (
        TokenCipher(settings.kite_session_encryption_key)
        if settings.kite_session_encryption_key
        else None
    )
    return KiteAuthService(
        settings=settings,
        kite_client=KiteConnectAuthClient(
            api_key=settings.kite_api_key,
            api_secret=settings.kite_api_secret,
        ),
        session_store=SQLAlchemySessionStore(session),
        state_store=RedisStateStore(get_redis_client()),
        token_cipher=token_cipher,
    )


def _build_token_cipher() -> TokenCipher | None:
    return (
        TokenCipher(settings.kite_session_encryption_key)
        if settings.kite_session_encryption_key
        else None
    )


async def get_kite_access_session_provider(
    session: AsyncSession = Depends(get_session),
) -> KiteAccessSessionProvider:
    """Build the internal-only Kite access session provider."""
    return KiteAccessSessionProvider(
        settings=settings,
        session_store=SQLAlchemySessionStore(session),
        token_cipher=_build_token_cipher(),
    )


async def get_instrument_sync_service(
    session: AsyncSession = Depends(get_session),
    session_provider: KiteAccessSessionProvider = Depends(get_kite_access_session_provider),
) -> InstrumentSyncService:
    """Build the instrument sync service."""
    return InstrumentSyncService(
        settings=settings,
        market_client=KiteConnectMarketClient(),
        repository=SQLAlchemyMarketDataRepository(session),
        session_provider=session_provider,
    )


async def get_watchlist_validation_service(
    session: AsyncSession = Depends(get_session),
) -> WatchlistValidationService:
    """Build DB-only watchlist diagnostics."""
    return WatchlistValidationService(
        settings=settings,
        repository=SQLAlchemyMarketDataRepository(session),
    )


async def get_market_data_stream_service() -> MarketDataStreamService:
    """Return a process-local stream controller for P04."""
    global _market_data_stream_service
    if _market_data_stream_service is None:
        _market_data_stream_service = MarketDataStreamService(
            settings=settings,
            market_client=KiteConnectMarketClient(),
            repository=SessionFactoryMarketDataRepository(async_session_factory),
            session_provider=KiteAccessSessionProvider(
                settings=settings,
                session_store=SessionFactorySessionStore(async_session_factory),
                token_cipher=_build_token_cipher(),
            ),
        )
    return _market_data_stream_service


async def get_stream_readiness_service(
    session: AsyncSession = Depends(get_session),
    stream_service: MarketDataStreamService = Depends(get_market_data_stream_service),
) -> StreamReadinessService:
    """Build DB-only stream readiness diagnostics."""
    return StreamReadinessService(
        settings=settings,
        watchlist_service=WatchlistValidationService(
            settings=settings,
            repository=SQLAlchemyMarketDataRepository(session),
        ),
        session_store=SQLAlchemySessionStore(session),
        stream_status_provider=stream_service,
    )


async def get_scanner_service(
    session: AsyncSession = Depends(get_session),
) -> ScannerService:
    """Build the operator-triggered P05 scanner service."""
    universe_service = UniverseSelectionService(
        settings=settings,
        repository=SQLAlchemyUniverseRepository(session),
    )
    return ScannerService(
        settings=settings,
        repository=SQLAlchemyScannerRepository(session),
        latest_universe_provider=universe_service,
    )


async def get_scanner_auto_loop_service() -> ScannerAutoLoopService:
    """Return the process-local disabled-by-default scanner scheduler."""
    global _scanner_auto_loop_service
    if _scanner_auto_loop_service is None:
        universe_service = UniverseSelectionService(
            settings=settings,
            repository=SessionFactoryUniverseRepository(async_session_factory),
        )
        _scanner_auto_loop_service = ScannerAutoLoopService(
            settings=settings,
            scanner_service=ScannerService(
                settings=settings,
                repository=SessionFactoryScannerRepository(async_session_factory),
                latest_universe_provider=universe_service,
            ),
        )
    return _scanner_auto_loop_service


async def get_universe_selection_service(
    session: AsyncSession = Depends(get_session),
) -> UniverseSelectionService:
    """Build deterministic local-data universe selection."""
    return UniverseSelectionService(
        settings=settings,
        repository=SQLAlchemyUniverseRepository(session),
    )


async def get_morning_readiness_service(
    session: AsyncSession = Depends(get_session),
    stream_service: MarketDataStreamService = Depends(get_market_data_stream_service),
    auto_loop_service: ScannerAutoLoopService = Depends(get_scanner_auto_loop_service),
) -> MorningReadinessService:
    """Build local-only operational readiness aggregation."""
    market_repository = SQLAlchemyMarketDataRepository(session)
    watchlist_service = WatchlistValidationService(
        settings=settings,
        repository=market_repository,
    )
    stream_readiness_service = StreamReadinessService(
        settings=settings,
        watchlist_service=watchlist_service,
        session_store=SQLAlchemySessionStore(session),
        stream_status_provider=stream_service,
    )
    return MorningReadinessService(
        settings=settings,
        watchlist_service=watchlist_service,
        stream_readiness_service=stream_readiness_service,
        scanner_service=ScannerService(
            settings=settings,
            repository=SQLAlchemyScannerRepository(session),
        ),
        auto_loop_service=auto_loop_service,
        universe_service=UniverseSelectionService(
            settings=settings,
            repository=SQLAlchemyUniverseRepository(session),
        ),
    )


async def get_notifier() -> Notifier:
    """Return the process-local secret-safe market-ops notifier."""
    global _market_ops_notifier
    if _market_ops_notifier is None:
        _market_ops_notifier = Notifier(settings=settings)
    return _market_ops_notifier


async def get_market_ops_orchestrator() -> MarketOpsOrchestrator:
    """Build the process-local market-ops orchestration service."""
    global _market_ops_orchestrator
    if _market_ops_orchestrator is None:
        stream_service = await get_market_data_stream_service()
        auto_loop_service = await get_scanner_auto_loop_service()
        market_repository = SessionFactoryMarketDataRepository(async_session_factory)
        universe_service = UniverseSelectionService(
            settings=settings,
            repository=SessionFactoryUniverseRepository(async_session_factory),
        )
        scanner_service = ScannerService(
            settings=settings,
            repository=SessionFactoryScannerRepository(async_session_factory),
            latest_universe_provider=universe_service,
        )
        watchlist_service = WatchlistValidationService(
            settings=settings,
            repository=market_repository,
        )
        stream_readiness_service = StreamReadinessService(
            settings=settings,
            watchlist_service=watchlist_service,
            session_store=SessionFactorySessionStore(async_session_factory),
            stream_status_provider=stream_service,
        )
        morning_readiness_service = MorningReadinessService(
            settings=settings,
            watchlist_service=watchlist_service,
            stream_readiness_service=stream_readiness_service,
            scanner_service=scanner_service,
            auto_loop_service=auto_loop_service,
            universe_service=universe_service,
        )
        _market_ops_orchestrator = MarketOpsOrchestrator(
            settings=settings,
            morning_readiness=morning_readiness_service,
            stream_readiness=stream_readiness_service,
            stream_service=stream_service,
            universe_service=universe_service,
            scanner_service=scanner_service,
            notifier=await get_notifier(),
            decision_automation=await get_decision_automation_service(),
            kite_login_url_provider=KiteAuthService(
                settings=settings,
                kite_client=KiteConnectAuthClient(
                    api_key=settings.kite_api_key,
                    api_secret=settings.kite_api_secret,
                ),
                session_store=SessionFactorySessionStore(async_session_factory),
                state_store=RedisStateStore(get_redis_client()),
                token_cipher=_build_token_cipher(),
            ),
        )
    return _market_ops_orchestrator


async def get_market_ops_scheduler() -> MarketOpsScheduler:
    """Return the process-local disabled-by-default market-ops scheduler."""
    global _market_ops_scheduler
    if _market_ops_scheduler is None:
        _market_ops_scheduler = MarketOpsScheduler(
            settings=settings,
            orchestrator=await get_market_ops_orchestrator(),
        )
    return _market_ops_scheduler


async def get_paper_service(
    session: AsyncSession = Depends(get_session),
) -> PaperService:
    """Build the operator-triggered P06 paper service."""
    return PaperService(
        settings=settings,
        repository=SQLAlchemyPaperRepository(session),
    )


async def get_decision_service(
    session: AsyncSession = Depends(get_session),
) -> DecisionService:
    """Build operator-triggered P07 decision evaluation."""
    return DecisionService(
        settings=settings,
        repository=SQLAlchemyDecisionRepository(session),
        adapter=_build_decision_adapter(),
    )


def _build_decision_adapter() -> OpenAIDecisionAdapter | FakeDecisionAdapter:
    return (
        OpenAIDecisionAdapter(settings=settings)
        if settings.openai_decision_adapter.strip().lower() == "openai"
        else FakeDecisionAdapter()
    )


async def get_decision_automation_service() -> DecisionAutomationService:
    """Return process-local bounded P07 automation and its last summary."""
    global _decision_automation_service
    if _decision_automation_service is None:
        repository = SessionFactoryDecisionRepository(async_session_factory)
        _decision_automation_service = DecisionAutomationService(
            settings=settings,
            decision_service=DecisionService(
                settings=settings,
                repository=repository,
                adapter=_build_decision_adapter(),
            ),
            repository=repository,
            notifier=await get_notifier(),
        )
    return _decision_automation_service


async def get_telegram_interactive_bot() -> TelegramInteractiveBot:
    """Return the disabled-by-default process-local Telegram poller."""
    global _telegram_interactive_bot
    if _telegram_interactive_bot is None:
        repository = SessionFactoryDecisionRepository(async_session_factory)
        _telegram_interactive_bot = TelegramInteractiveBot(
            settings=settings,
            actions=TelegramActionService(
                settings=settings,
                kite_service=KiteAuthService(
                    settings=settings,
                    kite_client=KiteConnectAuthClient(
                        api_key=settings.kite_api_key,
                        api_secret=settings.kite_api_secret,
                    ),
                    session_store=SessionFactorySessionStore(async_session_factory),
                    state_store=RedisStateStore(get_redis_client()),
                    token_cipher=_build_token_cipher(),
                ),
                stream_service=await get_market_data_stream_service(),
                scheduler=await get_market_ops_scheduler(),
                decision_service=DecisionService(
                    settings=settings,
                    repository=repository,
                    adapter=_build_decision_adapter(),
                ),
                decision_automation=await get_decision_automation_service(),
            ),
        )
    return _telegram_interactive_bot
