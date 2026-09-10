"""Operator-only provisioning: python -m app.manage_users USERNAME [--allow-mcp]."""
import argparse
import asyncio
import getpass
import uuid
from sqlalchemy import select
from .auth import hash_password
from .db import User, init_db, close_db, get_session_factory


async def create(username, password, allow_mcp):
    await init_db()
    try:
        async with get_session_factory()() as session:
            if (await session.execute(select(User.id).where(User.username == username))).first():
                raise ValueError("账号已存在")
            session.add(User(id=uuid.uuid4().hex, username=username, password_hash=hash_password(password), can_use_mcp=allow_mcp))
            await session.commit()
    finally:
        await close_db()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("username")
    parser.add_argument("--allow-mcp", action="store_true")
    args = parser.parse_args()
    if not 1 <= len(args.username) <= 100:
        parser.error("用户名长度必须为 1–100")
    password = getpass.getpass("密码（至少 12 字符）: ")
    if not 12 <= len(password) <= 256 or password != getpass.getpass("确认密码: "):
        parser.error("密码长度不符或两次输入不一致")
    asyncio.run(create(args.username, password, args.allow_mcp))
    print("账号已创建")
