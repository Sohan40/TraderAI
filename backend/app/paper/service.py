"""P06 paper-trading service orchestration."""

from __future__ import annotations

from datetime import datetime, time, timezone
from decimal import Decimal

from app.analysis.indicators import IST
from app.core.config import Settings
from app.paper.exceptions import (
    LiveModeNotImplementedError,
    PaperConfigError,
    PaperDisabledError,
    PaperModeDisabledError,
)
from app.paper.reporting import build_paper_report
from app.paper.repository import DuplicatePaperTradeError, PaperRepository
from app.paper.schemas import (
    PaperConfig,
    PaperExitReason,
    PaperInstruction,
    PaperMode,
    PaperReplaySummary,
    PaperSignal,
    PaperSimulationResult,
    rejected_outcome,
)
from app.paper.simulator import PaperSimulator

PAPER_CANDLE_LIMIT = 100_000


class PaperService:
    """Safe service for deterministic paper replay and reporting."""

    def __init__(
        self,
        *,
        settings: Settings,
        repository: PaperRepository,
        simulator: PaperSimulator | None = None,
    ) -> None:
        self._settings = settings
        self._config = paper_config_from_settings(settings)
        self._repository = repository
        self._simulator = simulator or PaperSimulator()

    async def status(self) -> dict[str, object]:
        """Return non-sensitive paper engine status."""
        return {
            "paper_enabled": self._config.enabled,
            "paper_mode": self._config.mode.value,
            "live_supported": False,
            "simulated_only": True,
            "default_quantity": self._config.default_quantity,
            "max_trades_per_day": self._config.max_trades_per_day,
            "force_flat_time_ist": self._config.force_flat_time_ist.strftime("%H:%M"),
            "estimated_cost_per_trade": str(self._config.estimated_cost_per_trade),
        }

    async def run_replay(
        self,
        *,
        symbol: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 100,
    ) -> PaperReplaySummary:
        """Load P05 candidates and simulate paper lifecycle in PAPER mode only."""
        self._ensure_replay_allowed()
        bounded_limit = max(1, min(limit, 500))
        candidate_signals = await self._repository.load_candidate_signals(
            symbol=symbol,
            start=start,
            end=end,
            limit=bounded_limit,
        )
        outcomes = []
        for signal in candidate_signals:
            duplicate = await self._duplicate_outcome_if_exists(signal)
            if duplicate is not None:
                outcomes.append(duplicate)
                continue
            capped = await self._daily_cap_outcome_if_reached(signal)
            if capped is not None:
                outcomes.append(capped)
                continue
            candles = await self._repository.load_candles(
                symbol=signal.symbol,
                start=signal.signal_time,
                end=end or _default_replay_end(signal.signal_time),
                limit=PAPER_CANDLE_LIMIT,
            )
            instruction_or_rejection = self._simulator.build_instruction(
                signal=signal,
                candles=candles,
                config=self._config,
            )
            if isinstance(instruction_or_rejection, PaperInstruction):
                outcome = self._simulator.simulate(
                    instruction=instruction_or_rejection,
                    candles=candles,
                    config=self._config,
                )
            else:
                outcome = instruction_or_rejection
            try:
                await self._repository.record_paper_outcome(signal=signal, outcome=outcome)
            except DuplicatePaperTradeError:
                outcome = rejected_outcome(
                    signal=signal,
                    config=self._config,
                    exit_reason=PaperExitReason.DUPLICATE_SIGNAL,
                    rejection_reason="duplicate_signal",
                )
                await self._repository.record_paper_outcome(signal=signal, outcome=outcome)
            outcomes.append(outcome)
        return PaperReplaySummary(
            paper_enabled=self._config.enabled,
            paper_mode=self._config.mode,
            signals_loaded=len(candidate_signals),
            outcomes=outcomes,
        )

    async def report(self, *, limit: int = 1000) -> dict[str, object]:
        """Return aggregate paper journal report."""
        bounded_limit = max(1, min(limit, 10_000))
        outcomes = await self._repository.list_journal_outcomes(limit=bounded_limit)
        return build_paper_report(
            paper_enabled=self._config.enabled,
            paper_mode=self._config.mode,
            outcomes=outcomes,
        )

    async def trades(self, *, limit: int = 100) -> list[dict[str, object]]:
        """Return bounded recent paper journal outcomes."""
        bounded_limit = max(1, min(limit, 500))
        return await self._repository.list_journal_outcomes(limit=bounded_limit)

    def _ensure_replay_allowed(self) -> None:
        if self._config.mode == PaperMode.LIVE:
            raise LiveModeNotImplementedError("LIVE paper mode is disabled and not implemented.")
        if not self._config.enabled:
            raise PaperDisabledError("Paper engine is disabled.")
        if self._config.mode in {PaperMode.OFF, PaperMode.SHADOW}:
            raise PaperModeDisabledError(f"{self._config.mode.value} mode does not create fills.")
        if self._config.mode != PaperMode.PAPER:
            raise PaperConfigError("Unsupported paper mode.")

    async def _duplicate_outcome_if_exists(
        self,
        signal: PaperSignal,
    ) -> PaperSimulationResult | None:
        if not await self._repository.paper_trade_exists(signal_id=signal.id):
            return None
        outcome = rejected_outcome(
            signal=signal,
            config=self._config,
            exit_reason=PaperExitReason.DUPLICATE_SIGNAL,
            rejection_reason="duplicate_signal",
        )
        await self._repository.record_paper_outcome(signal=signal, outcome=outcome)
        return outcome

    async def _daily_cap_outcome_if_reached(
        self,
        signal: PaperSignal,
    ) -> PaperSimulationResult | None:
        if self._config.max_trades_per_day < 1:
            rejection_reason = "paper_max_trades_per_day_invalid"
        else:
            count = await self._repository.count_paper_trades_for_day(
                signal_time=signal.signal_time,
            )
            if count < self._config.max_trades_per_day:
                return None
            rejection_reason = "paper_max_trades_per_day_reached"
        outcome = rejected_outcome(
            signal=signal,
            config=self._config,
            exit_reason=PaperExitReason.MODE_DISABLED,
            rejection_reason=rejection_reason,
        )
        await self._repository.record_paper_outcome(signal=signal, outcome=outcome)
        return outcome


def paper_config_from_settings(settings: Settings) -> PaperConfig:
    """Parse paper settings without consulting production trading mode."""
    try:
        mode = PaperMode(settings.paper_mode.upper())
    except ValueError as exc:
        raise PaperConfigError("Unsupported PAPER_MODE configured.") from exc
    force_flat = _parse_force_flat(settings.paper_force_flat_time_ist)
    return PaperConfig(
        enabled=settings.paper_enabled,
        mode=mode,
        max_trades_per_day=settings.paper_max_trades_per_day,
        default_quantity=settings.paper_default_quantity,
        entry_buffer_pct=Decimal(str(settings.paper_entry_buffer_pct)),
        stop_pct=Decimal(str(settings.paper_stop_pct)),
        target_r_multiple=Decimal(str(settings.paper_target_r_multiple)),
        force_flat_time_ist=force_flat,
        estimated_cost_per_trade=Decimal(str(settings.paper_estimated_cost_per_trade)),
    )


def _parse_force_flat(value: str) -> time:
    try:
        hour, minute = (int(part) for part in value.split(":", 1))
        return time(hour=hour, minute=minute)
    except ValueError as exc:
        raise PaperConfigError("PAPER_FORCE_FLAT_TIME_IST must be HH:MM.") from exc


def _default_replay_end(signal_time: datetime) -> datetime:
    signal_date = signal_time.astimezone(IST).date()
    end_ist = datetime.combine(signal_date, time(23, 59), tzinfo=IST)
    return end_ist.astimezone(timezone.utc)
