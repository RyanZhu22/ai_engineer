"""Allow LangChain collections with different embedding dimensions.

Revision ID: 0004_vector_unconstrained
Revises: 0003_enable_vector
Create Date: 2026-09-17
"""

from alembic import op


revision = "0004_vector_unconstrained"
down_revision = "0003_enable_vector"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.langchain_pg_embedding') IS NOT NULL THEN
                ALTER TABLE public.langchain_pg_embedding
                ALTER COLUMN embedding TYPE vector USING embedding::vector;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    # A 512-dimensional BGE collection cannot safely be narrowed back to the
    # previous 256-dimensional local vector column.
    pass
