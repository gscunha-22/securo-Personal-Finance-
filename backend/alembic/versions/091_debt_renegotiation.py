"""Debt renegotiation inventory fields, cash plan and written offers."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "091"
down_revision = "090"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("debts", sa.Column("product", sa.String(40), nullable=False, server_default="outro"))
    op.add_column(
        "debts",
        sa.Column("delinquency_status", sa.String(20), nullable=False, server_default="em_dia"),
    )
    op.add_column("debts", sa.Column("days_past_due", sa.Integer(), nullable=False, server_default="0"))
    op.add_column(
        "debts",
        sa.Column("penalty_amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
    )
    op.add_column("debts", sa.Column("installment_amount", sa.Numeric(15, 2), nullable=True))
    op.add_column("debts", sa.Column("remaining_term_months", sa.Integer(), nullable=True))
    op.add_column("debts", sa.Column("cet_annual_informed", sa.Numeric(10, 4), nullable=True))
    op.add_column("debts", sa.Column("due_date", sa.Date(), nullable=True))
    op.add_column("debts", sa.Column("guarantee", sa.String(40), nullable=False, server_default="nenhuma"))

    op.create_table(
        "debt_cash_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("income", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("variable_income", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("essential", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("discretionary", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("reserve", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("shock", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("steps", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace_id", name="uq_debt_cash_plans_workspace"),
    )
    op.create_index("ix_debt_cash_plans_workspace_id", "debt_cash_plans", ["workspace_id"])

    op.create_table(
        "debt_offers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "debt_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("debts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("path", sa.String(20), nullable=False, server_default="outro"),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("payoff", sa.Numeric(15, 2), nullable=False),
        sa.Column("cet_monthly", sa.Numeric(10, 4), nullable=True),
        sa.Column("installment", sa.Numeric(15, 2), nullable=False),
        sa.Column("term_months", sa.Integer(), nullable=True),
        sa.Column("down_payment", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("waiver", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("grace", sa.String(20), nullable=False, server_default="nao"),
        sa.Column("new_guarantee", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("operational_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_debt_offers_debt_id", "debt_offers", ["debt_id"])
    op.create_index("ix_debt_offers_workspace_id", "debt_offers", ["workspace_id"])


def downgrade() -> None:
    op.drop_table("debt_offers")
    op.drop_table("debt_cash_plans")
    for column in (
        "guarantee",
        "due_date",
        "cet_annual_informed",
        "remaining_term_months",
        "installment_amount",
        "penalty_amount",
        "days_past_due",
        "delinquency_status",
        "product",
    ):
        op.drop_column("debts", column)
