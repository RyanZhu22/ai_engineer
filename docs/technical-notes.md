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

### ⚠️ 可改进点（TODO）

- [ ] `httpx.AsyncClient` 未配置连接池上限，可加：

```python
self._client = httpx.AsyncClient(
    timeout=60.0,
    limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
)
```

- [ ] 加指数退避重试（LLM API 偶发 429/5xx）

### 面试讲法（30 秒版）

> "LLM 客户端我用了单例模式 + httpx 连接池复用。HTTP 连接需要 TCP 握手和 TLS 协商，每次请求新建成本很高。单例保证整个应用只建一个 AsyncClient，连接池里的连接反复复用，延迟和资源占用大幅降低。应用关闭时在 lifespan 里显式 aclose 释放连接，避免悬挂连接。"

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
| `app/llm_client.py` | OpenAI 兼容协议、mock 模式、SSE 流式格式 |
| `app/main.py` | liveness/readiness、SSE 协议、会话"先存后读"的坑 |
| `app/history.py` | 文件存储取舍（注释声明生产应换数据库） |
| `app/config.py` | secret 不进代码库、mock 模式 |
| `Dockerfile` | 分层缓存顺序、非 root 用户 |
| `tests/test_api.py` | 单例重置原因 |

### 待落实 TODO（补充到代码时勾选）

- [ ] LLMClient 加连接池上限参数（`httpx.Limits`）
- [ ] LLM API 调用加重试（指数退避，处理 429/5xx）
- [x] 存储层升级 PostgreSQL + SQLAlchemy（替换 JSON 文件）
- [x] RAG 链路 + pgvector（上传/切分/检索/生成/来源标注）
- [ ] 会话按 user_id 隔离（目前无用户体系，所有会话平铺）
- [ ] 前端加"清空历史"确认提示，避免误删
- [ ] 数据库迁移工具（Alembic）替代 create_all
- [ ] 检索重排（rerank）与混合检索（BM25 + 向量）

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
