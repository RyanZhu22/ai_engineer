# 🧠 技术笔记 · llm-qa-service

> 记录开发过程中的技术决策、踩过的坑、概念讲解与面试素材。
> 用途：以后写代码时引用这里的模式，补充到代码注释或 README。

---

## 目录

1. [单例 + 连接池复用](#1-单例--连接池复用)
2. [会话存储：从文件到企业级数据库](#2-会话存储从文件到企业级数据库)
3. [AI Studio 历史记录重置排查](#3-ai-studio-历史记录重置排查)
4. [RAG 链路 + pgvector](#4-rag-链路--pgvector)
5. [async SQLAlchemy 踩坑记录](#5-async-sqlalchemy-踩坑记录)
6. [代码位置索引与待办](#6-代码位置索引与待办)
7. [Agent 循环 + tool calling](#7-agent-循环--tool-calling)

---

## 1. 单例 + 连接池复用

### 概念

- **单例（Singleton）**：应用生命周期内只创建一个实例，所有请求共用。
- **连接池（Connection Pool）**：预先建立一批 TCP 连接反复使用，用完归还而不是销毁。

组合原因：HTTP 连接需要 TCP 握手 + TLS 协商（每请求 ~50-100ms 开销），反复建立销毁是浪费；
单例保证连接池只建一次、全局共享。

### 代码模式（llm_client.py）

```python
_client: Optional[LLMClient] = None   # 模块级变量，只初始化一次

def get_llm_client() -> LLMClient:
    global _client
    if _client is None:               # 第一次调用才创建
        s = get_settings()
        _client = LLMClient(base_url=s.llm_base_url, api_key=s.llm_api_key, model=s.llm_model)
    return _client                    # 之后永远返回同一个
```

```python
self._client = httpx.AsyncClient(timeout=60.0)  # 内部维护连接池
```

### 配套细节（两处必须配套）

1. **优雅关闭**（main.py 的 lifespan）——单例连接池活得和应用一样久，关闭时必须释放：

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    client = get_llm_client()
    await client.aclose()   # 关闭池子里所有连接
```

> 类比 Spring：`@PreDestroy` / `ApplicationContext.close()` 释放连接池。

2. **测试重置单例**（tests/test_api.py）——lifespan 关闭了 client，下一个测试必须拿到新的：

```python
@pytest.fixture
def client():
    llm_client_mod._client = None   # 重置单例，避免测试间共享已关闭的 client
    with TestClient(app) as c:
        yield c
```

### 反例（为什么不能每次请求新建）

```python
client = LLMClient()  # ❌ 每个请求都新建：握手开销 + 连接池形同虚设 + 可能泄漏
```

### ✅ 连接池上限 + 指数退避重试（已实现 08-13）

```python
self._client = httpx.AsyncClient(
    timeout=60.0,
    limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
)
```

重试策略（`_post_with_retry`，面试考点）：

| 场景 | 处理 |
|------|------|
| 429（限流） | 重试，尊重 `Retry-After` 头（封顶 60s） |
| 5xx（500/502/503/504） | 重试 |
| 网络错误（连接重置/超时） | 重试 |
| 4xx（400/401/403/422） | **不重试**，立即失败（重试无意义） |

- 退避：指数 `base * 2^attempt`（1s → 2s → 4s）+ 随机抖动（jitter），防止重试风暴同时打爆上游
- **流式边界**：只在"拿到响应头之前"重试；一旦开始流式输出 token，中途断流不重试（重发会重复输出）
- 所有参数（连接数/重试次数/退避间隔）环境变量可调，测试注入 `httpx.MockTransport` 模拟故障（10 个新测试）

### 面试讲法（30 秒版）

> "LLM 客户端我用了单例模式 + httpx 连接池复用。HTTP 连接需要 TCP 握手和 TLS 协商，每次请求新建成本很高。单例保证整个应用只建一个 AsyncClient，连接池里的连接反复复用，延迟和资源占用大幅降低。应用关闭时在 lifespan 里显式 aclose 释放连接，避免悬挂连接。
> 另外我加了指数退避重试：429 限流尊重 Retry-After，5xx 和网络错误自动重试，4xx 客户端错误直接失败不浪费重试。重试加随机抖动避免重试风暴。流式场景只在拿到响应头前重试，防止用户看到重复内容。"

---

## 2. 会话存储：从文件到企业级数据库

### 存储方案演进

| 档次 | 方案 | 场景 | 关闭浏览器后 |
|------|------|------|------------|
| 0 | 内存 dict | 演示，重启即丢 | ❌ 丢 |
| 1 | JSON 文件（本项目当前） | 单机 demo，重启保留 | ✅ 在（本地） |
| 2 | SQLite | 单机小生产 | ✅ 在 |
| 3 | PostgreSQL + Redis | **企业级起点** | ✅ 在 |
| 4 | 分片 + 事件溯源 + 缓存 | 大规模 | ✅ 在 |

### 企业级对话存储的真实分层

| 层 | 技术 | 存什么 |
|----|------|--------|
| 热数据（正在聊的） | Redis | 当前会话上下文、token 用量、临时状态 |
| 主存储（历史对话） | PostgreSQL / MySQL | 会话表、消息表、用户表，按用户检索 |
| 向量（RAG） | pgvector / Milvus | 知识库片段向量、对话摘要向量 |
| 大内容 | S3 / 对象存储 | 上传的文档、图片、附件 |
| 审计 | 消息队列 + 日志 | 谁在什么时候问了什么（合规） |

### 表结构设计（对话数据是强关联数据，适合关系型）

```sql
CREATE TABLE conversations (
  id UUID PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES users(id),
  title TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE messages (
  id UUID PRIMARY KEY,
  conversation_id UUID REFERENCES conversations(id) ON DELETE CASCADE,
  role TEXT,            -- 'user' / 'assistant' / 'system'
  content TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_messages_conv ON messages(conversation_id);
```

### 为什么企业级必须用数据库（不用文件）

1. **多实例部署**：N 个 pod 各有一份本地 JSON，请求打到不同 pod 历史不一致；数据库是所有实例共享的单一事实源。
2. **并发与事务**：多用户同时写，文件系统无任何保障。
3. **查询能力**：`WHERE user_id=? AND created_at > ?` 按用户/时间/关键词检索。
4. **审计合规**：金融/医疗要求对话留痕可追溯。
5. **容量**：文件无限增长，单点 IO 爆炸。

### 本项目现状与升级路径

- 当前：`history.py` 已用 PostgreSQL + SQLAlchemy async（档次 3），conversations/messages 表关系型存储。
- RAG：documents/chunks 表 + pgvector（Vector 列），对话与向量同库。
- 下一步：Alembic 迁移、user_id 多租户、检索重排（rerank）。

### 面试素材

> "我在项目里用 PostgreSQL 做对话持久化，按 user_id 关联会话，支持跨设备、跨会话查询——这解决了我司 AI studio 关闭就丢历史的痛点。"

---

## 3. AI Studio 历史记录重置排查

### 判断矩阵（关键信号：刷新 vs 关闭）

| 存储方案 | 刷新后 | 关闭后 | 判定 |
|---------|--------|--------|------|
| localStorage | ✅ | ✅ | ❌ 排除 |
| 数据库/文件落盘 | ✅ | ✅ | ❌ 排除 |
| 前端组件内存（React state） | ❌ | ❌ | 刷新就丢 |
| **sessionStorage** | ✅ | ❌ | ✅ **关闭丢、刷新不丢 = 实锤** |
| **后端内存 + session cookie** | ✅ | ❌ | ✅ 符合（cookie 过期/连接断开） |

### 最可能的公司实现（按概率排序）

1. **前端 sessionStorage**：对话存在 `sessionStorage`，标签页关闭浏览器直接销毁。内部工具赶工、无登录体系时的常见选择。
2. **后端进程内存 + session cookie**：历史存在后端内存，关浏览器 cookie 过期，服务端找不到会话。
3. **故意不持久化**：合规/隐私设计，对话不落库。

### 5 分钟验证步骤

1. **实验 1**：聊几句后只刷新（F5）不关闭
   - 历史还在 → 会话级存储，继续实验 2
   - 历史没了 → 前端内存
2. **实验 2**：DevTools → Application → **Session Storage**
   - 有对话相关数据 → 实锤 sessionStorage
   - 没有 → Network 面板刷新时有无 `GET /history` 请求：
     - 有 → 后端存储绑定 session（关浏览器 cookie 失效）
     - 无 → 前端存储

### 商业洞察

> 很多公司的内部 AI 工具停留在"演示级"存储，离企业级生产化有差距——这正是求职者的机会点。

---

## 4. RAG 链路 + pgvector

### 架构（已实现）

```
上传文档(txt/md/pdf) → 解析 → 切分(500字符/overlap 50) → embedding → pgvector 入库
提问 → embedding → pgvector 余弦距离 top-k → 拼入 system prompt → LLM 生成(带来源标注)
```

### 表设计

```sql
CREATE TABLE documents (
  id SERIAL PRIMARY KEY,
  title TEXT, source TEXT, created_at FLOAT
);
CREATE TABLE chunks (
  id SERIAL PRIMARY KEY,
  document_id INT REFERENCES documents(id) ON DELETE CASCADE,
  chunk_index INT,
  content TEXT,
  embedding vector(512)   -- pgvector 列，维度=embedding 模型输出维度
);
-- 检索：ORDER BY embedding <=> $1 LIMIT k（余弦距离）
```

### Embedding 三模式（EMBEDDING_PROVIDER）

| 模式 | 实现 | 质量 | 成本 |
|------|------|------|------|
| local（默认 auto 优先） | fastembed + BAAI/bge-small-zh-v1.5 | ⭐⭐⭐ 中文好 | 0，首次下载 ~90MB |
| api | OpenAI 兼容 /embeddings | ⭐⭐⭐⭐ | 按量付费 |
| mock | feature-hashing 词重叠 | ⭐ 仅链路演示 | 0 |

实测：mock 检索 score 0.03-0.46 区分度弱（"报销"问题召回年假 chunk）；
bge-small-zh 检索 score 0.56-0.73 正确命中。**本地 embedding 是零成本高质的解。**

### 切分设计要点

- 段落优先 → 句子 → 字符兜底（贪心合并到 chunk_size）
- **overlap 50 字符**：跨 chunk 边界语义断裂时减少信息丢失
- 中文按句号/问号/感叹号切句（正则 lookbehind）

### 提示词设计（防幻觉）

```
仅基于下面资料回答 + 末尾用 [资料1] 标注来源 + 资料没有就明说
```

### 关键决策记录

1. **pgvector 而非独立向量库（Chroma/Pinecone）**：对话+向量同库，运维简单，PostgreSQL 生态成熟；
   SQLAlchemy 直接支持 `Vector` 类型。
2. **embedding 本地化**：中文知识库 bge 质量高、零 API 成本、数据不出内网（合规）。
3. **检索结果按内容去重**：重复上传/overlap 导致重复片段，去重避免 prompt 冗余。

---

## 4.1 Render 云端部署经验（08-11）

### 部署方式：Blueprint（IaC）

`render.yaml` 声明式定义 Web Service + PostgreSQL，网页点 Apply 自动创建：

```yaml
services:
  - type: web
    runtime: docker
    rootDir: projects/llm-qa-service
    plan: free
    healthCheckPath: /health
    envVars:
      - key: DATABASE_URL
        fromDatabase: { name: llmqa-db, property: connectionString }
      - key: LLM_API_KEY
        sync: false          # 密钥不由蓝图管理，控制台手动填
databases:
  - name: llmqa-db
    plan: free
```

### 踩坑 / 注意点

1. **URL 格式兼容**：Render 给的是 `postgresql://...`，SQLAlchemy async 需要 `postgresql+psycopg://`，
   db.py 里启动时自动替换。
2. **secret 不进蓝图**：`sync: false` + 控制台填 LLM_API_KEY，避免 key 进 git。
3. **免费层限制**：闲置 15 分钟休眠（冷启动 ~30s）；256MB 数据库；1 个实例 750h/月。
4. **健康检查路径**：`/health` 必须返回 200，否则 Render 标记 unhealthy。

### Baseline（云端）

| 指标 | 值 |
|------|-----|
| 部署平台 | Render（免费层） |
| 公网地址 | https://llm-qa-service.onrender.com |
| 功能验证 | 上传文档 + RAG 问答 ✅ |

### IaC 面试讲法

> "我用 render.yaml 以声明式方式定义云端资源（Web 服务 + 托管 PostgreSQL），
> 一键 Apply 自动创建。这本质是基础设施即代码（IaC）——
> 同 docker-compose（本地）同源，企业级对应 Terraform/CloudFormation。
> 优势：可版本控制、可复现、密钥不入库。"

---

## 5. async SQLAlchemy 踩坑记录

### 坑 1：async 下 lazy load 抛 MissingGreenlet

```
# ❌ 访问 relationship 未预加载 → MissingGreenlet
conv.messages  /  doc.chunks

# ✅ 查询时 selectinload 预加载
select(Conversation).options(selectinload(Conversation.messages))
```

### 坑 2：lazy load 在 session 关闭后抛 DetachedInstanceError

`create_conversation` 返回 dict 时访问 `conv.messages`：新会话必然无消息，直接构造 dict，不触发 lazy load。

### 坑 3：commit 后仍可能报错——数据已写入（脏数据）

上传端点中，lazy load 报错发生在 `commit()` 之后 → 文档已入库但请求返回 500。
排查时先查库（`SELECT * FROM documents`）确认脏数据。

### 坑 4：FastAPI 依赖 `get_db` 不能直接 `async with`

`get_db` 是 async generator（依赖），要用 `get_session_factory()()` 直接开 session。

---

## 6. 代码位置索引与待办

### 已写入代码注释的知识点

| 位置 | 内容 |
|------|------|
| `app/llm_client.py` | OpenAI 兼容协议、mock 模式、SSE 流式格式、function calling、连接池上限 + 指数退避重试 |
| `app/agent.py` | Tool 抽象、Agent 循环、内置工具、安全 eval |
| `app/main.py` | liveness/readiness、SSE 协议、会话"先存后读"的坑、agent 端点 |
| `app/history.py` | 文件存储取舍（注释声明生产应换数据库） |
| `app/config.py` | secret 不进代码库、mock 模式 |
| `Dockerfile` | 分层缓存顺序、非 root 用户 |
| `tests/test_api.py` | 单例重置原因 |

### 待落实 TODO（补充到代码时勾选）

- [x] LLMClient 加连接池上限参数（`httpx.Limits`）
- [x] LLM API 调用加重试（指数退避，处理 429/5xx）
- [x] 存储层升级 PostgreSQL + SQLAlchemy（替换 JSON 文件）
- [x] RAG 链路 + pgvector（上传/切分/检索/生成/来源标注）
- [x] Agent 开发（tool calling / 工具循环，3 个内置工具）
- [x] MCP（Model Context Protocol）接入（stdio / Streamable HTTP，server + tool allow-list）
- [ ] 会话按 user_id 隔离（目前无用户体系，所有会话平铺）
- [ ] 前端加"清空历史"确认提示，避免误删
- [ ] 数据库迁移工具（Alembic）替代 create_all
- [ ] 检索重排（rerank）与混合检索（BM25 + 向量）

---

## 7. Agent 循环 + tool calling

### 已实现的调用链

```text
用户问题 → LLM（带 tools JSON Schema）
          ├─ 直接回答 → 返回最终答案
          └─ tool_calls → 执行本地工具 → role="tool" 回填结果 → 再调用 LLM
```

本项目将知识库检索、精确计算和香港当前时间统一抽象为 `Tool`。`Agent` 只负责循环和协议拼装；添加新工具时只需提供名称、说明、JSON Schema 和异步函数，不必改动循环逻辑。

### OpenAI 兼容协议要点

1. 请求携带 `tools=[{"type":"function","function":{name,description,parameters}}]` 与 `tool_choice="auto"`。
2. 模型返回 `message.tool_calls`，其中包含调用 ID、函数名与 JSON 字符串参数。
3. 服务执行工具后，以 `role="tool"`、相同 `tool_call_id` 将结果回填。
4. 重复调用模型，直到它不再请求工具或达到迭代上限。

### 安全与运行边界

- 工具参数由模型生成，不应被直接信任：检索词长度、`top_k` 和计算式长度均有限制。
- 计算器用 AST 白名单实现，只允许数字和受限的算术运算；拒绝函数调用、属性访问、超大指数与异常大的中间结果。
- 一次请求默认最多 5 次模型迭代、最多 12 次工具调用；工具输出也会截断，防止上下文和响应无限膨胀。
- 无法解析的 JSON、未知工具和参数不匹配会作为工具错误回填，让模型有机会修正，而不是让服务崩溃。

### 当前范围与下一步

当前完成的是单 Agent + 本地工具的最小可用版本，接口为 `/agent` 和 `/agent/stream`，前端会显示工具调用标签。

### MCP 接入（已实现）

`app/mcp_client.py` 支持 stdio 与 Streamable HTTP MCP server。每次启用 MCP 的 Agent 请求会：连接部署者在 `MCP_SERVERS_JSON` 中配置的 server → `list_tools` → 仅保留 `allowed_tools` → 加上 `mcp_<server>_<tool>` 命名空间 → 转换为本地 `Tool` 后交给现有 Agent loop。

安全原则：API 请求只能传 `use_mcp: true`，不能指定 server 命令、URL 或 token；每个 server 必须显式列工具 allow-list，限制 server 数、工具数、调用超时和结果长度。`/mcp/tools` 可以检查当前部署实际暴露的工具。`app/demo_mcp_server.py` 与测试覆盖用于本地协议验收。

### 面试问题库（持续追加）

**Q1：liveness 和 readiness 的区别？**
- liveness = 容器是否活着，失败则 kill & restart
- readiness = 是否准备好接收流量，失败则摘除不路由流量
- 关键：readiness 失败 ≠ 重启，liveness 失败 = 重启

**Q2：为什么用单例 + 连接池？（见 [第 1 节](#1-单例--连接池复用)）**

**Q3：对话历史存在哪？（见 [第 2 节](#2-会话存储从文件到企业级数据库)）**
- 从 JSON 文件 → PostgreSQL 的演进理由
- 多实例一致性、事务、查询、审计、容量

**Q4：LLM 输出为什么不能直接 innerHTML？**
- LLM 输出不可信（prompt injection），`marked` 转 HTML 后必须过 `DOMPurify.sanitize()`
- 前端 `renderMarkdown()` 已实现双层防护

**Q5：为什么用 OpenAI 兼容协议？**
- 一套代码接所有主流供应商（DeepSeek/OpenAI/Moonshot/Ollama），vendor lock-in 最小
- 换供应商 = 改 .env 两个变量，零代码改动

**Q6：RAG 为什么用 pgvector？**
- 向量检索与关系数据同库（对话表+向量表），无额外运维成本
- SQLAlchemy 原生支持 Vector 类型，SQL 就能做余弦检索

**Q7：切分为什么要 overlap？**
- 跨 chunk 边界语义断裂，overlap 保留上下文，减少信息丢失

**Q8：embedding 为什么本地化？**
- 中文知识库 bge-small-zh 质量高、零 API 成本、数据不出内网（合规敏感场景）

**Q9：async SQLAlchemy 的坑？（见 [第 5 节](#5-async-sqlalchemy-踩坑记录)）**
- relationship 访问必须 selectinload，否则 async 下 lazy load 抛 MissingGreenlet

**Q10：什么是 function calling / tool calling？（见 [第 7 节](#7-agent-循环--tool-calling)）**
- LLM 返回「函数名 + JSON 参数」而非直接回答；agent loop 执行工具并回喂结果

**Q11：为什么把 RAG 检索包装成工具？**
- 让模型自主决定「要不要检索、检索什么」，而不是强制每次都检索
- 与计算器/查时间并列，统一走 tool calling 协议，agent 循环零改动

**Q12：怎么知道 Agent 开发做好了？怎么测试？（三层测试法）**
- **第 1 层 · 自动化测试（验证循环逻辑）**：mock LLM 确定性模拟工具选择（问算式→calculator、时间词→get_current_time、有 mcp_* → 选它），验证工具被正确调用、工具结果回填、安全边界（AST 白名单拒绝 `__import__`/超大指数）、容错（未知工具/坏参数回填给模型修正不崩溃）、迭代上限防死循环。本项目 24 个用例，GitHub Actions push 自动跑。
- **第 2 层 · 手动 API 测试（验证真实模型决策）**：mock 只证明循环逻辑对，不证明真实模型会调对工具。本地起服务 + 真实 key，逐场景 curl 验证：算术→calculator、时间→get_current_time、手册问题→search_knowledge_base、多步问题→连续调用多个工具。
- **第 3 层 · 云端端到端（验证部署）**：`/health` UP → `/mcp/tools` 列出 allow-list 工具 → `/agent` 真实混合调用内置 + MCP 工具。
- **关键认知（面试亮点）**：这套测试验证「机制正确」（工具调对、循环不崩、安全到位），不验证「回答质量」——质量评估是另一层，需要评测集 + Ragas 等指标。区分这两件事本身就是工程素养。
- **安全行为必测**：未配置 MCP 时请求 `use_mcp: true` 必须 503 明确报错，而非静默忽略；危险表达式、超长参数、迭代超限全部有明确错误路径。
