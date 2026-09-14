# LLM QA Service 项目总结

> 当前代码、验证结果和跨终端交接流程见 [`project-status.md`](project-status.md)。

## 一句话介绍

这是一个面向企业内部知识库的 LLM 问答服务：用户上传员工手册等文档，系统完成切分、中文 embedding、混合检索和带来源回答；同一套服务还支持 Agent 工具调用、MCP 外部工具接入、SSE 流式输出和可重复的 RAG 质量评测。

## 项目背景与目标

目标不是做一个只能演示的聊天页面，而是把“LLM 能力”包装成可部署、可测试、可排障的后端服务，覆盖以下链路：

```text
文档上传 → 解析与切分 → embedding 入库 → pgvector/BM25 检索
                                      ↓
用户问题 → RAG 上下文 → LLM 回答 → 引用/拒答 → SSE/前端展示
                                      ↓
                         Agent 工具循环 / MCP 外部工具
```

## 已完成的核心工作

### 1. LLM 服务与 API 层

- 用 FastAPI 提供 `/chat`、`/chat/stream`、`/agent`、`/agent/stream`、文档管理、历史记录和检索调试接口。
- 用 OpenAI 兼容协议抽象 DeepSeek、OpenAI、Ollama 等供应商，切换供应商主要通过环境变量完成。
- `LLMClient` 使用可复用的 `httpx.AsyncClient` 连接池；对 429、5xx 和网络错误做指数退避、jitter 和 `Retry-After` 处理；4xx 客户端错误不盲目重试。
- 流式请求只在收到响应头前重试，避免已经输出的 token 被重复发送。

### 2. RAG 与知识库

- 支持 txt/md/pdf 上传，按段落、句子和字符上限切分，默认 500 字符、50 字符 overlap。
- 默认使用本地 `BAAI/bge-small-zh-v1.5`（512 维）生成中文向量，避免 embedding API 成本和敏感数据外传；同时保留 API/mock/auto 模式。
- 使用 PostgreSQL + pgvector 持久化 documents/chunks，并与会话数据放在同一关系数据库中。
- 当前默认 hybrid 检索流程：向量候选 + 中文 BM25 候选 → 候选块内最佳事实句 BM25 rerank → RRF 融合；`vector` 模式仍保留用于对照和排障。
- 回答提示词要求只使用检索资料、用 `[资料1]` 等标注来源、资料不足时明确说明。

### 3. Agent 与 MCP

- 将知识库检索、AST 安全计算器、香港当前时间统一抽象为 Tool。
- Agent 按“模型决策 → 执行工具 → 结果回填 → 再请求模型”的循环工作；每次请求最多 5 轮、12 次工具调用，并限制参数长度、`top_k`、计算表达式和工具输出。
- 支持 stdio 和 Streamable HTTP MCP；部署者配置 server 和 `allowed_tools`，客户端不能提交命令、URL 或 token；工具以 `mcp_<server>_<tool>` 命名空间接入现有 Agent loop。

### 4. 认证、评测、测试与部署

- P0-1 已加入密码登录和 8 小时可撤销 bearer session；账号由部署者通过 `python -m app.manage_users` 创建。
- 会话、文档、切片和 RAG/Agent 检索使用同一个 `owner_id` 过滤；MCP 额外检查账号权限。跨用户测试覆盖列表、详情、删除、普通聊天、SSE、RAG、Agent 和 MCP。

- 建立 31 条版本化中文评测集：29 条可回答、2 条不可回答，每条可回答题包含文档、原文证据和答案关键事实标注。
- 检索层有 Evidence Hit@1/@3/@4、MRR、平均/P50/P95 延迟；生成层检查关键词、引用格式/有效性/证据支持和资料不足拒答；可选 LLM-as-a-judge 检查忠实度、正确性和拒答恰当性。
- CI 使用不调用付费 LLM 的 mock + hybrid 检索门槛：Hit@1 ≥ 95%、Hit@4 = 100%。
- 已验证结果：

| 运行 | 结果 |
|---|---|
| mock + hybrid | Hit@1 96.5%，Hit@4 100%，MRR 0.9828 |
| local bge + hybrid | Hit@1/3/4 100%，MRR 1.0000；检索 P95 24.70 ms（该次运行） |
| DeepSeek live baseline | 31/31 裁判 JSON 可解析；关键词、引用、资料不足拒答和裁判指标均 100%（候选与裁判使用同一模型，不能当作独立准确率） |
| 自动化测试 | 58 个 pytest 用例，覆盖认证隔离、HNSW、基准参数、API、RAG、hybrid 检索、Agent、MCP、LLMClient 重试和评测逻辑 |

- 用 Docker Compose 提供 PostgreSQL 16 + pgvector；用 `render.yaml` Blueprint 部署到 Render，并完成云端健康检查、知识库问答和 Agent/MCP 端到端验证。

## 项目价值

1. 把“调用 LLM”扩展成可运行的服务：有 REST/SSE、持久化、部署和错误恢复。
2. 把“感觉检索变好了”变成可复现的指标和 CI 门槛，能定位是检索、生成、引用还是拒答出了问题。
3. 把 Agent 和 MCP 放在同一套 Tool 抽象下，新增工具不需要重写 Agent 编排逻辑。
4. 将模型生成的参数和外部工具视为不可信输入，加入 allow-list、AST 白名单、超时、数量、长度和重试边界。

## 中文简历项目经历（可直接粘贴）

**LLM QA Service｜企业知识库问答平台**　*FastAPI · PostgreSQL/pgvector · BM25 · Agent · MCP · Docker · GitHub Actions · Render*

- 负责企业知识库问答全链路：支持 txt/md/pdf 上传、中文文档切分、本地 `bge-small-zh-v1.5` embedding、PostgreSQL/pgvector 持久化，以及带 `[资料]` 引用的 RAG 回答。
- 设计并实现 hybrid 检索：向量候选 + 中文 BM25 + 候选块内句级 rerank + RRF 融合；31 条版本化评测集上，mock Hit@1/Hit@4 为 96.5%/100%，local bge 为 100%/100%，MRR 1.0000。
- 实现 ReAct-style Agent tool calling 与 MCP 适配器，统一接入知识库检索、AST 安全计算器、当前时间及 allow-list 的 stdio/Streamable HTTP 工具；限制循环次数、调用次数、参数、超时和输出长度。
- 通过异步 SQLAlchemy、SSE 流式响应、httpx 连接池与 429/5xx/网络错误指数退避提升服务可靠性；58 个 pytest 接入 GitHub Actions，配置 mock hybrid 检索质量门槛，并完成 Render 云端端到端验证。

## 当前仍未完成/不应在简历中过度声称的事项

- 当前是账号级隔离，还没有企业 SSO、部门/租户层级权限和管理员后台。
- 尚未用 Alembic 替换 `create_all`，生产数据库 schema 迁移仍需补齐。
- 前端“清空历史”还缺少二次确认。
- LLM-as-a-judge 的首份基线使用 `deepseek-chat` 同时生成和裁判；独立裁判模型交叉复核是可选下一步。
- 当前 P0-1 代码和测试已在本地数据库上验证，仍需按项目流程提交并推送；Render 部署也需要重新部署后再验证登录流程。

## 30 秒项目介绍

> 我做了一个企业知识库问答服务，后端是 FastAPI，数据和向量都放在 PostgreSQL/pgvector。RAG 先用本地中文 embedding 和 BM25 取候选，再做句级 rerank 和 RRF 融合，回答必须带引用，资料不足要拒答。为了验证优化不是主观感觉，我做了 31 条中文评测集和 CI 门槛，mock hybrid 的 Hit@1 是 96.5%，本地 bge 达到 100%。在此基础上又加了 Agent tool calling、allow-list 的 MCP 接入和账号级资源隔离，并用 58 个 pytest、Docker 和 Render 云端验证完整链路。
