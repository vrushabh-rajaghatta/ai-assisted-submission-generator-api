"""add product_id to uploaded_files for product-level file association

Revision ID: b7c8d9e0f1a2
Revises: a1f2c3d4e5b6
Create Date: 2026-06-25 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b7c8d9e0f1a2'
down_revision = 'a1f2c3d4e5b6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'uploaded_files',
        sa.Column('product_id', sa.UUID(), nullable=True),
    )
    op.create_index(
        op.f('ix_uploaded_files_product_id'),
        'uploaded_files',
        ['product_id'],
        unique=False,
    )
    op.create_foreign_key(
        'fk_uploaded_files_product_id_products',
        'uploaded_files',
        'products',
        ['product_id'],
        ['id'],
    )

    # Backfill product_id from submission when file is linked to a submission.
    conn = op.get_bind()
    conn.execute(sa.text(
        """
        UPDATE uploaded_files uf
        SET product_id = s.product_id
        FROM submissions s
        WHERE uf.submission_id = s.id
          AND uf.product_id IS NULL;
        """
    ))


def downgrade() -> None:
    op.drop_constraint(
        'fk_uploaded_files_product_id_products',
        'uploaded_files',
        type_='foreignkey',
    )
    op.drop_index(op.f('ix_uploaded_files_product_id'), table_name='uploaded_files')
    op.drop_column('uploaded_files', 'product_id')
