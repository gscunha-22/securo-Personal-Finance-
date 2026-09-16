"""Interpretation versions, human decisions and parse-integrity conflicts."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "092"
down_revision = "091"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("vault_documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "extraction_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("document_extractions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("interpreter", sa.String(40), nullable=False, server_default="deterministic"),
        sa.Column("status", sa.String(40), nullable=False, server_default="completed"),
        sa.Column("parse_integrity", sa.String(40), nullable=False, server_default="not_applicable"),
        sa.Column("printed_total", sa.Numeric(15, 2), nullable=True),
        sa.Column("computed_total", sa.Numeric(15, 2), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("document_id", "version_number", name="uq_document_version_number"),
    )
    op.create_index("ix_document_versions_document_id", "document_versions", ["document_id"])
    op.create_index("ix_document_versions_workspace_id", "document_versions", ["workspace_id"])

    op.create_table(
        "human_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "candidate_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("import_candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("vault_documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_human_decisions_workspace_id", "human_decisions", ["workspace_id"])
    op.create_index("ix_human_decisions_candidate_id", "human_decisions", ["candidate_id"])

    op.create_table(
        "document_conflicts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("vault_documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("document_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_document_conflicts_document_id", "document_conflicts", ["document_id"])
    op.create_index("ix_document_conflicts_workspace_id", "document_conflicts", ["workspace_id"])


def downgrade() -> None:
    op.drop_table("document_conflicts")
    op.drop_table("human_decisions")
    op.drop_table("document_versions")
