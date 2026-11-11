"""industry profile

One row per installation: the industry the system serves and the words it uses
(decision 2026-11-03). An installation that already holds documents was built
for pharmaceutical bundles, so it gets the pharmaceutical preset; a fresh one
gets no row, which means the generic preset until an admin chooses.

Revision ID: c3d5e7f90a12
Revises: a4f2c9d81e60
Create Date: 2026-11-03 22:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c3d5e7f90a12'
down_revision: str | Sequence[str] | None = 'a4f2c9d81e60'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# A copy of src/industry/profile.py's preset as of today: migrations must not
# import application code, which keeps changing after they are written.
PHARMACEUTICAL = {
    "preset": "pharmaceutical",
    "industry": "Pharmaceutical",
    "description": "a pharmaceutical manufacturer's quality assurance team, keeping the vendor documentation "
    "for the components and materials it buys (GMP, 21 CFR Part 11).",
    "vendor_label": "Vendor", "vendor_label_plural": "Vendors",
    "component_label": "Component", "component_label_plural": "Components",
}

# Core key attributes' descriptions are GPT's instructions; their examples came
# from the pharma test bundle. Replaced only if QA hasn't edited them since.
# (name, old description, new description)
NEUTRAL_DESCRIPTIONS = [
    ("title",
     "The document's own title as printed in its heading or title block, e.g. 'Compliance Bulletin' "
     "or 'Overview of FluroTec and B2-Coating'. The title words only: no page numbers, stray symbols, "
     "company name, logo text or address.",
     "The document's own title as printed in its heading or title block, e.g. 'Certificate of "
     "Conformity' or 'Material Safety Data Sheet'. The title words only: no page numbers, stray "
     "symbols, company name, logo text or address."),
    ("item_numbers",
     "The products, items, components or formulations this document is about, e.g. '4432/50 Grey' "
     "for 'West Item: 4432/50 Grey'. The identifiers alone, without labels such as 'Item:'. Only "
     "items the document covers, not ones it merely mentions.",
     "The products, items, parts, materials or shipments this document is about, e.g. 'NS-880-24' "
     "for 'Article no.: NS-880-24'. The identifiers alone, without labels such as 'Item:'. Only "
     "items the document covers, not ones it merely mentions."),
]

# A fresh installation (no documents yet) assumes no industry, so it doesn't
# require what only some industries print on every document: a revision (a bill
# of lading has none) or an approval signature (a safety data sheet rarely has
# one). QA marks them required again if their industry needs them. And its
# default age rule trusts a document's own "valid until" date.
NOT_REQUIRED_ON_FRESH_INSTALL = ("revision", "approval_status")
FRESH_INSTALL_REASON = "Industry-neutral defaults for a new installation (2026-11-03)."


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('industry_profiles',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('singleton', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('preset', sa.String(), nullable=True),
    sa.Column('industry', sa.String(), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('vendor_label', sa.String(), nullable=False),
    sa.Column('vendor_label_plural', sa.String(), nullable=False),
    sa.Column('component_label', sa.String(), nullable=False),
    sa.Column('component_label_plural', sa.String(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('singleton', name=op.f('ck_industry_profiles_one_profile')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_industry_profiles')),
    sa.UniqueConstraint('singleton', name=op.f('uq_industry_profiles_singleton'))
    )
    columns = ", ".join(PHARMACEUTICAL)
    values = ", ".join(f":{name}" for name in PHARMACEUTICAL)
    op.get_bind().execute(
        sa.text(
            f"INSERT INTO industry_profiles (id, {columns}) "
            f"SELECT gen_random_uuid(), {values} WHERE EXISTS (SELECT 1 FROM documents)"
        ),
        PHARMACEUTICAL,
    )
    for name, old, new in NEUTRAL_DESCRIPTIONS:
        op.get_bind().execute(
            sa.text("UPDATE key_attributes SET description = :new, updated_at = now() WHERE name = :name AND description = :old"),
            {"name": name, "old": old, "new": new},
        )

    # --- Fresh installation only ---
    fresh = not op.get_bind().execute(sa.text("SELECT EXISTS (SELECT 1 FROM documents)")).scalar()
    if fresh:
        op.get_bind().execute(
            sa.text("UPDATE key_attributes SET required = false, updated_at = now() WHERE name = ANY(:names)"),
            {"names": list(NOT_REQUIRED_ON_FRESH_INSTALL)},
        )
        # Rule versions are append-only: a new version, not an edit.
        op.get_bind().execute(
            sa.text("""
                INSERT INTO compliance_rule_versions
                    (id, rule_id, version, name, parameters, severity, active, change_reason, created_at, updated_at)
                SELECT gen_random_uuid(), v.rule_id, v.version + 1, v.name,
                       v.parameters || '{"use_stated_expiry": true}'::jsonb, v.severity, v.active, :reason, now(), now()
                FROM compliance_rule_versions v JOIN compliance_rules r ON r.id = v.rule_id
                WHERE r.code = 'DEFAULT_DOCUMENT_AGE'
                  AND v.version = (SELECT max(version) FROM compliance_rule_versions WHERE rule_id = v.rule_id)
            """),
            {"reason": FRESH_INSTALL_REASON},
        )


def downgrade() -> None:
    """Downgrade schema."""
    for name, old, new in NEUTRAL_DESCRIPTIONS:
        op.get_bind().execute(
            sa.text("UPDATE key_attributes SET description = :old, updated_at = now() WHERE name = :name AND description = :new"),
            {"name": name, "old": old, "new": new},
        )
    op.drop_table('industry_profiles')
