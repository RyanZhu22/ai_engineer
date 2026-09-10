# 项目当前状态与交接

> 这是跨终端继续开发时的首个阅读入口。先看本文件，再按“文件入口”和“下一步”继续工作。
> 跨端开工/收尾规则、长任务规范见 [`vibe-coding-workflow.md`](vibe-coding-workflow.md)。
>
> 最近更新：2026-09-10（HNSW 基准进行中）

## 1. 项目位置

| 项目 | 路径 |
|---|---|
| 工作区 | `/Users/ryan/developer/career_study/ai_engineer` |
| 服务项目 | `/Users/ryan/developer/career_study/ai_engineer/projects/llm-qa-service` |
| 当前分支 | `main` |
| 最近已提交版本 | `78f337d feat: password login and per-account resource isolation` |
| 远端状态 | 本地 `main` 领先 `origin/main` 1 个提交（**78f337d 尚未推送**） |

在新终端快速定位：

```bash
cd /Users/ryan/developer/career_study/ai_engineer
sed -n '1,260p' docs/project-status.md
git status --short
cd projects/llm-qa-service
```

## 2. 当前工作区状态

P0-1“登录与账号级资源隔离”已提交为 `78f337d`，**尚未推送、Render 尚未重新部署**。

当前未提交改动是 **P1：pgvector HNSW 向量索引 + 检索基准**，代码已完成，基准只跑通 mock：

- 代码：`app/config.py`（`rag_hnsw_*` 参数）、`app/db.py`（HNSW 索引 + 会话级 GUC + `pool_pre_ping` + 建/删/查索引）、`app/rag.py`（`vector_candidates`、`apply_hnsw_search_settings`、`ef_search` 参数）、`app/main.py`（`/documents/search` 支持 `ef_search` 覆盖并回显）
- 新脚本（untracked）：`evals/bench_retrieval.py` —— 精确扫描 vs HNSW 的延迟 / 召回 / 过滤基准
- mock 报告：`/tmp/bench-mock.md`（未入库）
- 本次文档同步：`docs/project-status.md`、`docs/vibe-coding-workflow.md`、`progress.md`、`projects/llm-qa-service/evals/README.md`

尚未完成：真实 bge 基准报告（`evals/retrieval-bench.md`）、HNSW 单测、提交。

⚠️ 2026-09-10 22:48 的本地 bge 运行因内存颠簸中止：8GB 机器上 Docker VM 占 4GB + swap 已用 6GB+，约 10 分钟才写入 256/2000 条切片。当时那条 `| tail -25` 命令还把输出全缓冲，看起来像死锁（实际在用 ONNX 推理）。重跑方式与防坑见 §4/§5 和 `vibe-coding-workflow.md` §3。数据库残留 512 条 `__bench_retrieval__` 切片，重跑时会自动清理。

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
- pgvector HNSW 索引 + `ef_search` / `iterative_scan` 参数（代码已完成，基准未跑通，未提交）
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
| 自动化测试 | `54 passed in 5.13s`（P0-1 提交时；HNSW 改动后尚未复跑） |
| 工作区格式检查 | `git diff --check` 通过（HNSW 改动后待复跑） |
| mock + hybrid RAG | Hit@1 96.5%，Hit@3 100%，Hit@4 100%，MRR 0.9828 |
| local bge + hybrid RAG | Hit@1/3/4 100%，MRR 1.0000 |
| DeepSeek live + judge | 31/31 JSON 可解析；本次候选与裁判使用同一模型 |
| PostgreSQL | Docker Compose 中 `llm-qa-pg` healthy |
| mock HNSW 基准 | 20005 切片：精确 P95 70.3ms → HNSW 2.55ms（27.6×），建索引 1.71s；mock 向量下 Recall@10 0.49–0.72，只验证机制 |
| local bge HNSW 基准 | ❌ 未完成：22:48 运行因本机内存颠簸中止（约 10 分钟/256 条切片） |

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
  --sizes 2000 --queries 15 --passes 1 --embedding-provider local \
  --output evals/retrieval-bench.md > /tmp/bench.log 2>&1 &
tail -f /tmp/bench.log
```

## 5. 下一步优先级

### P0：收尾 HNSW 基准（当前任务）

1. 释放内存后重跑本地 bge 基准（命令见 §4），产出 `evals/retrieval-bench.md`。
2. 给 HNSW 代码补单测：索引 DDL 参数、`ef_search` 边界校验、`vector_candidates` 的文档过滤。
3. 跑全量 pytest + `git diff --check`，提交代码、基准脚本、报告和文档。

### P1：P0-1 上线 + 生产化缺口

1. 推送 `78f337d`（**只有用户明确要求时才推送**），重新部署 Render，验证登录、跨账号隔离和 MCP 权限。
2. 用 Alembic 管理 `users`、`login_sessions`、`owner_id`、HNSW 索引等 schema 迁移，替代生产环境依赖 `create_all`。
3. 增加前端“清空历史”二次确认。
4. 增加登录和高成本 LLM 接口的限流、审计日志和基础可观测性。
5. 增加备份/恢复演练与 token/session 清理策略。

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
| 最近的评测报告 | [`baseline.md`](../projects/llm-qa-service/evals/baseline.md)、[`latest-live-judge-report.refusal-v3.md`](../projects/llm-qa-service/evals/latest-live-judge-report.refusal-v3.md) |

## 7. 接手时的最短流程

```text
读 vibe-coding-workflow.md（跨端规则）
  → 读本文件
  → git status / git diff
  → docker compose up -d
  → pytest -q
  → 按 §5 P0 继续：重跑 bge 基准 → 补测试 → 提交
  → 按需推送并重新部署 Render
```

## 8. 当前明确未完成

- HNSW：真实 bge 基准报告未产出，代码无单测、未提交。
- P0-1（`78f337d`）未推送、Render 未重新部署验证。
- 没有企业 SSO、组织/部门权限和管理员后台。
- 生产 schema 迁移尚未切换到 Alembic。
- 前端清空历史没有二次确认。
- 尚未完成独立裁判模型交叉复核。

