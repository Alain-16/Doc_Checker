"""condition rules, vendor-level findings, number attributes

The engine gains QA's own rules (kind 'condition'), rules documents can't prove
(kind 'manual_check'), a level on every rule, findings and alerts about a whole
vendor, and number attributes.

Revision ID: d7b1f4a6c2e8
Revises: c3d5e7f90a12
Create Date: 2026-11-05 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd7b1f4a6c2e8'
down_revision: str | Sequence[str] | None = 'c3d5e7f90a12'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_KINDS = (
    "'document_age', 'missing_field', 'record_completeness', 'date_conflict', 'low_confidence', "
    "'missing_document', 'revision_without_replacement'"
)
NEW_KINDS = f"{OLD_KINDS}, 'condition', 'manual_check'"
OLD_VALUE_TYPES = "'text', 'text_list', 'date', 'status', 'records'"
NEW_VALUE_TYPES = f"{OLD_VALUE_TYPES}, 'number'"


def replace_check(name: str, table: str, condition: str) -> None:
    op.drop_constraint(op.f(name), table, type_="check")
    op.create_check_constraint(op.f(name), table, condition)


def upgrade() -> None:
    """Upgrade schema."""
    replace_check("ck_compliance_rules_kind", "compliance_rules", f"kind IN ({NEW_KINDS})")
    replace_check("ck_key_attributes_value_type", "key_attributes", f"value_type IN ({NEW_VALUE_TYPES})")

    # Every existing kind has one fixed level, so existing rules can be filled in.
    op.add_column("compliance_rules", sa.Column("level", sa.Enum("document", "component", "vendor", name="rulelevel", native_enum=False, length=50), nullable=True))
    op.execute(
        "UPDATE compliance_rules SET level = CASE WHEN kind IN "
        "('missing_document', 'revision_without_replacement') THEN 'component' ELSE 'document' END"
    )
    op.alter_column("compliance_rules", "level", nullable=False)
    op.create_check_constraint(
        op.f("ck_compliance_rules_level"), "compliance_rules", "level IN ('document', 'component', 'vendor')"
    )

    op.add_column("compliance_findings", sa.Column("vendor_id", sa.Uuid(), nullable=True))
    op.create_index(op.f("ix_compliance_findings_vendor_id"), "compliance_findings", ["vendor_id"], unique=False)
    op.create_foreign_key(
        op.f("fk_compliance_findings_vendor_id_vendors"), "compliance_findings", "vendors", ["vendor_id"], ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "uq_compliance_findings_open_vendor_rule", "compliance_findings", ["vendor_id", "rule_code"],
        unique=True, postgresql_where=sa.text("NOT resolved AND vendor_id IS NOT NULL"),
    )
    replace_check(
        "ck_compliance_findings_one_subject", "compliance_findings",
        "num_nonnulls(document_id, component_id, vendor_id) = 1",
    )

    op.add_column("alerts", sa.Column("vendor_id", sa.Uuid(), nullable=True))
    op.create_index(op.f("ix_alerts_vendor_id"), "alerts", ["vendor_id"], unique=False)
    op.create_foreign_key(
        op.f("fk_alerts_vendor_id_vendors"), "alerts", "vendors", ["vendor_id"], ["id"], ondelete="RESTRICT"
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Rule versions are append-only and findings are history: what only this
    # revision can hold can't be removed quietly, so the downgrade refuses.
    bind = op.get_bind()
    blockers = {
        "condition or manual_check rules": "SELECT EXISTS (SELECT 1 FROM compliance_rules WHERE kind IN ('condition', 'manual_check') OR level = 'vendor')",
        "vendor findings": "SELECT EXISTS (SELECT 1 FROM compliance_findings WHERE vendor_id IS NOT NULL)",
        "number attributes": "SELECT EXISTS (SELECT 1 FROM key_attributes WHERE value_type = 'number')",
    }
    found = [name for name, query in blockers.items() if bind.execute(sa.text(query)).scalar()]
    if found:
        raise RuntimeError(f"Can't downgrade: the database holds {', '.join(found)}.")

    op.drop_constraint(op.f("fk_alerts_vendor_id_vendors"), "alerts", type_="foreignkey")
    op.drop_index(op.f("ix_alerts_vendor_id"), table_name="alerts")
    op.drop_column("alerts", "vendor_id")

    replace_check(
        "ck_compliance_findings_one_subject", "compliance_findings", "(document_id IS NULL) <> (component_id IS NULL)"
    )
    op.drop_index(
        "uq_compliance_findings_open_vendor_rule", table_name="compliance_findings",
        postgresql_where=sa.text("NOT resolved AND vendor_id IS NOT NULL"),
    )
    op.drop_constraint(op.f("fk_compliance_findings_vendor_id_vendors"), "compliance_findings", type_="foreignkey")
    op.drop_index(op.f("ix_compliance_findings_vendor_id"), table_name="compliance_findings")
    op.drop_column("compliance_findings", "vendor_id")

    op.drop_constraint(op.f("ck_compliance_rules_level"), "compliance_rules", type_="check")
    op.drop_column("compliance_rules", "level")
    replace_check("ck_key_attributes_value_type", "key_attributes", f"value_type IN ({OLD_VALUE_TYPES})")
    replace_check("ck_compliance_rules_kind", "compliance_rules", f"kind IN ({OLD_KINDS})")
