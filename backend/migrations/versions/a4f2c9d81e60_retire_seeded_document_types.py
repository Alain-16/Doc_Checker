"""retire seeded document types

The system must serve any industry, so no document type is assumed up front
(decision 2026-11-03): types are discovered from real documents. The pharma
types seeded by 8c020861341e are retired, not deleted (documents and append-only
rule history point at them), unless a document already uses them.

Rules and key attributes tied to a retired type are switched off the
Part 11 way: rules get a new, inactive version with a reason; key attributes
are set inactive. REQUIRED_DOCUMENTS lists seeded type names in its
parameters, so it is switched off when any of them is retired.

Revision ID: a4f2c9d81e60
Revises: fd6cd933e4c2
Create Date: 2026-11-03 21:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a4f2c9d81e60'
down_revision: Union[str, Sequence[str], None] = 'fd6cd933e4c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UNKNOWN_TYPE = "unknown"
REASON = "Seeded document type retired: types are discovered per industry (2026-11-03)."


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('document_types', sa.Column('active', sa.Boolean(), server_default=sa.text('true'), nullable=False))

    # --- Retire seeded types no document uses ---
    op.execute(f"""
        UPDATE document_types t SET active = false
        WHERE t.origin = 'seeded' AND t.name <> '{UNKNOWN_TYPE}'
          AND NOT EXISTS (SELECT 1 FROM documents d WHERE d.document_type_id = t.id)
    """)

    # --- Their rules: a new inactive version (versions are append-only) ---
    # Also REQUIRED_DOCUMENTS-style rules whose parameters name a retired type.
    op.execute(f"""
        INSERT INTO compliance_rule_versions
            (id, rule_id, version, name, parameters, severity, active, change_reason, created_at, updated_at)
        SELECT gen_random_uuid(), v.rule_id, v.version + 1, v.name, v.parameters, v.severity, false,
               '{REASON}', now(), now()
        FROM compliance_rule_versions v
        JOIN compliance_rules r ON r.id = v.rule_id
        WHERE v.version = (SELECT max(version) FROM compliance_rule_versions WHERE rule_id = v.rule_id)
          AND v.active
          AND (
            r.document_type_id IN (SELECT id FROM document_types WHERE NOT active)
            OR EXISTS (
              SELECT 1 FROM jsonb_array_elements_text(coalesce(v.parameters -> 'document_types', '[]'::jsonb)) AS named(type_name)
              JOIN document_types t ON t.name = named.type_name
              WHERE NOT t.active
            )
          )
    """)

    # --- Their key attributes ---
    op.execute("""
        UPDATE key_attributes SET active = false, updated_at = now()
        WHERE document_type_id IN (SELECT id FROM document_types WHERE NOT active)
    """)


def downgrade() -> None:
    """Downgrade schema. Rule versions stay (append-only); reactivate them by API if needed."""
    op.execute("""
        UPDATE key_attributes SET active = true, updated_at = now()
        WHERE document_type_id IN (SELECT id FROM document_types WHERE NOT active)
    """)
    op.drop_column('document_types', 'active')
