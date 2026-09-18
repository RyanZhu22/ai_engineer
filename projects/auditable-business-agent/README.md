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
2. ✅ LangGraph Agent 工作流与人工审批持久化
3. ✅ 政策检索、引用证据、可替换的客服回复生成器和前端演示
4. ✅ LangChain + pgvector 向量 RAG 与幂等政策导入
5. ✅ API、Docker 生产镜像、RAG 质量评测和异常/安全测试
6. ✅ 浏览器端到端测试与 GitHub Actions CI
7. ✅ 本地 BGE 真实 Embedding、独立向量 collection 与真实检索评测
8. ✅ 扩充 RAG 评测集：36 条平衡查询、边界样本与跨主题干扰样本

## P0 验证

P0 与 P1 的存储测试不依赖大模型。默认使用 SQLite 临时库验证 repository；正式运行使用 PostgreSQL：

```bash
uv run python -m unittest discover -s tests -v
```

### PostgreSQL 本地启动

```bash
cp .env.example .env
docker compose up -d database
uv sync
uv run alembic upgrade head
uv run python -m app.seed
```

### Docker 生产化验证

Docker 镜像使用多阶段构建：Node 阶段编译 React，Python 阶段只保留运行时依赖、API、迁移文件和政策文档。API 容器启动时执行迁移和幂等 seed，健康检查通过后才对外提供服务。

```bash
cp .env.example .env
docker compose up -d --build
docker compose ps
curl http://127.0.0.1:8000/health
```

打开 `http://127.0.0.1:8000/` 验证 Web 演示。查看日志或停止服务：

```bash
docker compose logs --tail=100 api
docker compose down
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
# 如果 API 容器正在运行，先停止它以释放 8000 端口
docker compose stop api
uv run uvicorn app.main:app --env-file .env --port 8000 --reload
```

打开 `http://127.0.0.1:8000/docs`，按以下顺序验证：

1. `POST /auth/login` 获取客服或审批人的 bearer token。
2. 使用客服 token 调用 `POST /cases` 创建案例。
3. 退货或维修案例返回 `202 Accepted`，工作流暂停等待审批。
4. 使用审批人 token 调用 `POST /cases/{case_id}/approval` 恢复工作流。
5. 调用 `GET /cases/{case_id}/audit` 查看完整审计事件。

`customer_service` 账号不能调用审批接口；`approver` 才能批准或拒绝。开发环境的 `.env` 必须设置唯一的 `AUTH_SECRET`，部署前不要使用示例值。

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

政策文档位于 `sample_data/policies/`。生产运行时使用 LangChain `Document`、`RecursiveCharacterTextSplitter`、`Embeddings` 和 `PGVector`。启动时会把政策文档切分、向量化并幂等写入 PostgreSQL；检索按 `request_type` 过滤，并返回文档 ID、版本、chunk 和摘录。默认 `RAG_EMBEDDING_PROVIDER=bge` 使用 FastEmbed 的本地 `BAAI/bge-small-zh-v1.5`（512 维）进行真实中文 embedding；首次运行会下载模型。`local` 是可复现的 256 维基线；`openai` 需要 `EMBEDDING_API_KEY`。不同 provider 和维度写入独立 collection，避免混用。`LLM_CHAT_COMPLETIONS_URL`、`LLM_API_KEY`、`LLM_MODEL` 控制 OpenAI-compatible 回复生成器，可配置 DeepSeek；它与 embedding provider 独立。未配置时使用模板回复。LangGraph/LangChain 兼容 `LANGSMITH_TRACING`、`LANGSMITH_API_KEY` 和 `LANGSMITH_PROJECT` 环境变量。

运行黄金案例回归：

```bash
uv run python evals/run_golden_cases.py
```

运行政策向量检索质量评测。评测集位于 `evals/retrieval_cases.json`，包含 36 条退货、维修、物流查询，覆盖同义改写、时间边界、材料要求、物流延迟和跨主题干扰文档；脚本会输出 Recall@1、Recall@K 和 MRR。可复现的本地基线：

```bash
uv run --env-file .env python evals/run_retrieval_eval.py --provider local --k 1 --min-recall 0.65
```

本地 BGE 的真实 embedding 评测不需要 API Key：

```bash
uv run --env-file .env python evals/run_retrieval_eval.py --provider bge --k 1 --min-recall 0.91 --output retrieval-bge.json
```

OpenAI embedding 是可选对照，需要在 `.env` 设置 `EMBEDDING_API_KEY`（或 `OPENAI_API_KEY`）以及 `RAG_EMBEDDING_PROVIDER=openai`：

```bash
uv run --env-file .env python evals/run_retrieval_eval.py --provider openai --k 1 --min-recall 0.8 --output retrieval-openai.json
```

浏览器端到端测试使用独立的 `e2e-agent` 和 `e2e-approver` 账号，不会修改手动演示账号。先确保 Docker API 运行，再执行：

```bash
docker compose up -d
uv run --env-file .env python scripts/seed_e2e_users.py
cd frontend
npm ci
npx playwright install chromium
npm run test:e2e
```

GitHub Actions 配置位于 `.github/workflows/ci.yml`，会执行单元测试、黄金案例、local 与 BGE 检索评测、前端构建、Docker 和浏览器 E2E。仓库配置 `OPENAI_API_KEY` Secret 后，CI 会额外运行 OpenAI Embedding 对照评测并上传结果 JSON。

异常与安全回归覆盖：缺失订单、订单归属不匹配、重复 `case_id`、未认证请求、篡改 JWT、JWT 声明角色与数据库角色不一致、政策文档缺失和回复模型失败降级。运行全部测试：

```bash
uv run python -m unittest discover -s tests -v
```

当前状态见 [`docs/project-status.md`](docs/project-status.md)。
