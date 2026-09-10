# 项目当前状态与交接

> 这是跨终端继续开发时的首个阅读入口。先看本文件，再按“文件入口”和“下一步”继续工作。
>
> 最近更新：2026-09-10

## 1. 项目位置

| 项目 | 路径 |
|---|---|
| 工作区 | `/Users/ryan/developer/career_study/ai_engineer` |
| 服务项目 | `/Users/ryan/developer/career_study/ai_engineer/projects/llm-qa-service` |
| 当前分支 | `main` |
| 最近已提交版本 | `7b44b43 update` |
| 远端状态 | 记录时 `origin/main` 与最近已提交版本一致 |

在新终端快速定位：

```bash
cd /Users/ryan/developer/career_study/ai_engineer
sed -n '1,260p' docs/project-status.md
git status --short
cd projects/llm-qa-service
```

## 2. 当前工作区状态

P0-1“登录与账号级资源隔离”代码已经完成并通过本地验证，但还没有提交和推送。当前未提交改动分为两组：

- 代码与测试：`app/auth.py`、`app/security.py`、`app/manage_users.py`、`app/db.py`、`app/history.py`、`app/main.py`、`app/static/index.html`、`tests/test_auth.py`、`tests/test_api.py`
- 文档同步：`progress.md`、`docs/technical-notes.md`、`docs/llm-qa-service-project-summary.md`、`docs/llm-qa-service-interview-qa.md`、`projects/llm-qa-service/README.md`、`resume-ai-engineer.md`，以及本文件

不要在未确认前使用 `git reset --hard` 或覆盖这些文件。继续开发前先运行：

```bash
git status --short
git diff --stat
```

## 3. 已完成能力

### 核心服务

- FastAPI REST 与 SSE 流式问答
- OpenAI 兼容的 DeepSeek/OpenAI/Ollama/Mock 客户端
- `httpx.AsyncClient` 连接池、429/5xx/网络错误重试、`Retry-After` 和 jitter
- PostgreSQL 16 + pgvector 持久化
- txt/md/pdf 上传、切片、embedding、文档管理

### RAG、Agent、MCP

- 向量检索 + BM25 + 句级 rerank + RRF 混合检索
- `[资料1]` 来源引用和资料不足拒答
- Agent 内置检索、AST 安全计算器、当前时间工具
- stdio / Streamable HTTP MCP；server 与 tool allow-list
- 工具调用次数、循环次数、参数、超时和输出长度限制

### 认证与隔离（P0-1）

- `/auth/login`、`/auth/me`、`/auth/logout`
- scrypt 密码哈希；数据库只保存 bearer token 哈希
- token 默认 8 小时过期，支持主动撤销
- 会话、文档、切片、普通聊天、SSE、RAG 和 Agent 按 `owner_id` 隔离
- MCP 需要账号具有 `can_use_mcp`
- `python -m app.manage_users USERNAME [--allow-mcp]` 创建账号

### 评测与交付

- 31 条版本化评测样本：29 条可回答、2 条不可回答
- CI 离线门槛：mock + hybrid，Hit@1 ≥ 95%，Hit@4 = 100%
- 真实 LLM 可选检查关键词、引用、拒答和 LLM-as-a-judge
- Docker Compose 本地 pgvector；Render 云端部署和 Agent/MCP 验证已完成
- GitHub Actions 已运行完整测试和 RAG 质量门槛

## 4. 最近验证结果

| 检查 | 最近结果 |
|---|---|
| 自动化测试 | `54 passed in 5.13s` |
| 工作区格式检查 | `git diff --check` 通过 |
| mock + hybrid RAG | Hit@1 96.5%，Hit@3 100%，Hit@4 100%，MRR 0.9828 |
| local bge + hybrid RAG | Hit@1/3/4 100%，MRR 1.0000 |
| DeepSeek live + judge | 31/31 JSON 可解析；本次候选与裁判使用同一模型 |
| PostgreSQL | Docker Compose 中 `llm-qa-pg` healthy |

重新验证命令：

```bash
cd /Users/ryan/developer/career_study/ai_engineer/projects/llm-qa-service
docker compose up -d
.venv/bin/python -m pytest -q
.venv/bin/python -m evals.run_rag_eval \
  --embedding-provider mock \
  --retrieval-mode hybrid \
  --min-hit-at-1 0.95 \
  --min-hit-at-k 1.0
```

## 5. 下一步优先级

### P0：收尾当前改动

1. 查看 `git diff`，确认 P0-1 代码和文档没有覆盖用户改动。
2. 再跑测试和 `git diff --check`。
3. 提交 P0-1 代码、测试和文档；只有用户明确要求时才推送。
4. 推送后重新部署 Render，再验证登录、跨账号隔离和 MCP 权限。

### P1：生产化缺口

1. 用 Alembic 管理 `users`、`login_sessions`、`owner_id` 等 schema 迁移，替代生产环境依赖 `create_all`。
2. 增加前端“清空历史”二次确认。
3. 增加登录和高成本 LLM 接口的限流、审计日志和基础可观测性。
4. 增加备份/恢复演练与 token/session 清理策略。

### P2：企业能力与规模化

1. 企业 SSO/OIDC、组织/部门权限和管理员后台。
2. 更细粒度的租户/知识库授权。
3. 知识库变大后，将进程内 BM25 迁移到带中文分析器的专用索引。
4. 使用独立裁判模型做一次交叉复核；这项是评测增强，不是当前 CI 门槛。

## 6. 文件入口

| 需要查看 | 文件 |
|---|---|
| 时间线和每日进度 | [`progress.md`](../progress.md) |
| 服务启动、API、数据库和部署 | [`projects/llm-qa-service/README.md`](../projects/llm-qa-service/README.md) |
| 设计取舍、代码索引和 TODO | [`technical-notes.md`](technical-notes.md) |
| Agent/MCP 手动测试 | [`agent-testing.md`](agent-testing.md) |
| RAG/LLM 评测命令和指标 | [`projects/llm-qa-service/evals/README.md`](../projects/llm-qa-service/evals/README.md) |
| 项目总结、简历和面试素材 | [`llm-qa-service-project-summary.md`](llm-qa-service-project-summary.md)、[`llm-qa-service-interview-qa.md`](llm-qa-service-interview-qa.md)、[`../resume-ai-engineer.md`](../resume-ai-engineer.md) |
| 最近的评测报告 | [`baseline.md`](../projects/llm-qa-service/evals/baseline.md)、[`latest-live-judge-report.refusal-v3.md`](../projects/llm-qa-service/evals/latest-live-judge-report.refusal-v3.md) |

## 7. 接手时的最短流程

```text
读本文件
  → git status / git diff
  → docker compose up -d
  → pytest -q
  → mock hybrid 评测
  → 检查 P0-1 diff
  → 提交
  → 按需推送并重新部署 Render
```

## 8. 当前明确未完成

- P0-1 当前工作区改动尚未提交、推送和重新部署。
- 没有企业 SSO、组织/部门权限和管理员后台。
- 生产 schema 迁移尚未切换到 Alembic。
- 前端清空历史没有二次确认。
- 尚未完成独立裁判模型交叉复核。

