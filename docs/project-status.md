# 项目当前状态与交接

> 这是跨终端继续开发时的首个阅读入口。先看本文件，再按“文件入口”和“下一步”继续工作。
> 跨端开工/收尾规则、长任务规范见 [`vibe-coding-workflow.md`](vibe-coding-workflow.md)。
>
> 最近更新：2026-09-14（本地账号隔离验证完成；Render 云端 Shell 受 Free 计划限制）

## 1. 项目位置

| 项目 | 路径 |
|---|---|
| 工作区 | `/Users/ryan/developer/career_study/ai_engineer` |
| 服务项目 | `/Users/ryan/developer/career_study/ai_engineer/projects/llm-qa-service` |
| 当前分支 | `main` |
| 最近已提交版本 | `455f181 feat: add pgvector HNSW index, retrieval benchmark, and cross-end workflow docs` |
| 远端状态 | `main` 与 `origin/main` 一致 |

在新终端快速定位：

```bash
cd /Users/ryan/developer/career_study/ai_engineer
sed -n '1,260p' docs/project-status.md
git status --short
cd projects/llm-qa-service
```

## 2. 当前工作区状态

P0-1“登录与账号级资源隔离”已提交为 `78f337d`；HNSW 索引与基准脚本已提交为 `455f181`，两者均已推送。

当前 P0 未提交改动是 HNSW 低内存基准支持、聚焦单测、正式报告和状态同步：

- 新测试：`tests/test_hnsw.py`，覆盖索引 DDL 参数、`ef_search` 边界与 `vector_candidates` 的 `document_ids` 过滤。
- `evals/bench_retrieval.py` 新增 `--embedding-batch-size`（1–256）参数；`tests/test_bench_retrieval.py` 覆盖边界。
- 正式报告：`evals/retrieval-bench.md`；文档同步：本文件、`progress.md`、服务 README、评测说明与测试手册。

已完成：HNSW 代码、mock 基准、真实 local bge 基准、4 条新增 HNSW/基准测试、全量 58 个 pytest、CI 同款 mock hybrid 评测。

2026-09-13 经用户允许停止 `kimi-k8s-control-plane` 后，固定 256 条 batch 仍在 256/2,000 切片时进入内存颠簸，因此停止并清理了 20 个临时文档和 256 条临时切片。新增 32 条 batch 后，2,005 切片正式基准完成且临时数据自动清理。

Render 已做只读验证：2026-09-13 `GET /health` 返回 200；未带 bearer token 的 `GET /history` 返回 401。Render Free 计划不提供 Shell，用户选择不升级，因此云端测试账号未创建。

本地回退验证已完成（2026-09-14）：`p0-a-local`（`can_use_mcp=false`）和 `p0-mcp-local`（`can_use_mcp=true`）均为 active；用户已完成登录、账号隔离和 MCP 权限手测。密码未写入文档。

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
- pgvector HNSW 索引 + `ef_search` / `iterative_scan` 参数（代码、mock/local bge 基准和单测已完成）
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
- Docker Compose 本地 pgvector；Render 云端部署和单账号 Agent/MCP 验证已完成；跨账号验证已在本地完成
- GitHub Actions 已运行完整测试和 RAG 质量门槛

## 4. 最近验证结果

| 检查 | 最近结果 |
|---|---|
| 自动化测试 | `58 passed in 5.18s`（2026-09-13，含 HNSW 与低内存 batch 参数测试） |
| 工作区格式检查 | `git diff --check` 通过（2026-09-13） |
| mock + hybrid RAG | Hit@1 96.5%，Hit@3 100%，Hit@4 100%，MRR 0.9828 |
| local bge + hybrid RAG | Hit@1/3/4 100%，MRR 1.0000 |
| DeepSeek live + judge | 31/31 JSON 可解析；本次候选与裁判使用同一模型 |
| PostgreSQL | Docker Compose 中 `llm-qa-pg` healthy |
| mock HNSW 基准 | 20005 切片：精确 P95 70.3ms → HNSW 2.55ms（27.6×），建索引 1.71s；mock 向量下 Recall@10 0.49–0.72，只验证机制 |
| local bge HNSW 基准 | 2,005 切片、15 条查询、1 pass、batch=32：精确 P95 9.88ms；HNSW ef=100 P95 9.07ms、Recall@10 1.000；ef=10 Recall@10 0.624。规模偏小，不作为大规模吞吐 SLO。 |
| Render 登录验证 | `GET /health` 为 200；未认证 `GET /history` 为 401（2026-09-13） |
| 本地账号隔离与 MCP 权限手测 | 两个账号均 active；普通账号 `can_use_mcp=false`，MCP 账号 `can_use_mcp=true`；用户确认登录、隔离和权限验证完成（2026-09-14） |

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

HNSW 基准（先释放内存 + 后台落盘日志，规则见 `vibe-coding-workflow.md` §3）：

```bash
# 按需停掉别的项目容器（本机 8GB，Docker VM 占 4GB）
docker stop kimi-k8s-control-plane cicd-demo-platform-jenkins-1 northstar-mysql cicd-demo-platform-docker-1

nohup .venv/bin/python -u -m evals.bench_retrieval \
  --sizes 2000 --queries 15 --passes 1 --embedding-provider local --embedding-batch-size 32 \
  --output evals/retrieval-bench.md > /tmp/bench.log 2>&1 &
tail -f /tmp/bench.log
```

## 5. 下一步优先级

### P0：收尾 HNSW 与上线验证（当前任务）

1. 本地 A/B 资源隔离和 MCP 权限验证已完成；Render Free 计划不提供 Shell，云端账号验证暂缓，不升级服务。
2. 提交本次 HNSW 单测、低内存 batch 参数、报告和状态文档。

### P1：P0-1 上线 + 生产化缺口

1. 用 Alembic 管理 `users`、`login_sessions`、`owner_id`、HNSW 索引等 schema 迁移，替代生产环境依赖 `create_all`。
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
| 跨端开工/收尾规则、长任务规范 | [`vibe-coding-workflow.md`](vibe-coding-workflow.md) |
| 时间线和每日进度 | [`progress.md`](../progress.md) |
| 服务启动、API、数据库和部署 | [`projects/llm-qa-service/README.md`](../projects/llm-qa-service/README.md) |
| 设计取舍、代码索引和 TODO | [`technical-notes.md`](technical-notes.md) |
| Agent/MCP 手动测试 | [`agent-testing.md`](agent-testing.md) |
| RAG/LLM 评测命令和指标 | [`projects/llm-qa-service/evals/README.md`](../projects/llm-qa-service/evals/README.md) |
| HNSW 向量索引基准脚本 | [`projects/llm-qa-service/evals/bench_retrieval.py`](../projects/llm-qa-service/evals/bench_retrieval.py) |
| 项目总结、简历和面试素材 | [`llm-qa-service-project-summary.md`](llm-qa-service-project-summary.md)、[`llm-qa-service-interview-qa.md`](llm-qa-service-interview-qa.md)、[`../resume-ai-engineer.md`](../resume-ai-engineer.md) |
| 最近的评测报告 | [`baseline.md`](../projects/llm-qa-service/evals/baseline.md)、[`retrieval-bench.md`](../projects/llm-qa-service/evals/retrieval-bench.md)、[`latest-live-judge-report.refusal-v3.md`](../projects/llm-qa-service/evals/latest-live-judge-report.refusal-v3.md) |

## 7. 接手时的最短流程

```text
读 vibe-coding-workflow.md（跨端规则）
  → 读本文件
  → git status / git diff
  → docker compose up -d
  → pytest -q
  → 按 §5 P0 继续：Render 跨账号验证 → 提交
```

## 8. 当前明确未完成

- Render：登录拦截已验证；Free 计划无 Shell，跨账号隔离和 MCP 权限尚未用云端测试账号验证；本地等价验证已完成。
- 没有企业 SSO、组织/部门权限和管理员后台。
- 生产 schema 迁移尚未切换到 Alembic。
- 前端清空历史没有二次确认。
- 尚未完成独立裁判模型交叉复核。
