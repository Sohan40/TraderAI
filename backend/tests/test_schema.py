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
    }

    assert expected_tables.issubset(metadata.tables)
