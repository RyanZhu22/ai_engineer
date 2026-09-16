"""Enable pgvector for LangChain policy retrieval.

Revision ID: 0003_enable_vector
Revises: 0002_users
Create Date: 2026-09-16
"""

from alembic import op


revision = "0003_enable_vector"
down_revision = "0002_users"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    # LangChain's vector tables depend on this extension; keep it during a
    # downgrade so an existing collection is not made unreadable.
    pass
