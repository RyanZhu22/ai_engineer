"""HNSW 索引配置与向量候选范围测试。"""
import asyncio

import pytest

from app.config import get_settings
from app.db import _vector_index_ddl, get_session_factory
from app.embedding_client import get_embedding_client
from app.rag import apply_hnsw_search_settings, vector_candidates
from test_api import client


def test_vector_index_ddl_uses_configured_hnsw_parameters(monkeypatch):
    monkeypatch.setenv("RAG_HNSW_M", "24")
    monkeypatch.setenv("RAG_HNSW_EF_CONSTRUCTION", "96")
    get_settings.cache_clear()
    try:
        ddl = _vector_index_ddl()
        assert "USING hnsw (embedding vector_cosine_ops)" in ddl
        assert "m = 24" in ddl
        assert "ef_construction = 96" in ddl
    finally:
        get_settings.cache_clear()


def test_hnsw_search_settings_validate_ef_search_before_sql():
    class Session:
        def in_transaction(self):
            return True

        async def execute(self, statement):
            raise AssertionError(f"不应执行 SQL：{statement}")

    with pytest.raises(ValueError, match="1 到 1000"):
        asyncio.run(apply_hnsw_search_settings(Session(), 0))
    with pytest.raises(ValueError, match="1 到 1000"):
        asyncio.run(apply_hnsw_search_settings(Session(), 1001))


def test_vector_candidates_respect_document_ids(client):
    first = client.post(
        "/documents/upload",
        files={"file": ("first.md", "只属于第一份文档的火星报销规则。", "text/markdown")},
    ).json()
    second = client.post(
        "/documents/upload",
        files={"file": ("second.md", "只属于第二份文档的木星报销规则。", "text/markdown")},
    ).json()

    async def find_first_document_candidates():
        query_vector = await get_embedding_client().embed_one("报销规则")
        async with get_session_factory()() as session:
            return await vector_candidates(
                session,
                query_vector,
                limit=10,
                document_ids=[first["id"]],
            )

    try:
        hits = client.portal.call(find_first_document_candidates)
        assert hits
        assert {hit["document_id"] for hit in hits} == {first["id"]}
    finally:
        client.delete(f"/documents/{first['id']}")
        client.delete(f"/documents/{second['id']}")
