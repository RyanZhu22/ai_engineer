# LLM QA Service · 企业知识库问答服务

> 项目驱动学习 · 交付物（LLM API + RAG + pgvector）
> 对标香港 AI 工程师 JD：Buyandship（LLM API+RAG+向量数据库）、SCMP（LLM APIs+FastAPI）
>
> 📝 技术决策与面试素材见 [`../../docs/technical-notes.md`](../../docs/technical-notes.md)

## 已实现

| 功能 | 状态 | 对应 JD 技能 |
|------|------|-------------|
| FastAPI REST 服务 | ✅ | FastAPI/Flask 封装 LLM |
| OpenAI 兼容多供应商（DeepSeek/OpenAI/Ollama） | ✅ | LLM API 调用 |
| Mock 模式（无 Key 可跑） | ✅ | 本地开发调试 |
| 参数校验 (pydantic) | ✅ | 生产级 API 设计 |
| **SSE 流式输出** | ✅ | ChatGPT 式打字机效果 |
| **会话历史（PostgreSQL 持久化）** | ✅ | 企业级数据层 |
| **RAG 全链路**（上传→切分→向量化→检索→生成） | ✅ | **SCMP/Buyandship 硬性要求** |
| **pgvector 向量检索** | ✅ | 向量数据库技能 |
| **本地 embedding**（bge-small-zh，无需 API key） | ✅ | 中文检索质量高 |
| **多文档知识库管理**（上传/列表/删除/检索） | ✅ | RAG 生产化 |
| **回答带来源标注**（cite） | ✅ | 可追溯，防幻觉 |
| ChatGPT 风格前端（暂停/重发/复制/知识库开关） | ✅ | 全栈加分 |
| 测试 (pytest) | ✅ | 7 个测试通过 |

## 快速开始

```bash
# 1. 启动数据库（PostgreSQL 16 + pgvector）
docker compose up -d

# 2. 安装依赖
uv venv
uv pip install -e ".[dev]"

# 3. 配置（LLM Key 任选一个 OpenAI 兼容供应商；Embedding 默认本地模型无需配置）
cp .env.example .env
# 编辑 .env 填入 LLM_API_KEY（DeepSeek: LLM_BASE_URL=https://api.deepseek.com/v1）

# 4. 启动服务（首次 embedding 会自动下载 bge-small-zh 模型，~90MB）
source .venv/bin/activate
uvicorn app.main:app --port 8000 --reload

# 5. 打开 http://localhost:8000 使用；API 文档 /docs
```

## RAG 使用

1. 打开前端，侧边栏 **📚 知识库 → ＋** 上传文档（txt/md/pdf，≤10MB）
2. 勾选 **"回答时检索知识库"**
3. 提问，回答会标注来源 `[资料1] [资料2]`，前端显示来源标签

> 快速体验：`sample_data/employee-handbook.md` 是一份现成的中文员工手册示例，
> 前端上传它即可测试（年假/产假/病假/加班/报销/远程办公/培训/离职 8 个主题）。

```bash
# 纯 API 方式
# 上传文档
curl -X POST http://localhost:8000/documents/upload -F "file=@员工手册.md"

# 检索调试（看 query 召回哪些切片）
curl -X POST http://localhost:8000/documents/search \
  -H "Content-Type: application/json" \
  -d '{"query":"年假有几天","top_k":3}'

# RAG 问答
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"远程办公每周可以申请几天？","use_rag":true}'
```

## Embedding 三模式（EMBEDDING_PROVIDER）

| 模式 | 说明 | 何时用 |
|------|------|--------|
| `auto`（默认） | 有 API key → api；否则本地模型；再否则 mock | 开箱即用 |
| `local` | fastembed + BAAI/bge-small-zh-v1.5（512 维） | 中文知识库，零成本 |
| `api` | OpenAI 兼容 /embeddings（OpenAI/SiliconFlow/智谱） | 需要更强模型或已有 key |
| `mock` | 确定性哈希向量（词重叠） | 离线测试兜底 |

> ⚠️ `EMBEDDING_DIM` 必须与数据库 `chunks.embedding` 列维度一致（建表时固定）。切换 embedding 模型后需重建表：`docker exec llm-qa-pg psql -U llmqa -d llmqa -c "DROP TABLE chunks, documents;"` 再重启服务。

## 架构

```
浏览器 (index.html)
   │  /chat/stream (SSE)        /documents/upload
   ▼                                 ▼
FastAPI (main.py) ──► history.py ──► PostgreSQL 16
   │                    conversations/messages 表
   ├──► rag.py ──► documents/chunks 表（pgvector 向量检索）
   │       │
   │       ▼
   │   embedding_client（local bge / api / mock）
   ▼
LLMClient ──► DeepSeek / OpenAI / Ollama（OpenAI 兼容协议）
```

## 数据库表

```sql
conversations(id, title, created_at)
messages(id, conversation_id FK, role, content, created_at)
documents(id, title, source, created_at)
chunks(id, document_id FK, chunk_index, content, embedding vector(512))  -- pgvector
```

## API 文档

启动后访问 **http://localhost:8000/docs**（Swagger UI，自动生成）

端点一览：

| 端点 | 说明 |
|------|------|
| `GET /health` | 健康检查（含文档数） |
| `POST /chat` | 完整回复（支持 `use_rag`） |
| `POST /chat/stream` | SSE 流式（支持 `use_rag`，事件含 sources） |
| `GET/POST /history` | 会话历史 |
| `POST /documents/upload` | 上传文档并索引 |
| `GET/DELETE /documents` | 文档列表/删除 |
| `POST /documents/search` | RAG 检索调试 |

## 目录结构

```
llm-qa-service/
├── docker-compose.yml       # PostgreSQL 16 + pgvector
├── pyproject.toml           # 依赖管理
├── .env.example             # 配置模板（secret 不入库）
├── app/
│   ├── main.py              # FastAPI 入口 + 路由
│   ├── config.py            # 环境变量配置
│   ├── db.py                # SQLAlchemy 模型 + async engine
│   ├── history.py           # 会话存储（PostgreSQL）
│   ├── llm_client.py        # LLM 客户端（多供应商抽象）
│   ├── embedding_client.py  # Embedding 客户端（local/api/mock）
│   ├── rag.py               # RAG：解析/切分/检索/提示词
│   └── static/index.html    # ChatGPT 风格前端
└── tests/
    └── test_api.py          # 7 个测试（含 RAG）
```

## 面试知识点（下次面试可讲）

1. **为什么用环境变量存 API Key？** → secret 不进代码库，可轮换，多环境隔离
2. **为什么用 OpenAI 兼容协议？** → 一套代码接所有主流供应商，vendor lock-in 最小
3. **liveness vs readiness？** → liveness 决定要不要重启，readiness 决定要不要接流量
4. **RAG 为什么用 pgvector？** → 向量检索与关系数据同库（对话+向量），无额外运维成本；PostgreSQL 生态成熟
5. **切分为什么要 overlap？** → 跨 chunk 边界时语义断裂，overlap 减少信息丢失
6. **embedding 为什么本地化？** → 中文知识库用 bge-small-zh 质量好且零 API 成本；数据不出内网（合规敏感场景）
7. **为什么 LLM 输出要过 DOMPurify？** → LLM 输出不可信（prompt injection），防 XSS
8. **async SQLAlchemy 的坑？** → relationship 访问必须 selectinload 预加载，否则 async 下 lazy load 抛 MissingGreenlet
