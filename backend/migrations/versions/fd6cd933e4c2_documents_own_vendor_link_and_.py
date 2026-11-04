"""documents own vendor link and superseding

One bundle can hold documents of several vendors and components (decision
2026-11-03), so the vendor/component link, its evidence and superseding move
from vendor_files to documents.

Revision ID: fd6cd933e4c2
Revises: e3a1c7b52f04
Create Date: 2026-11-03 19:01:40.211137

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'fd6cd933e4c2'
down_revision: Union[str, Sequence[str], None] = 'e3a1c7b52f04'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('documents', sa.Column('vendor_id', sa.Uuid(), nullable=True))
    op.add_column('documents', sa.Column('component_id', sa.Uuid(), nullable=True))
    op.add_column('documents', sa.Column('identification_evidence', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False))
    op.add_column('documents', sa.Column('superseded_by_id', sa.Uuid(), nullable=True))
    op.add_column('documents', sa.Column('superseded_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f('ix_documents_vendor_id'), 'documents', ['vendor_id'], unique=False)
    op.create_index(op.f('ix_documents_component_id'), 'documents', ['component_id'], unique=False)
    op.create_foreign_key(op.f('fk_documents_vendor_id_vendors'), 'documents', 'vendors', ['vendor_id'], ['id'], ondelete='RESTRICT')
    op.create_index(op.f('ix_documents_superseded_by_id'), 'documents', ['superseded_by_id'], unique=False)
    op.create_foreign_key(op.f('fk_documents_superseded_by_id_documents'), 'documents', 'documents', ['superseded_by_id'], ['id'], ondelete='RESTRICT')
    op.create_foreign_key(op.f('fk_documents_component_id_components'), 'documents', 'components', ['component_id'], ['id'], ondelete='RESTRICT')
    # Autogenerate doesn't see CHECKs (see the enum_check note in models/base.py).
    op.create_check_constraint(op.f('ck_documents_superseded_fields_together'), 'documents', '(superseded_by_id IS NULL) = (superseded_at IS NULL)')
    op.create_check_constraint(op.f('ck_documents_not_superseded_by_itself'), 'documents', 'superseded_by_id <> id')

    # --- Backfill: every document inherits its file's link ---
    op.execute("""
        UPDATE documents d
        SET component_id = f.component_id, identification_evidence = f.identification_evidence
        FROM vendor_files f
        WHERE d.vendor_file_id = f.id
    """)
    op.execute("""
        UPDATE documents d SET vendor_id = c.vendor_id
        FROM components c WHERE d.component_id = c.id
    """)
    # After the backfill: the rows only satisfy it once vendor_id is filled in.
    op.create_check_constraint(op.f('ck_documents_component_has_vendor'), 'documents', 'component_id IS NULL OR vendor_id IS NOT NULL')
    # A superseded file's documents: replaced by the newer file's document of the
    # same type (and same number when both have one). Documents with no such
    # match stay current: per document, nothing replaced them.
    op.execute("""
        UPDATE documents old
        SET superseded_by_id = new.id, superseded_at = f.superseded_at
        FROM vendor_files f, documents new
        WHERE old.vendor_file_id = f.id
          AND f.superseded_by_id IS NOT NULL
          AND new.vendor_file_id = f.superseded_by_id
          AND new.document_type_id = old.document_type_id
          AND (old.document_number IS NULL OR new.document_number IS NULL
               OR old.document_number = new.document_number)
    """)

    op.drop_index(op.f('ix_vendor_files_component_id'), table_name='vendor_files')
    op.drop_constraint(op.f('ck_vendor_files_superseded_fields_together'), 'vendor_files', type_='check')
    op.drop_constraint(op.f('ck_vendor_files_not_superseded_by_itself'), 'vendor_files', type_='check')
    op.drop_constraint(op.f('fk_vendor_files_superseded_by_id_vendor_files'), 'vendor_files', type_='foreignkey')
    op.drop_constraint(op.f('fk_vendor_files_component_id_components'), 'vendor_files', type_='foreignkey')
    op.drop_column('vendor_files', 'superseded_by_id')
    op.drop_column('vendor_files', 'identification_evidence')
    op.drop_column('vendor_files', 'component_id')
    op.drop_column('vendor_files', 'superseded_at')


def downgrade() -> None:
    """Downgrade schema. Lossy: a file gets one component (its first document's)."""
    op.add_column('vendor_files', sa.Column('superseded_at', postgresql.TIMESTAMP(timezone=True), autoincrement=False, nullable=True))
    op.add_column('vendor_files', sa.Column('component_id', sa.UUID(), autoincrement=False, nullable=True))
    op.add_column('vendor_files', sa.Column('identification_evidence', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), autoincrement=False, nullable=False))
    op.add_column('vendor_files', sa.Column('superseded_by_id', sa.UUID(), autoincrement=False, nullable=True))
    op.create_foreign_key(op.f('fk_vendor_files_component_id_components'), 'vendor_files', 'components', ['component_id'], ['id'], ondelete='RESTRICT')
    op.create_foreign_key(op.f('fk_vendor_files_superseded_by_id_vendor_files'), 'vendor_files', 'vendor_files', ['superseded_by_id'], ['id'], ondelete='RESTRICT')
    op.create_index(op.f('ix_vendor_files_component_id'), 'vendor_files', ['component_id'], unique=False)
    op.execute("""
        UPDATE vendor_files f
        SET component_id = d.component_id, identification_evidence = d.identification_evidence
        FROM (SELECT DISTINCT ON (vendor_file_id) vendor_file_id, component_id, identification_evidence
              FROM documents ORDER BY vendor_file_id, start_page) d
        WHERE d.vendor_file_id = f.id
    """)
    op.create_check_constraint(op.f('ck_vendor_files_superseded_fields_together'), 'vendor_files', '(superseded_by_id IS NULL) = (superseded_at IS NULL)')
    op.create_check_constraint(op.f('ck_vendor_files_not_superseded_by_itself'), 'vendor_files', 'superseded_by_id <> id')

    op.drop_constraint(op.f('ck_documents_component_has_vendor'), 'documents', type_='check')
    op.drop_constraint(op.f('ck_documents_not_superseded_by_itself'), 'documents', type_='check')
    op.drop_constraint(op.f('fk_documents_vendor_id_vendors'), 'documents', type_='foreignkey')
    op.drop_index(op.f('ix_documents_vendor_id'), table_name='documents')
    op.drop_constraint(op.f('ck_documents_superseded_fields_together'), 'documents', type_='check')
    op.drop_constraint(op.f('fk_documents_component_id_components'), 'documents', type_='foreignkey')
    op.drop_constraint(op.f('fk_documents_superseded_by_id_documents'), 'documents', type_='foreignkey')
    op.drop_index(op.f('ix_documents_superseded_by_id'), table_name='documents')
    op.drop_index(op.f('ix_documents_component_id'), table_name='documents')
    op.drop_column('documents', 'superseded_at')
    op.drop_column('documents', 'superseded_by_id')
    op.drop_column('documents', 'identification_evidence')
    op.drop_column('documents', 'component_id')
    op.drop_column('documents', 'vendor_id')
