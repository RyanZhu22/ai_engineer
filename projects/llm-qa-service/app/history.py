"""会话历史存储 - PostgreSQL（SQLAlchemy async）。

对标技术笔记 docs/technical-notes.md 第 2 节：
  - 从 JSON 文件升级到企业级关系型存储（多实例共享、事务、可扩展 user_id）
  - 异步 session，避免阻塞事件循环

接口与旧 JSON 版保持一致，main.py 无需改动业务逻辑。
"""
import time
import uuid

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from .db import Conversation, Message, get_session_factory


def _conv_to_dict(conv: Conversation) -> dict:
    """ORM → dict，兼容旧接口返回结构。"""
    return {
        "id": conv.id,
        "title": conv.title,
        "created_at": conv.created_at,
        "messages": [{"role": m.role, "content": m.content} for m in conv.messages],
    }


async def list_conversations() -> list[dict]:
    """会话列表（不含完整消息，只含标题等摘要）。"""
    async with get_session_factory()() as session:
        rows = (
            await session.execute(
                select(Conversation)
                .options(selectinload(Conversation.messages))
                .order_by(Conversation.created_at.desc())
            )
        ).scalars().all()
    return [
        {
            "id": c.id,
            "title": c.title,
            "created_at": c.created_at,
            "message_count": len(c.messages),
        }
        for c in rows
    ]


async def create_conversation(title: str = "新对话") -> dict:
    conv = Conversation(id=uuid.uuid4().hex[:12], title=title, created_at=time.time())
    async with get_session_factory()() as session:
        session.add(conv)
        await session.commit()
    # 新会话必然没有消息，直接构造 dict（避免触发 async 不支持的 lazy load）
    return {"id": conv.id, "title": conv.title, "created_at": conv.created_at, "messages": []}


async def get_conversation(conv_id: str) -> dict | None:
    async with get_session_factory()() as session:
        conv = (
            await session.execute(
                select(Conversation)
                .options(selectinload(Conversation.messages))
                .where(Conversation.id == conv_id)
            )
        ).scalar_one_or_none()
        if conv is None:
            return None
        return _conv_to_dict(conv)


async def add_message(conv_id: str, role: str, content: str) -> None:
    async with get_session_factory()() as session:
        conv = (
            await session.execute(
                select(Conversation)
                .where(Conversation.id == conv_id)
            )
        ).scalar_one_or_none()
        if conv is None:
            raise ValueError(f"会话不存在: {conv_id}")
        session.add(Message(conversation_id=conv_id, role=role, content=content, created_at=time.time()))
        # 用第一条用户消息作为标题
        if role == "user" and conv.title == "新对话":
            conv.title = content[:30] + ("…" if len(content) > 30 else "")
        await session.commit()


async def delete_conversation(conv_id: str) -> bool:
    async with get_session_factory()() as session:
        conv = (
            await session.execute(
                select(Conversation)
                .where(Conversation.id == conv_id)
            )
        ).scalar_one_or_none()
        if conv is None:
            return False
        await session.delete(conv)  # cascade 删除 messages
        await session.commit()
        return True


async def truncate_conversation(conv_id: str, keep_messages: int) -> bool:
    """保留会话前 N 条消息（重发/重新生成时避免历史重复）。"""
    async with get_session_factory()() as session:
        msgs = (
            await session.execute(
                select(Message)
                .where(Message.conversation_id == conv_id)
                .order_by(Message.id)
            )
        ).scalars().all()
        if not msgs:
            return False
        for m in msgs[keep_messages:]:
            await session.delete(m)
        await session.commit()
        return True
