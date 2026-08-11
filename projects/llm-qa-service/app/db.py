"""数据库连接与会话管理 - PostgreSQL 16 + pgvector。

企业级存储起点（对标技术笔记 docs/technical-notes.md 第 2 节）：
  - 对话表、消息表：关系型存储，按 user_id 可扩展
  - chunks 表：pgvector 向量检索（RAG）
"""
from sqlalchemy import Column, Float, ForeignKey, Integer, String, Text, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, relationship
from pgvector.sqlalchemy import Vector

from .config import get_settings


class Base(DeclarativeBase):
    pass


# ---------- 对话/消息 ----------
class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(String(32), primary_key=True)          # uuid hex 前 12 位
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
_engine = None
_session_factory = None


def _get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(settings.database_url, echo=False)
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


async def close_db() -> None:
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
