"""基础测试 - 有 Key 验证真实调用，无 Key 验证 mock 模式。

RAG 测试强制 mock embedding（EMBEDDING_PROVIDER=mock）：
  - 不下载本地模型，测试快、可离线
  - 需要 PostgreSQL 在运行（docker compose up -d）
"""
import os

os.environ.setdefault("EMBEDDING_PROVIDER", "mock")

import pytest
from fastapi.testclient import TestClient

import app.embedding_client as embedding_client_mod
import app.llm_client as llm_client_mod
from app.main import app


@pytest.fixture
def client():
    # 重置单例，避免测试之间共享已关闭的 client / embedding 模型
    llm_client_mod._client = None
    embedding_client_mod._client = None
    with TestClient(app) as c:
        yield c


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "UP"
    assert data["service"] == "llm-qa-service"


def test_chat_live_or_mock(client):
    """有 Key 时验证真实调用，无 Key 时验证 mock 模式。"""
    resp = client.post("/chat", json={"message": "香港AI工程师需要什么技能？"})
    assert resp.status_code == 200
    data = resp.json()
    assert "model" in data
    assert data["reply"].strip()  # 非空回复


def test_chat_invalid_empty(client):
    resp = client.post("/chat", json={"message": ""})
    assert resp.status_code == 422  # pydantic 校验失败


# ---------- RAG 测试 ----------

def test_upload_document(client):
    resp = client.post(
        "/documents/upload",
        files={"file": ("年假政策.md", "# 年假政策\n员工每年享有12天年假。", "text/markdown")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] > 0
    assert data["chunks"] >= 1
    assert data["embedding_mode"] == "mock"
    # 清理
    client.delete(f"/documents/{data['id']}")


def test_search_retrieves_relevant_chunk(client):
    doc = client.post(
        "/documents/upload",
        files={"file": ("员工手册.md", "## 年假\n员工每年享有12天年假。\n## 培训\n每年5000元培训预算。", "text/markdown")},
    ).json()
    resp = client.post("/documents/search", json={"query": "年假有几天", "top_k": 3})
    assert resp.status_code == 200
    hits = resp.json()["hits"]
    assert hits, "mock 模式应能基于词重叠检索到内容"
    assert any("年假" in h["content"] for h in hits)
    client.delete(f"/documents/{doc['id']}")


def test_chat_with_rag_returns_sources(client):
    doc = client.post(
        "/documents/upload",
        files={"file": ("预算政策.md", "每位员工每年享有5000元培训预算。", "text/markdown")},
    ).json()
    resp = client.post("/chat", json={"message": "培训预算是多少？", "use_rag": True})
    assert resp.status_code == 200
    data = resp.json()
    assert data["reply"].strip()
    assert data["sources"], "RAG 模式应返回检索来源"
    client.delete(f"/documents/{doc['id']}")


def test_delete_document(client):
    doc = client.post(
        "/documents/upload",
        files={"file": ("临时.md", "临时内容", "text/markdown")},
    ).json()
    resp = client.delete(f"/documents/{doc['id']}")
    assert resp.status_code == 200
    resp = client.delete(f"/documents/{doc['id']}")
    assert resp.status_code == 404
