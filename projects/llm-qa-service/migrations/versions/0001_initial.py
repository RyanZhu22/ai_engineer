"""Initial production schema, compatible with the pre-Alembic database."""
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id VARCHAR(32) PRIMARY KEY,
            username VARCHAR(100) NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            active BOOLEAN NOT NULL DEFAULT TRUE,
            can_use_mcp BOOLEAN NOT NULL DEFAULT FALSE
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS login_sessions (
            token_hash VARCHAR(64) PRIMARY KEY,
            user_id VARCHAR(32) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            expires_at DOUBLE PRECISION NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS conversations (
            id VARCHAR(32) PRIMARY KEY,
            owner_id VARCHAR(32) REFERENCES users(id),
            title VARCHAR(200) DEFAULT '新对话',
            created_at DOUBLE PRECISION
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id SERIAL PRIMARY KEY,
            conversation_id VARCHAR(32) REFERENCES conversations(id) ON DELETE CASCADE,
            role VARCHAR(16),
            content TEXT,
            created_at DOUBLE PRECISION
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS documents (
            id SERIAL PRIMARY KEY,
            owner_id VARCHAR(32) REFERENCES users(id),
            title VARCHAR(300),
            source VARCHAR(300),
            created_at DOUBLE PRECISION
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS chunks (
            id SERIAL PRIMARY KEY,
            document_id INTEGER REFERENCES documents(id) ON DELETE CASCADE,
            chunk_index INTEGER,
            content TEXT,
            embedding vector(512)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_logs (
            id SERIAL PRIMARY KEY,
            event VARCHAR(64) NOT NULL,
            user_id VARCHAR(32) REFERENCES users(id) ON DELETE SET NULL,
            success BOOLEAN NOT NULL DEFAULT TRUE,
            request_id VARCHAR(64),
            ip_address VARCHAR(64),
            details TEXT,
            created_at DOUBLE PRECISION NOT NULL
        )
        """
    )

    # Existing installations may have been created by create_all before the
    # owner columns or audit table existed. These statements are idempotent.
    op.execute(
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS owner_id VARCHAR(32) REFERENCES users(id)"
    )
    op.execute(
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS owner_id VARCHAR(32) REFERENCES users(id)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_conversations_owner_id ON conversations(owner_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_documents_owner_id ON documents(owner_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_login_sessions_user_id ON login_sessions(user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_messages_conversation_id ON messages(conversation_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_chunks_document_id ON chunks(document_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_audit_logs_user_id ON audit_logs(user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_audit_logs_created_at ON audit_logs(created_at)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_audit_logs_user_id_created_at "
        "ON audit_logs(user_id, created_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_chunks_embedding_hnsw "
        "ON chunks USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_chunks_embedding_hnsw")
    op.execute("DROP TABLE IF EXISTS audit_logs")
    op.execute("DROP TABLE IF EXISTS chunks")
    op.execute("DROP TABLE IF EXISTS documents")
    op.execute("DROP TABLE IF EXISTS messages")
    op.execute("DROP TABLE IF EXISTS conversations")
    op.execute("DROP TABLE IF EXISTS login_sessions")
    op.execute("DROP TABLE IF EXISTS users")

