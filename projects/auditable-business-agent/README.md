# Auditable Business Agent

企业售后与客服工单可审计 Agent。

## 项目边界

本项目是独立项目，与 [`../llm-qa-service`](../llm-qa-service) 分开开发、运行和验证。原有项目不作为本项目的运行时依赖。

## 项目目标

构建一个能处理售后请求的业务 Agent：

1. 识别用户意图。
2. 检索产品政策和操作手册。
3. 查询订单与历史工单等业务数据。
4. 根据确定性业务规则给出处理建议。
5. 对创建工单、修改状态、发送通知等副作用操作请求人工审批。
6. 保存可复核的证据、工具调用、审批和执行记录。

第一版只使用公开文档、脱敏样例和模拟业务系统，不连接真实退款、邮件或生产数据库。

## 预期演示

用户提出售后请求后，页面展示：

```text
请求 → 意图识别 → 文档检索 → 订单查询 → 规则判断
                                      ↓
                              回复 / 待审批操作
                                      ↓
                       审批 → 模拟执行 → 审计记录
```

审计记录保存结构化证据和执行轨迹，不保存或展示模型隐藏的思维链：

- 请求和响应
- 使用的文档、版本和引用位置
- 工具名称、参数和返回结果
- 规则判断结果
- Agent 建议的操作
- 审批人、审批决定和修改内容
- 实际执行结果
- 模型、提示词、代码版本、耗时和成本

## 计划技术栈

- Python、FastAPI
- LangGraph：工作流编排、状态持久化和人工审批
- LangChain：模型、检索和工具适配
- PostgreSQL：业务样例、工作流状态和审计记录
- pgvector：知识库向量检索
- LangSmith：Trace、调试和离线评测
- Docker Compose：本地运行

LangGraph 只用于需要状态、恢复或人工介入的流程；确定性的业务判断保留在普通 Python 代码中。

## 目录规划

```text
auditable-business-agent/
├── app/                 # 应用代码
├── docs/                # 设计、决策和项目状态
├── evals/               # 评测数据与评测脚本
├── sample_data/         # 脱敏样例和公开文档
├── tests/               # 自动化测试
├── .env.example
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
└── README.md
```

## 开发阶段

1. ✅ 项目骨架、业务模型、模拟订单/工单工具、确定性规则引擎和审计日志
2. LangGraph Agent 工作流与人工审批持久化
3. ✅ 政策检索、引用证据、可替换的客服回复生成器和前端演示
4. ✅ LangChain + pgvector 向量 RAG 与幂等政策导入
5. API、Docker 和简历材料

## P0 验证

P0 与 P1 的存储测试不依赖大模型。默认使用 SQLite 临时库验证 repository；正式运行使用 PostgreSQL：

```bash
uv run python -m unittest discover -s tests -v

### PostgreSQL 本地启动

```bash
cp .env.example .env
docker compose up -d
uv sync
uv run alembic upgrade head
uv run python -m app.seed
```

### P1 API 与审批工作流

创建两个本地测试账号；密码不会写入数据库明文：

```bash
uv run python -m app.manage_users agent-1 --role customer_service
uv run python -m app.manage_users reviewer-1 --role approver
```

忘记本地测试账号密码时，不能读取旧密码；可设置一个新密码：

```bash
uv run python -m app.manage_users agent-1 --reset-password
uv run python -m app.manage_users reviewer-1 --reset-password
```

启动 API：

```bash
uv run uvicorn app.main:app --env-file .env --port 8000 --reload
```

打开 `http://127.0.0.1:8000/docs`，按以下顺序验证：

1. `POST /auth/login` 获取客服或审批人的 bearer token。
2. 使用客服 token 调用 `POST /cases` 创建案例。
3. 退货或维修案例返回 `202 Accepted`，工作流暂停等待审批。
4. 使用审批人 token 调用 `POST /cases/{case_id}/approval` 恢复工作流。
5. 调用 `GET /cases/{case_id}/audit` 查看完整审计事件。

`customer_service` 账号不能调用审批接口；`approver` 才能批准或拒绝。开发环境的 `.env` 必须设置唯一的 `AUTH_SECRET`，部署前不要使用示例值。
```

### P2 Web 演示与检索

构建前端后，API 会在同一端口提供 React 页面：

```bash
cd frontend
npm install
npm run build
cd ..
uv run uvicorn app.main:app --env-file .env --port 8000
```

打开 `http://127.0.0.1:8000/`。以 `agent-1` 登录后，可创建案例，并看到审计轨迹中的：

- `knowledge_retrieved`：政策文档 ID、版本、摘录与匹配分数；
- `rule_evaluated`：不可被模型覆盖的业务规则；
- `reply_generated`：客服回复和生成器来源；
- `approval_*` 与 `action_executed`：审批和模拟副作用。

政策文档位于 `sample_data/policies/`。生产运行时使用 LangChain `Document`、`RecursiveCharacterTextSplitter`、`Embeddings` 和 `PGVector`。启动时会把政策文档切分、向量化并幂等写入 PostgreSQL；检索按 `request_type` 过滤，并返回文档 ID、版本、chunk 和摘录。默认 `RAG_EMBEDDING_PROVIDER=local` 使用可复现的本地向量实现，适合无密钥演示；配置 `RAG_EMBEDDING_PROVIDER=openai`、`EMBEDDING_API_KEY` 和对应维度后使用真实 OpenAI embeddings，OpenAI 向量保存在独立 collection 中，避免维度混用。配置 `LLM_CHAT_COMPLETIONS_URL`、`LLM_API_KEY`、`LLM_MODEL` 后，回复生成会切换到 OpenAI-compatible Chat Completions；未配置时使用模板回复。LangGraph/LangChain 兼容 `LANGSMITH_TRACING`、`LANGSMITH_API_KEY` 和 `LANGSMITH_PROJECT` 环境变量。

运行黄金案例回归：

```bash
uv run python evals/run_golden_cases.py
```

当前状态见 [`docs/project-status.md`](docs/project-status.md)。
