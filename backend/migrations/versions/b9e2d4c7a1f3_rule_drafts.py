"""plain-language rule drafts

Revision ID: b9e2d4c7a1f3
Revises: d7b1f4a6c2e8
Create Date: 2026-11-05 15:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b9e2d4c7a1f3'
down_revision: str | Sequence[str] | None = 'd7b1f4a6c2e8'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "rule_drafts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("items", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.Enum("open", "confirmed", name="ruledraftstatus", native_enum=False, length=50), server_default="open", nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('open', 'confirmed')", name=op.f("ck_rule_drafts_status")),
        sa.CheckConstraint("(status = 'confirmed') = (confirmed_at IS NOT NULL)", name=op.f("ck_rule_drafts_confirmed_fields_together")),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], name=op.f("fk_rule_drafts_created_by_id_users"), ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rule_drafts")),
    )
    op.create_index(op.f("ix_rule_drafts_created_by_id"), "rule_drafts", ["created_by_id"], unique=False)
    # Empty on every version signed so far; see FINGERPRINTED_WHEN_SET.
    op.add_column("compliance_rule_versions", sa.Column("source_text", sa.Text(), nullable=True))
    op.drop_constraint(op.f("ck_document_types_origin"), "document_types", type_="check")
    op.create_check_constraint(
        op.f("ck_document_types_origin"), "document_types", "origin IN ('seeded', 'discovered', 'configured')"
    )


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    blockers = {
        "rule versions written in plain language": "SELECT EXISTS (SELECT 1 FROM compliance_rule_versions WHERE source_text IS NOT NULL)",
        "document types named by rules": "SELECT EXISTS (SELECT 1 FROM document_types WHERE origin = 'configured')",
    }
    found = [name for name, query in blockers.items() if bind.execute(sa.text(query)).scalar()]
    if found:
        raise RuntimeError(f"Can't downgrade: the database holds {', '.join(found)}.")
    op.drop_constraint(op.f("ck_document_types_origin"), "document_types", type_="check")
    op.create_check_constraint(op.f("ck_document_types_origin"), "document_types", "origin IN ('seeded', 'discovered')")
    op.drop_column("compliance_rule_versions", "source_text")
    op.drop_index(op.f("ix_rule_drafts_created_by_id"), table_name="rule_drafts")
    op.drop_table("rule_drafts")
