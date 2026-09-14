# ⚡ 跨端 Vibe Coding 工作流

> 目的：在任意一台机器 / 任意一个终端（本机 pi、远端 pi、Codex、Claude Code…）打开本项目，都能几分钟内接上进度继续干活，并且不会覆盖另一端正在做的事。
>
> 适用场景：人 + AI Agent 并行开发。**跨端只认仓库里的文件，不认聊天记录**——pi 的 session 存在 `~/.pi/agent/sessions/`，不随 git 同步，换端就没了。

---

## 0. 唯一事实来源

| 信息 | 文件 | 什么时候更新 |
|---|---|---|
| 当前工作区、验证结果、下一步 | [`project-status.md`](project-status.md) | **每次会话收尾前（必须）** |
| 每日进度、里程碑、面试题 | [`../progress.md`](../progress.md) | 有交付或进展时 |
| 技术决策、踩坑、面试讲法 | [`technical-notes.md`](technical-notes.md) | 学到新东西时 |
| 服务启动 / API / 部署 | [`../projects/llm-qa-service/README.md`](../projects/llm-qa-service/README.md) | 用法变化时 |
| 评测命令与指标 | [`../projects/llm-qa-service/evals/README.md`](../projects/llm-qa-service/evals/README.md) | 评测资产变化时 |

铁律：**文档不更新 = 进度丢失**。宁可花 5 分钟写清状态，也不要让下一个端去猜。

---

## 1. 开工：新端 3 分钟自检

```bash
cd <repo 根目录>                      # 机器间路径可能不同，下面命令都以仓库根为基准
git fetch --prune
git status --short && git log --oneline -5 && git branch -vv
sed -n '1,220p' docs/project-status.md   # 先读交接文件
```

判断规则：

- **有未提交改动** → 另一端可能正在改：先读 `git diff`，**不要** `reset` / `checkout` / `clean` 覆盖，直接问用户这些改动归谁。
- `main` 落后 origin → `git pull --ff-only`；领先 origin → 确认是否该 push（默认**不 push**，见 §4）。
- 有其他端正在跑长任务（§3）→ 本轮只做不冲突的读操作或另一个模块。
- 看 `docs/project-status.md` §2 的“当前工作区状态”和 §5 的“下一步优先级”，从那里接着干。

## 2. 环境自检（新机器第一次）

```bash
cd projects/llm-qa-service
docker compose up -d                     # PostgreSQL 16 + pgvector
.venv/bin/python -m pytest -q            # 应全绿（截至 2026-09-13：58 passed）
```

要点：

- `.env` 已 gitignore：从 `.env.example` 复制，LLM key 自己配；`EMBEDDING_PROVIDER=local` 无需 key。
- `.venv` 已 gitignore：没有就按 `projects/llm-qa-service/README.md` 的快速开始重建。
- 首次 `local` embedding 会下载 `BAAI/bge-small-zh-v1.5`（约 90MB）到 HF 缓存；离线环境可 `HF_HUB_OFFLINE=1`。
- 本机（8GB RAM）Docker VM 固定占 4GB：开跑前先 `docker stats --no-stream`，用不到的容器按 §3.3 停掉。

## 3. 长任务：三条铁律（都是实际踩过的坑）

### 3.1 输出必须落盘，禁止用 `| tail` 包长任务

```bash
# ❌ 管道全缓冲：进程退出前终端什么都看不到，看起来像永久卡死
.venv/bin/python -m evals.bench_retrieval ... | tail -25

# ✅ 后台 + 日志 + PID
mkdir -p /tmp/bench
nohup .venv/bin/python -u -m evals.bench_retrieval ... \
  > /tmp/bench/run.log 2>&1 &
echo $! > /tmp/bench/run.pid
tail -f /tmp/bench/run.log
```

- `-u` 关闭 Python 输出缓冲；日志放 `/tmp`（`nohup.out` 也已加入 .gitignore）。
- `--output` 报告只在**成功结束**时才写文件：不要用它是否出现判断进度，看日志或数据库行数。
- 超过几分钟的任务，一律按上面的模板起，不要在前台等。

### 3.2 进度必须可观察

起任务前先想好“怎么知道它在动”，例如：

- 日志里每批一行打印（必要时给脚本加进度输出）；
- `ps -o pid,stat,time,%cpu,rss -p $(cat /tmp/bench/run.pid)` 看 CPU 时间是否在涨；
- 数据库行数（如 `select count(*) from chunks ... source='__bench_retrieval__'`）；
- 观察 `top -l 1 -pid <pid> -stats pid,cpu,state,mem`：`stuck`（U 状态）+ CPU 忽高忽低 = 内存颠簸，不是死锁。

### 3.3 资源护栏（8GB 机器）

- embedding 基准 / 大评测 / HNSW 建索引前，停掉不用的容器：
  `docker stop kimi-k8s-control-plane cicd-demo-platform-jenkins-1 northstar-mysql cicd-demo-platform-docker-1`（都是别的项目，按需停）。
- 内存压力信号：`sysctl vm.swapusage` 接近用满、`kern.memorystatus_vm_pressure_level=2`、进程 RSS 抖动。
- 本地 embedding 先小规模冒烟（`--sizes 2000 --passes 1`）量吞吐，确认后再放大；批量不要超过 256。
- 不同时跑多个重任务（bench + pytest + 真实 LLM 评测）。

### 3.4 收工处理

- 结束或放弃任务：`kill $(cat /tmp/bench/run.pid)`，确认 `ps aux | grep bench_retrieval` 为空。
- 把「跑完了什么 / 中止了什么 / 产出在哪 / 数据是否残留」写进 `docs/project-status.md`，残留数据写明清理命令。

## 4. 收尾：离开一个端之前（5 分钟清单）

1. `git status --short && git diff --stat` —— 得到准确的改动清单。
2. 更新 [`project-status.md`](project-status.md) 三处：
   - §2 当前工作区状态（哪些文件、什么状态、哪组改动属于哪个任务）
   - §4 最近验证结果（跑了什么、数字多少、没跑什么）
   - §5 下一步优先级（下一个端从哪一步开始）
3. 后台任务：写清 PID / 日志路径，或直接杀掉；**不留无主的 python 进程**。
4. 提交：小步、可读，前缀用 `feat:` / `fix:` / `docs:` / `test:` / `chore:`。
   - **push 和 Render 部署默认要用户明确同意**。
   - 未提交的改动就是交接状态的一部分，如实写进文档。
5. 禁用手法：`git reset --hard`、`git checkout -- <file>`、`git clean -fd`——会静默吞掉另一端的改动。

## 5. 多端并行规则

- 同一时间只让一个端**写代码/写文件**；另一端只读、跑测试或写不相交的文档。
- 需要并行就分文件或开分支：`git switch -c feat/xxx`，并在 `project-status.md` §2 声明“本端占用哪些文件”。
- 合并前先 `git fetch && git log --oneline main..origin/main`；有冲突保留双方意图，拿不准就问用户。
- 文档是同步通道：每个端收尾都更新 §2/§5，冲突和“接不上”自然就少。

## 6. 常见坑速查

| 症状 | 真实原因 | 处理 |
|---|---|---|
| 命令跑很久没有任何输出 | `\| tail` 管道缓冲；报告最后才写 | §3.1 后台 + 日志 |
| 进程 CPU 低、状态 `U`、DB 行数不动 | 内存颠簸 / swap | §3.3 停容器、缩小规模 |
| 本地 embedding 比预期慢很多 | 文本长、batch 大、内存压力 | 先小规模测吞吐，别拿短文本的测速外推 |
| CI 能过、本地不过（或反之） | `.env`、pgvector 扩展、模型缓存差异 | `docker compose up -d` + 跑 evals 的确定性命令 |
| 改了 config 不生效 | `get_settings()` 有 lru_cache | 重启进程（测试里 `cache_clear()`） |
| benchmark / eval 数据混进知识库 | 用 `__bench_retrieval__` / `__eval__` 前缀隔离 | 脚本正常结束会自清理；异常退出看 project-status |
| 换端后 AI 不知道干到哪了 | 聊天记录不同步 | 读 `project-status.md`；收尾必须更新它 |

## 7. 新端接手最短路径

```text
读本文件（§1 自检 → §3 长任务规则 → §4 收尾规则）
  → 读 docs/project-status.md
  → git status / git diff --stat
  → docker compose up -d && pytest -q
  → 按 §5 P0 继续
  → 收尾：更新 project-status.md + 处理后台进程 + 提交
```
