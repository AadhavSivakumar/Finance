"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-08-17

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

asset_class = sa.Enum(
    "equity", "etf", "crypto", "cash", "other", name="asset_class"
)
txn_type = sa.Enum("buy", "sell", "dividend", name="txn_type")
revenue_interval = sa.Enum(
    "monthly", "annual", "one_time", name="revenue_interval"
)
expense_interval = sa.Enum(
    "monthly", "annual", "one_time", name="expense_interval"
)

MONEY = sa.Numeric(18, 2)
QTY = sa.Numeric(24, 8)
PRICE = sa.Numeric(18, 6)


def upgrade() -> None:
    op.create_table(
        "portfolios",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False, unique=True),
        sa.Column("base_currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "instruments",
        sa.Column("symbol", sa.String(24), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False, server_default=""),
        sa.Column("asset_class", asset_class, nullable=False, server_default="equity"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
    )

    op.create_table(
        "transactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "portfolio_id",
            sa.Integer(),
            sa.ForeignKey("portfolios.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("symbol", sa.String(24), nullable=False),
        sa.Column("type", txn_type, nullable=False),
        sa.Column("quantity", QTY, nullable=False),
        sa.Column("price", PRICE, nullable=False),
        sa.Column("fee", MONEY, nullable=False, server_default="0"),
        sa.Column("executed_at", sa.Date(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
    )
    op.create_index("ix_transactions_portfolio_id", "transactions", ["portfolio_id"])
    op.create_index("ix_transactions_symbol", "transactions", ["symbol"])
    op.create_index("ix_transactions_executed_at", "transactions", ["executed_at"])

    op.create_table(
        "price_bars",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("symbol", sa.String(24), nullable=False),
        sa.Column("bar_date", sa.Date(), nullable=False),
        sa.Column("open", PRICE, nullable=False),
        sa.Column("high", PRICE, nullable=False),
        sa.Column("low", PRICE, nullable=False),
        sa.Column("close", PRICE, nullable=False),
        sa.Column("volume", sa.Numeric(24, 2), nullable=False, server_default="0"),
        sa.UniqueConstraint("symbol", "bar_date", name="uq_price_bars_symbol_date"),
    )
    op.create_index("ix_price_bars_symbol_date", "price_bars", ["symbol", "bar_date"])

    op.create_table(
        "watchlist_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("symbol", sa.String(24), nullable=False, unique=True),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "revenue_streams",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("customer", sa.String(160), nullable=False, server_default=""),
        sa.Column(
            "interval", revenue_interval, nullable=False, server_default="monthly"
        ),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
    )
    op.create_index("ix_revenue_streams_start_date", "revenue_streams", ["start_date"])

    op.create_table(
        "expenses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("category", sa.String(80), nullable=False),
        sa.Column("vendor", sa.String(160), nullable=False, server_default=""),
        sa.Column(
            "interval", expense_interval, nullable=False, server_default="monthly"
        ),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
    )
    op.create_index("ix_expenses_category", "expenses", ["category"])
    op.create_index("ix_expenses_start_date", "expenses", ["start_date"])

    op.create_table(
        "cash_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("as_of", sa.Date(), nullable=False, unique=True),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
    )


def downgrade() -> None:
    op.drop_table("cash_snapshots")
    op.drop_table("expenses")
    op.drop_table("revenue_streams")
    op.drop_table("watchlist_items")
    op.drop_table("price_bars")
    op.drop_table("transactions")
    op.drop_table("instruments")
    op.drop_table("portfolios")

    # Postgres ENUM types outlive the tables that used them; drop explicitly or
    # the next `downgrade`/`upgrade` cycle fails with "type already exists".
    bind = op.get_bind()
    for enum in (expense_interval, revenue_interval, txn_type, asset_class):
        enum.drop(bind, checkfirst=True)
