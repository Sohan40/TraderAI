from app.models import metadata


def test_initial_storage_schema_contains_p01_tables() -> None:
    expected_tables = {
        "system_events",
        "trading_sessions",
        "instruments",
        "candles",
        "signals",
        "recommendations",
        "risk_checks",
        "orders",
        "order_events",
        "trades",
        "journal_entries",
        "model_runs",
        "broker_sessions",
        "universe_selection_runs",
    }

    assert expected_tables.issubset(metadata.tables)
    assert "source" in metadata.tables["candles"].c
    assert "signal_status" in metadata.tables["signals"].c
    assert "veto_reasons" in metadata.tables["signals"].c
    assert "signal_key" in metadata.tables["signals"].c
    assert "simulated" in metadata.tables["orders"].c
    assert "signal_id" in metadata.tables["orders"].c
    assert "simulated" in metadata.tables["trades"].c
    assert "signal_id" in metadata.tables["trades"].c
    assert "gross_pnl" in metadata.tables["trades"].c
    assert "estimated_costs" in metadata.tables["trades"].c
    assert "net_pnl" in metadata.tables["trades"].c
    assert "exit_reason" in metadata.tables["trades"].c
    assert "uq_trades_paper_signal_id" in {
        index.name for index in metadata.tables["trades"].indexes
    }
