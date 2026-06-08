"""Deterministic paper fill simulator over completed candles only."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from app.analysis.indicators import IST
from app.analysis.schemas import CompletedBar
from app.paper.schemas import (
    PaperConfig,
    PaperExitReason,
    PaperInstruction,
    PaperSignal,
    PaperSimulationResult,
    completed_trade_outcome,
    no_fill_outcome,
    rejected_outcome,
)
from app.scanners.schemas import CANDIDATE, LONG

PRICE_QUANT = Decimal("0.000001")
ONE_HUNDRED = Decimal("100")


class PaperSimulator:
    """Build paper instructions and simulate long-only limit lifecycle events."""

    def build_instruction(
        self,
        *,
        signal: PaperSignal,
        candles: list[CompletedBar],
        config: PaperConfig,
    ) -> PaperInstruction | PaperSimulationResult:
        """Create a deterministic paper instruction or a rejected paper outcome."""
        rejection = self._validate_signal(signal=signal, config=config)
        if rejection is not None:
            return rejection

        signal_candle = _find_signal_candle(signal=signal, candles=candles)
        if signal_candle is None:
            return rejected_outcome(
                signal=signal,
                config=config,
                exit_reason=PaperExitReason.INVALID_SIGNAL_CONTEXT,
                rejection_reason="signal_candle_unavailable",
            )

        entry = _q(
            signal_candle.close_price
            * (Decimal("1") + (config.entry_buffer_pct / ONE_HUNDRED))
        )
        stop = _q(entry * (Decimal("1") - (config.stop_pct / ONE_HUNDRED)))
        unit_risk = entry - stop
        if entry <= 0 or stop <= 0 or unit_risk <= 0:
            return rejected_outcome(
                signal=signal,
                config=config,
                exit_reason=PaperExitReason.INVALID_SIGNAL_CONTEXT,
                rejection_reason="invalid_entry_stop_context",
            )
        if config.default_quantity < 1:
            return rejected_outcome(
                signal=signal,
                config=config,
                exit_reason=PaperExitReason.INVALID_SIGNAL_CONTEXT,
                rejection_reason="invalid_paper_quantity",
            )
        target = _q(entry + (config.target_r_multiple * unit_risk))
        if target <= entry:
            return rejected_outcome(
                signal=signal,
                config=config,
                exit_reason=PaperExitReason.INVALID_SIGNAL_CONTEXT,
                rejection_reason="invalid_target_context",
            )
        quantity = config.default_quantity
        return PaperInstruction(
            signal_id=signal.id,
            signal_key=signal.signal_key,
            symbol=signal.symbol,
            strategy_name=signal.strategy_name,
            signal_time=signal.signal_time,
            entry_reference_price=entry,
            stop_price=stop,
            target_price=target,
            quantity=quantity,
            paper_max_risk=_q(unit_risk * Decimal(quantity)),
            paper_mode=config.mode,
            estimated_costs=config.estimated_cost_per_trade,
        )

    def simulate(
        self,
        *,
        instruction: PaperInstruction,
        candles: list[CompletedBar],
        config: PaperConfig,
    ) -> PaperSimulationResult:
        """Simulate entry, stop, target, time exit and force-flat from future bars."""
        ordered = sorted(candles, key=lambda candle: candle.started_at)
        same_day_future = [
            candle
            for candle in ordered
            if _session_date(candle.started_at) == _session_date(instruction.signal_time)
            and candle.started_at > instruction.signal_time
        ]
        entry_candle = next(
            (
                candle
                for candle in same_day_future
                if not _at_or_after_force_flat(candle.started_at, config)
                and candle.low_price <= instruction.entry_reference_price <= candle.high_price
            ),
            None,
        )
        if entry_candle is None:
            return no_fill_outcome(instruction=instruction)

        exit_candles = [
            candle for candle in same_day_future if candle.started_at > entry_candle.started_at
        ]
        if not exit_candles:
            return completed_trade_outcome(
                instruction=instruction,
                entry_fill_time=entry_candle.started_at,
                exit_time=None,
                exit_price=None,
                exit_reason=PaperExitReason.DATA_ENDED,
            )

        last_eligible: CompletedBar | None = None
        for candle in exit_candles:
            if _at_or_after_force_flat(candle.started_at, config):
                return completed_trade_outcome(
                    instruction=instruction,
                    entry_fill_time=entry_candle.started_at,
                    exit_time=candle.started_at,
                    exit_price=candle.close_price,
                    exit_reason=PaperExitReason.FORCE_FLAT,
                )
            if candle.low_price <= instruction.stop_price:
                return completed_trade_outcome(
                    instruction=instruction,
                    entry_fill_time=entry_candle.started_at,
                    exit_time=candle.started_at,
                    exit_price=instruction.stop_price,
                    exit_reason=PaperExitReason.STOP_HIT,
                )
            if candle.high_price >= instruction.target_price:
                return completed_trade_outcome(
                    instruction=instruction,
                    entry_fill_time=entry_candle.started_at,
                    exit_time=candle.started_at,
                    exit_price=instruction.target_price,
                    exit_reason=PaperExitReason.TARGET_HIT,
                )
            last_eligible = candle

        if last_eligible is not None:
            return completed_trade_outcome(
                instruction=instruction,
                entry_fill_time=entry_candle.started_at,
                exit_time=last_eligible.started_at,
                exit_price=last_eligible.close_price,
                exit_reason=PaperExitReason.TIME_EXIT,
            )
        return completed_trade_outcome(
            instruction=instruction,
            entry_fill_time=entry_candle.started_at,
            exit_time=None,
            exit_price=None,
            exit_reason=PaperExitReason.DATA_ENDED,
        )

    def _validate_signal(
        self,
        *,
        signal: PaperSignal,
        config: PaperConfig,
    ) -> PaperSimulationResult | None:
        if signal.signal_status != CANDIDATE:
            return rejected_outcome(
                signal=signal,
                config=config,
                exit_reason=PaperExitReason.INVALID_SIGNAL_CONTEXT,
                rejection_reason="signal_is_not_candidate",
            )
        if signal.direction != LONG:
            return rejected_outcome(
                signal=signal,
                config=config,
                exit_reason=PaperExitReason.INVALID_SIGNAL_CONTEXT,
                rejection_reason="signal_direction_not_long",
            )
        if signal.veto_reasons:
            return rejected_outcome(
                signal=signal,
                config=config,
                exit_reason=PaperExitReason.INVALID_SIGNAL_CONTEXT,
                rejection_reason="candidate_has_veto_reasons",
            )
        features: dict[str, Any] = signal.features
        if not features:
            return rejected_outcome(
                signal=signal,
                config=config,
                exit_reason=PaperExitReason.INVALID_SIGNAL_CONTEXT,
                rejection_reason="missing_signal_features",
            )
        if features.get("signal_status") != CANDIDATE:
            return rejected_outcome(
                signal=signal,
                config=config,
                exit_reason=PaperExitReason.INVALID_SIGNAL_CONTEXT,
                rejection_reason="feature_snapshot_not_candidate",
            )
        feature_vetoes = features.get("veto_reasons")
        if feature_vetoes not in ([], None):
            return rejected_outcome(
                signal=signal,
                config=config,
                exit_reason=PaperExitReason.INVALID_SIGNAL_CONTEXT,
                rejection_reason="feature_snapshot_has_veto_reasons",
            )
        if not isinstance(features.get("indicator_values"), dict):
            return rejected_outcome(
                signal=signal,
                config=config,
                exit_reason=PaperExitReason.INVALID_SIGNAL_CONTEXT,
                rejection_reason="missing_indicator_snapshot",
            )
        if not isinstance(features.get("data_quality"), dict):
            return rejected_outcome(
                signal=signal,
                config=config,
                exit_reason=PaperExitReason.INVALID_SIGNAL_CONTEXT,
                rejection_reason="missing_data_quality_snapshot",
            )
        return None


def _find_signal_candle(
    *,
    signal: PaperSignal,
    candles: list[CompletedBar],
) -> CompletedBar | None:
    return next((candle for candle in candles if candle.started_at == signal.signal_time), None)


def _session_date(value: datetime) -> object:
    return value.astimezone(IST).date()


def _at_or_after_force_flat(value: datetime, config: PaperConfig) -> bool:
    return value.astimezone(IST).time() >= config.force_flat_time_ist


def _q(value: Decimal) -> Decimal:
    return value.quantize(PRICE_QUANT, rounding=ROUND_HALF_UP)
