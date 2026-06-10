"""Safe orchestration of read-only market-data and deterministic scanners."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Protocol, cast

from app.core.config import Settings
from app.ops.notifier import Notifier
from app.scanners.schemas import ScannerBatchResult
from app.universe.exceptions import (
    SelectedUniverseMissingError,
    UniverseInputError,
    UniverseSelectionDisabledError,
)
from app.universe.schemas import UniverseSelectionRun


class MorningReadiness(Protocol):
    async def readiness(self) -> dict[str, object]: ...


class StreamReadiness(Protocol):
    async def readiness(self) -> dict[str, object]: ...


class StreamController(Protocol):
    async def start(self) -> dict[str, object]: ...
    async def stop(self) -> dict[str, object]: ...
    def status_dict(self) -> dict[str, object]: ...


class UniverseSelector(Protocol):
    async def select(
        self,
        *,
        dry_run: bool,
        use_current_session: bool,
        min_candles: int,
        stale_policy: str,
    ) -> UniverseSelectionRun: ...


class BatchScanner(Protocol):
    async def run_batch(
        self,
        *,
        symbols: list[str] | None,
        store_rejections: bool,
        dry_run: bool,
        use_latest_universe: bool,
    ) -> ScannerBatchResult: ...


class KiteLoginUrlProvider(Protocol):
    async def create_login_url(self) -> dict[str, str]: ...


class DecisionAutomation(Protocol):
    def status(self) -> dict[str, object]: ...
    async def evaluate_scanner_batch(
        self,
        *,
        started_at: datetime,
        finished_at: datetime,
        symbols: list[str],
        dry_run: bool,
        candidate_count: int,
    ) -> dict[str, object]: ...


class MarketOpsOrchestrator:
    """Coordinate existing read-only services without bypassing their gates."""

    def __init__(
        self,
        *,
        settings: Settings,
        morning_readiness: MorningReadiness,
        stream_readiness: StreamReadiness,
        stream_service: StreamController,
        universe_service: UniverseSelector,
        scanner_service: BatchScanner,
        notifier: Notifier,
        decision_automation: DecisionAutomation | None = None,
        kite_login_url_provider: KiteLoginUrlProvider | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self._settings = settings
        self._morning_readiness = morning_readiness
        self._stream_readiness = stream_readiness
        self._stream_service = stream_service
        self._universe_service = universe_service
        self._scanner_service = scanner_service
        self._notifier = notifier
        self._decision_automation = decision_automation
        self._kite_login_url_provider = kite_login_url_provider
        self._now_provider = now_provider or (lambda: datetime.now(timezone.utc))

    async def preopen_check(self) -> dict[str, object]:
        started = self._now()
        try:
            report = await self._morning_readiness.readiness()
            safe = bool(report.get("safe"))
            stream = cast(dict[str, object], report.get("stream_readiness", {}))
            watchlist = cast(dict[str, object], report.get("watchlist_validation", {}))
            kite_ready = bool(stream.get("kite_session_ready"))
            watchlist_ready = bool(watchlist.get("ready_for_stream"))
            problems: list[str] = []
            if not safe:
                problems.append("trading_safety_defaults_not_off")
            if self._settings.market_ops_require_kite_session and not kite_ready:
                problems.append("kite_session_not_ready")
            if self._settings.market_ops_require_watchlist_ready and not watchlist_ready:
                problems.append("watchlist_not_ready")
            if problems:
                if "kite_session_not_ready" in problems:
                    event = "kite_session_missing"
                elif "watchlist_not_ready" in problems:
                    event = "watchlist_not_ready"
                else:
                    event = "preopen_check_failed"
                message = "Preopen readiness requires operator attention."
                summary = self._summary(
                    started=started,
                    ok=False,
                    skipped=False,
                    event=event,
                    level="warning",
                    message=message,
                    details={"issues": problems},
                )
            else:
                summary = self._summary(
                    started=started,
                    ok=True,
                    skipped=False,
                    event="preopen_check_ok",
                    level="info",
                    message="Preopen safety, Kite session, and watchlist checks passed.",
                    details={"kite_session_ready": kite_ready, "watchlist_ready": watchlist_ready},
                )
        except Exception:
            summary = self._failed(started, "preopen_check_failed", "Preopen check failed.")
        await self._notify(summary)
        return summary

    async def start_stream_if_ready(self) -> dict[str, object]:
        started = self._now()
        try:
            readiness = await self._stream_readiness.readiness()
            if (
                self._settings.market_ops_require_kite_session
                and not readiness.get("kite_session_ready")
            ):
                summary = self._summary(
                    started=started,
                    ok=False,
                    skipped=True,
                    event="stream_start_skipped",
                    level="warning",
                    message="Stream start skipped because Kite login is required.",
                    details={"recommended_action": "login_kite"},
                )
            elif (
                self._settings.market_ops_require_watchlist_ready
                and not readiness.get("watchlist_ready")
            ):
                summary = self._summary(
                    started=started,
                    ok=False,
                    skipped=True,
                    event="stream_start_skipped",
                    level="warning",
                    message="Stream start skipped because the watchlist is not ready.",
                    details={
                        "recommended_action": readiness.get("recommended_next_action"),
                        "missing_symbols": readiness.get("missing_symbols", []),
                    },
                )
            elif readiness.get("stream_already_running"):
                connected = bool(readiness.get("stream_connected"))
                summary = self._summary(
                    started=started,
                    ok=connected,
                    skipped=True,
                    event="stream_started" if connected else "stream_not_connected",
                    level="info" if connected else "warning",
                    message=(
                        "Market-data stream is already running and connected."
                        if connected
                        else "Market-data stream is running but not connected."
                    ),
                    details={"connected": connected},
                )
            elif not readiness.get("can_start_stream"):
                summary = self._summary(
                    started=started,
                    ok=False,
                    skipped=True,
                    event="stream_start_skipped",
                    level="warning",
                    message="Stream readiness gates did not pass.",
                    details={"errors": readiness.get("errors", [])},
                )
            else:
                status = await self._stream_service.start()
                summary = self._summary(
                    started=started,
                    ok=True,
                    skipped=False,
                    event="stream_started",
                    level="info",
                    message="Market-data stream start was requested successfully.",
                    details=_stream_details(status),
                )
        except Exception:
            summary = self._failed(started, "stream_start_failed", "Stream start failed.")
        await self._notify(summary)
        return summary

    async def verify_stream(self) -> dict[str, object]:
        started = self._now()
        try:
            readiness = await self._stream_readiness.readiness()
            stream_status = self._stream_service.status_dict()
            running = bool(readiness.get("stream_already_running"))
            connected = bool(readiness.get("stream_connected"))
            configured = _as_int(readiness.get("configured_symbols"))
            subscribed = _as_int(readiness.get("subscribed_symbols"))
            last_error = readiness.get("last_error")
            stale = bool(stream_status.get("stale"))
            connection_ready = (
                connected or not self._settings.market_ops_require_stream_connected
            )
            healthy = (
                running
                and connection_ready
                and configured == subscribed
                and last_error is None
                and not stale
            )
            if stale:
                event = "candle_health_warning"
                message = "Stream is connected but market-data activity is stale."
            elif healthy:
                event = "stream_verify_ok"
                message = "Stream connectivity and subscriptions are healthy."
            else:
                event = "stream_not_connected"
                message = "Stream connectivity or subscription health is not ready."
            summary = self._summary(
                started=started,
                ok=healthy,
                skipped=False,
                event=event,
                level="info" if healthy else "warning",
                message=message,
                details={
                    "running": running,
                    "connected": connected,
                    "configured_symbols": configured,
                    "subscribed_symbols": subscribed,
                    "last_error": last_error,
                    "stale": stale,
                },
            )
        except Exception:
            summary = self._failed(started, "stream_not_connected", "Stream verification failed.")
        await self._notify(summary)
        return summary

    async def run_universe_selection(self) -> dict[str, object]:
        started = self._now()
        if not self._settings.market_ops_use_universe_selection:
            summary = self._summary(
                started=started,
                ok=True,
                skipped=True,
                event="universe_selection_skipped",
                level="info",
                message="Market-ops universe selection is disabled.",
                details={},
            )
            await self._notify(summary)
            return summary
        if not self._settings.universe_selection_enabled:
            summary = self._summary(
                started=started,
                ok=False,
                skipped=True,
                event="universe_selection_skipped",
                level="warning",
                message="Universe selection is disabled.",
                details={"recommended_action": "enable_universe_selection"},
            )
            await self._notify(summary)
            return summary
        await self._notifier.notify(
            level="info",
            event="universe_selection_started",
            message="Universe selection started.",
            details={
                "min_candles": self._settings.market_ops_require_min_candles_for_universe,
                "dry_run": self._settings.market_ops_dry_run,
            },
        )
        try:
            run = await self._universe_service.select(
                dry_run=self._settings.market_ops_dry_run,
                use_current_session=True,
                min_candles=self._settings.market_ops_require_min_candles_for_universe,
                stale_policy="exclude",
            )
            summary = self._summary(
                started=started,
                ok=True,
                skipped=False,
                event="universe_selection_completed",
                level="info",
                message="Universe selection completed.",
                details={
                    "selected_count": run.selected_count,
                    "selected_symbols": run.selected_symbols[:20],
                    "scored_count": run.scored_count,
                    "warnings": run.warnings,
                },
            )
        except (UniverseSelectionDisabledError, UniverseInputError):
            summary = self._summary(
                started=started,
                ok=False,
                skipped=True,
                event="universe_selection_skipped",
                level="warning",
                message="Universe selection could not run with current local data or config.",
                details={},
            )
        except Exception:
            summary = self._failed(
                started,
                "universe_selection_failed",
                "Universe selection failed.",
            )
        await self._notify(summary)
        return summary

    async def run_scanner_batch(self) -> dict[str, object]:
        started = self._now()
        use_selected = self._settings.market_ops_use_selected_universe_for_scanner
        await self._notifier.notify(
            level="info",
            event="scanner_batch_started",
            message="Scanner batch started.",
            details={
                "symbol_source": (
                    "latest_selected_universe" if use_selected else "market_watchlist"
                ),
                "dry_run": self._settings.market_ops_dry_run,
            },
        )
        try:
            result = await self._scanner_service.run_batch(
                symbols=None,
                store_rejections=self._settings.market_ops_store_rejections,
                dry_run=self._settings.market_ops_dry_run,
                use_latest_universe=use_selected,
            )
            candidates = [
                item.symbol
                for item in result.per_symbol
                if item.candidates > 0
            ]
            summary = self._summary(
                started=started,
                ok=not result.errors,
                skipped=False,
                event="scanner_batch_completed",
                level="info" if not result.errors else "warning",
                message="Scanner batch completed.",
                details={
                    "symbol_source": (
                        "latest_selected_universe" if use_selected else "market_watchlist"
                    ),
                    "total_candidates": result.total_candidates,
                    "total_rejected": result.total_rejected,
                    "total_inserted": result.total_inserted,
                    "candidate_symbols": candidates,
                    "errors": result.errors,
                },
            )
            if result.total_candidates:
                await self._notifier.notify(
                    level="info",
                    event="scanner_candidates_found",
                    message="Deterministic scanner candidates were found.",
                    details={
                        "candidate_count": result.total_candidates,
                        "symbols": candidates,
                    },
                )
            decision_summary = await self._run_decision_auto_evaluation(result)
            summary["details"]["decision_auto_evaluation"] = decision_summary  # type: ignore[index]
        except SelectedUniverseMissingError:
            summary = self._summary(
                started=started,
                ok=False,
                skipped=True,
                event="scanner_batch_failed",
                level="warning",
                message="Scanner batch skipped because selected universe is missing.",
                details={"recommended_action": "run_universe_selection"},
            )
        except Exception:
            summary = self._failed(started, "scanner_batch_failed", "Scanner batch failed.")
        await self._notify(summary)
        return summary

    def decision_auto_status(self) -> dict[str, object]:
        if self._decision_automation is None:
            return {
                "enabled": False,
                "decision_enabled": self._settings.openai_decision_enabled,
                "available": False,
                "last_summary": None,
            }
        return self._decision_automation.status()

    async def _run_decision_auto_evaluation(
        self,
        result: ScannerBatchResult,
    ) -> dict[str, object]:
        if self._decision_automation is None:
            return {
                "attempted": 0,
                "created": 0,
                "existing": 0,
                "failed": 0,
                "skipped": 1,
                "skipped_reason": "decision_automation_unavailable",
                "notified": 0,
                "truncated": False,
                "results": [],
            }
        try:
            return await self._decision_automation.evaluate_scanner_batch(
                started_at=result.started_at,
                finished_at=result.finished_at,
                symbols=[item.symbol for item in result.per_symbol],
                dry_run=self._settings.market_ops_dry_run,
                candidate_count=result.total_candidates,
            )
        except Exception:
            return {
                "attempted": 0,
                "created": 0,
                "existing": 0,
                "failed": 1,
                "skipped": 0,
                "error_code": "decision_auto_batch_failed",
                "notified": 0,
                "truncated": False,
                "results": [],
            }

    async def stop_stream(self) -> dict[str, object]:
        started = self._now()
        try:
            before = self._stream_service.status_dict()
            if not before.get("running"):
                summary = self._summary(
                    started=started,
                    ok=True,
                    skipped=True,
                    event="stream_stop_completed",
                    level="info",
                    message="Market-data stream is already stopped.",
                    details={"running": False},
                )
            else:
                status = await self._stream_service.stop()
                summary = self._summary(
                    started=started,
                    ok=True,
                    skipped=False,
                    event="stream_stop_completed",
                    level="info",
                    message="Market-data stream stopped.",
                    details=_stream_details(status),
                )
        except Exception:
            summary = self._failed(started, "stream_stop_failed", "Stream stop failed.")
        await self._notify(summary)
        return summary

    async def test_notification(self) -> dict[str, object]:
        started = self._now()
        result = await self._notifier.test_notification()
        return self._summary(
            started=started,
            ok=result.ok,
            skipped=result.skipped,
            event=result.event,
            level="info" if result.ok else "warning",
            message=(
                "Test notification processed."
                if result.ok
                else "Test notification could not be delivered."
            ),
            details={"provider": result.provider, "error": result.error},
        )

    async def notify_scheduler_event(
        self,
        *,
        event: str,
        level: str,
        message: str,
        details: dict[str, object] | None = None,
    ) -> None:
        """Send scheduler lifecycle/error events without exposing notifier internals."""
        await self._notifier.notify(
            level=level,
            event=event,
            message=message,
            details=details or {},
        )

    async def send_kite_login_link(self) -> bool:
        """Send a transient manual-login helper link when every safety gate is enabled."""
        provider = self._settings.market_ops_notify_provider.strip().lower()
        if (
            not self._settings.market_ops_send_kite_login_link
            or not self._settings.market_ops_notify_enabled
            or provider != "telegram"
            or not self._settings.kite_auth_enabled
            or not self._settings.kite_api_key
            or not self._settings.kite_api_secret
            or not self._settings.kite_redirect_url
            or self._kite_login_url_provider is None
        ):
            return False
        try:
            response = await self._kite_login_url_provider.create_login_url()
            login_url = response.get("login_url", "")
            if not login_url:
                return False
            result = await self._notifier.notify(
                level="warning",
                event="kite_login_link_sent",
                message=f"Complete the required manual Kite login: {login_url}",
                details={},
            )
            return result.ok and not result.skipped
        except Exception:
            await self._notifier.notify(
                level="warning",
                event="kite_login_link_unavailable",
                message="A Kite login link could not be generated. Use the operator login route.",
                details={},
            )
            return False

    async def _notify(self, summary: dict[str, object]) -> None:
        await self._notifier.notify(
            level=str(summary["level"]),
            event=str(summary["event"]),
            message=str(summary["message"]),
            details=cast(dict[str, object], summary["details"]),
        )

    def _failed(self, started: datetime, event: str, message: str) -> dict[str, object]:
        return self._summary(
            started=started,
            ok=False,
            skipped=False,
            event=event,
            level="error",
            message=message,
            details={},
        )

    def _summary(
        self,
        *,
        started: datetime,
        ok: bool,
        skipped: bool,
        event: str,
        level: str,
        message: str,
        details: dict[str, object],
    ) -> dict[str, object]:
        return {
            "ok": ok,
            "skipped": skipped,
            "event": event,
            "level": level,
            "message": message,
            "started_at": started.isoformat(),
            "finished_at": self._now().isoformat(),
            "details": details,
        }

    def _now(self) -> datetime:
        now = self._now_provider()
        return now if now.tzinfo else now.replace(tzinfo=timezone.utc)


def _stream_details(status: dict[str, object]) -> dict[str, object]:
    return {
        "running": bool(status.get("running")),
        "connected": bool(status.get("connected")),
        "configured_symbols": status.get("configured_symbols", 0),
        "subscribed_symbols": status.get("subscribed_symbols", 0),
        "last_error": status.get("last_error"),
    }


def _as_int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0
