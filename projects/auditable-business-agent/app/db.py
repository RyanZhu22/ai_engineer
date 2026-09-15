from __future__ import annotations

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import database_url


def build_engine(url: str | None = None) -> Engine:
    return create_engine(url or database_url(), pool_pre_ping=True)


def build_session_factory(url: str | None = None) -> sessionmaker[Session]:
    return sessionmaker(bind=build_engine(url), expire_on_commit=False)
