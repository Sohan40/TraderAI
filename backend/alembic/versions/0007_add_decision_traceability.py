"""Add P07 decision traceability and idempotency fields."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0007_add_decision_traceability"
down_revision: str | None = "0006_add_universe_selection_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "model_runs",
        sa.Column("adapter", sa.String(length=50), server_default="fake", nullable=False),
    )
    op.add_column(
        "model_runs",
        sa.Column(
            "prompt_version",
            sa.String(length=50),
            server_default="p07_v1",
            nullable=False,
        ),
    )
    op.add_column(
        "model_runs",
        sa.Column("input_hash", sa.String(length=64), server_default="", nullable=False),
    )
    op.add_column("model_runs", sa.Column("latency_ms", sa.Integer(), nullable=True))
    op.add_column("model_runs", sa.Column("error_code", sa.String(length=100), nullable=True))
    op.create_index("ix_model_runs_input_hash", "model_runs", ["input_hash"], unique=False)

    op.add_column(
        "recommendations",
        sa.Column("confidence", sa.Numeric(5, 4), server_default="0", nullable=False),
    )
    op.add_column(
        "recommendations",
        sa.Column(
            "warnings",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "recommendations",
        sa.Column("evaluation_key", sa.String(length=64), nullable=True),
    )
    op.create_foreign_key(
        "fk_recommendations_model_run_id_model_runs",
        "recommendations",
        "model_runs",
        ["model_run_id"],
        ["id"],
    )
    op.create_index(
        "uq_recommendations_evaluation_key",
        "recommendations",
        ["evaluation_key"],
        unique=True,
    )
    op.create_index(
        "ix_recommendations_signal_created_at",
        "recommendations",
        ["signal_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_recommendations_signal_created_at", table_name="recommendations")
    op.drop_index("uq_recommendations_evaluation_key", table_name="recommendations")
    op.drop_constraint(
        "fk_recommendations_model_run_id_model_runs",
        "recommendations",
        type_="foreignkey",
    )
    op.drop_column("recommendations", "evaluation_key")
    op.drop_column("recommendations", "warnings")
    op.drop_column("recommendations", "confidence")

    op.drop_index("ix_model_runs_input_hash", table_name="model_runs")
    op.drop_column("model_runs", "error_code")
    op.drop_column("model_runs", "latency_ms")
    op.drop_column("model_runs", "input_hash")
    op.drop_column("model_runs", "prompt_version")
    op.drop_column("model_runs", "adapter")
