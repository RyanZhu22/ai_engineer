from __future__ import annotations

import os


DEFAULT_DATABASE_URL = "postgresql+psycopg://agent:agent_dev_only@localhost:5433/auditable_agent"
DEFAULT_AUTH_SECRET = "replace-this-development-secret-before-deployment"


def database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


def langgraph_database_url() -> str:
    return database_url().replace("postgresql+psycopg://", "postgresql://", 1)


def auth_secret() -> str:
    return os.environ.get("AUTH_SECRET", DEFAULT_AUTH_SECRET)
