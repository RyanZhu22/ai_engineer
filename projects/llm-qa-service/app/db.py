"""数据库连接与会话管理 - PostgreSQL 16 + pgvector。

企业级存储起点（对标技术笔记 docs/technical-notes.md 第 2 节）：
  - 对话表、消息表：关系型存储，按账号 owner_id 隔离
  - chunks 表：pgvector 向量检索（RAG）
"""
from sqlalchemy import Column, Float, ForeignKey, Integer, String, Text, Boolean, text, event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, relationship, Session, with_loader_criteria
from .security import current_user_id
from pgvector.sqlalchemy import Vector

from .config import get_settings


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id = Column(String(32), primary_key=True)
    username = Column(String(100), unique=True, nullable=False)
    password_hash = Column(Text, nullable=False)
    active = Column(Boolean, nullable=False, default=True)
    can_use_mcp = Column(Boolean, nullable=False, default=False)


class LoginSession(Base):
    __tablename__ = "login_sessions"
    token_hash = Column(String(64), primary_key=True)
    user_id = Column(String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    expires_at = Column(Float, nullable=False)


# ---------- 对话/消息 ----------
class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(String(32), primary_key=True)          # uuid hex 前 12 位
    owner_id = Column(String(32), ForeignKey("users.id"), index=True)
    title = Column(String(200), default="新对话")
    created_at = Column(Float, index=True)             # epoch 秒

    messages = relationship("Message", back_populates="conversation",
                            cascade="all, delete-orphan", order_by="Message.id")


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(String(32), ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    role = Column(String(16))                          # 'user' / 'assistant' / 'system'
    content = Column(Text)
    created_at = Column(Float, default=None)

    conversation = relationship("Conversation", back_populates="messages")


# ---------- RAG：文档与切片 ----------
class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_id = Column(String(32), ForeignKey("users.id"), index=True)
    title = Column(String(300))
    source = Column(String(300))                       # 原始文件名
    created_at = Column(Float)

    chunks = relationship("Chunk", back_populates="document",
                          cascade="all, delete-orphan", order_by="Chunk.chunk_index")


class Chunk(Base):
    """文档切片 + pgvector 向量。EMBEDDING_DIM 与 embedding 输出维度一致。"""
    __tablename__ = "chunks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    chunk_index = Column(Integer)
    content = Column(Text)
    embedding = Column(Vector(get_settings().embedding_dim))  # pgvector 列

    document = relationship("Document", back_populates="chunks")


# ---------- engine / session ----------
@event.listens_for(Session, "do_orm_execute")
def restrict_owned_rows(state):
    """Apply before SQL ranking/limits, including relationship and Agent queries.

    Offline evaluation has no request identity and is a trusted operator workflow.
    HTTP middleware rejects unauthenticated access before reaching any data route.
    """
    user_id = current_user_id.get()
    if user_id is None:
        return
    state.statement = state.statement.options(
        with_loader_criteria(Conversation, Conversation.owner_id == user_id, include_aliases=True),
        with_loader_criteria(Document, Document.owner_id == user_id, include_aliases=True),
        with_loader_criteria(Message, Message.conversation_id.in_(
            select(Conversation.id).where(Conversation.owner_id == user_id)), include_aliases=True),
        with_loader_criteria(Chunk, Chunk.document_id.in_(
            select(Document.id).where(Document.owner_id == user_id)), include_aliases=True),
    )


@event.listens_for(Session, "before_flush")
def assign_owner(session, flush_context, instances):
    user_id = current_user_id.get()
    if user_id is not None:
        for obj in session.new:
            if isinstance(obj, (Conversation, Document)):
                obj.owner_id = user_id


_engine = None
_session_factory = None


def _get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        url = settings.database_url
        # 兼容 Render/Heroku 风格 URL（postgresql:// → postgresql+psycopg://）
        if url.startswith("postgresql://") and "+psycopg" not in url:
            url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        _engine = create_async_engine(url, echo=False)
    return _engine


def get_session_factory() -> async_sessionmaker:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(_get_engine(), expire_on_commit=False)
    return _session_factory


async def get_db() -> AsyncSession:
    """FastAPI 依赖：每个请求一个 session，请求结束关闭。"""
    factory = get_session_factory()
    async with factory() as session:
        yield session


async def init_db() -> None:
    """建表（应用启动时调用）。正式项目用 Alembic 迁移。"""
    from sqlalchemy.ext.asyncio import async_engine_from_config  # noqa
    engine = _get_engine()
    async with engine.begin() as conn:
        # pgvector 扩展由 docker-compose 初始化时创建，这里再确保一次（幂等）
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
        # Additive compatibility migration: preserve legacy records as unowned.
        # Never silently give existing shared data to the first account.
        for table in ("conversations", "documents"):
            await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS owner_id VARCHAR(32) REFERENCES users(id)"))
            await conn.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{table}_owner_id ON {table}(owner_id)"))


async def close_db() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
    _session_factory = None
