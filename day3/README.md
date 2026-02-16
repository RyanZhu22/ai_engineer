# Day 3 - RAG API (Retrieval + Generation)

你当前背景是 Software Engineer，目标是 2 周内用项目驱动方式转向 AI Engineer。  
Day3 的定位是：把 Day1 的 LLM API 能力和 Day2 的向量检索能力合并成一个可调用的 RAG 服务。

## 今日目标

完成一个可运行的最小 RAG API：

1. `POST /search`：只做检索，便于调试召回质量
2. `POST /ask`：检索 + 生成，并返回引用来源
3. `GET /health`：查看服务状态、索引统计、模型配置

这一步是从“脚本能力”升级到“服务能力”的关键节点。

## 你将获得的能力

- 把离线检索流程封装成在线 API
- 理解 RAG 请求链路：Query -> Retrieve -> Prompt -> Generate -> Return sources
- 学会用“可解释输出（含来源）”降低幻觉风险
- 为后续评估、缓存、重排、A/B 测试打基础

## 项目结构

```text
day3/
├─ app/
│  ├─ config.py      # 环境变量和默认配置
│  ├─ retriever.py   # 向量检索器（加载、建索引、Top-K）
│  ├─ llm.py         # LLM provider 和 RAG prompt
│  ├─ telemetry.py   # 请求日志与指标汇总
│  └─ main.py        # FastAPI 路由（/health /search /ask /metrics/summary）
├─ data/
│  └─ docs/
│     ├─ rag_design.txt
│     ├─ prompt_strategy.txt
│     └─ ai_engineer_scope.txt
├─ .env.example
├─ requirements.txt
└─ README.md
```

## 快速开始

在 `day3` 目录中执行：

```bash
cd day3
python -m venv .venv
```

激活虚拟环境：

- Windows (PowerShell)

```powershell
.venv\Scripts\Activate.ps1
```

- macOS / Linux

```bash
source .venv/bin/activate
```

安装依赖：

```bash
python -m pip install -r requirements.txt
```

准备环境变量：

```bash
cp .env.example .env
```

Windows PowerShell 可用：

```powershell
Copy-Item .env.example .env
```

启动服务：

```bash
uvicorn app.main:app --reload --port 8001
```

## API 使用示例

### 1) 健康检查

```bash
curl -s http://127.0.0.1:8001/health
```

你将看到：
- 当前 `provider`
- 文档数 `doc_count`
- chunk 数 `chunk_count`
- 当前 embedding 模型

### 1.1) 指标汇总

```bash
curl -s http://127.0.0.1:8001/metrics/summary
```

你将看到：
- 请求总量与错误率
- 平均延迟与 P50/P95
- 各接口请求分布
- 高频 query 与高频来源文档

### 2) 只做检索（调试召回）

```bash
curl -s http://127.0.0.1:8001/search \
  -H "Content-Type: application/json" \
  -d "{\"query\":\"RAG 的核心流程是什么\",\"top_k\":3}"
```

### 3) RAG 问答（检索 + 生成）

```bash
curl -s http://127.0.0.1:8001/ask \
  -H "Content-Type: application/json" \
  -d "{\"question\":\"如何降低 RAG 幻觉？\",\"top_k\":3}"
```

返回包含：
- `answer`：模型回答
- `sources`：命中的来源片段（文档名、chunk id、相似度）

## Provider 说明

通过 `.env` 的 `LLM_PROVIDER` 切换：

- `echo`（默认）：无外部依赖，方便先验证整条链路
- `ollama`：本地模型推理
- `deepseek`：远程 API 推理

### `echo` 模式的意义

`echo` 不追求回答质量，重点是验证：
1. 检索结果是否合理  
2. Prompt 是否按预期组装  
3. API 输出结构是否可用  

你先把系统链路跑通，再切换到真实 LLM 做质量优化，效率最高。

## 关键参数

`.env` 里最重要的参数：

- `RAG_DOCS_DIR`：知识库目录
- `RAG_EMBED_MODEL`：Embedding 模型名
- `RAG_BATCH_SIZE`：向量化批大小
- `RAG_DEFAULT_TOP_K`：默认召回数量
- `RAG_SOURCE_MAX_CHARS`：返回来源文本的最大长度
- `RAG_LOG_PATH`：请求日志文件路径（jsonl）
- `RAG_METRICS_MAX_RECENT`：用于统计延迟分位数的最近样本数
- `LLM_PROVIDER`：`echo` / `ollama` / `deepseek`

## 代码学习顺序（建议）

1. `app/retriever.py`
   - 看 `build()`：如何把文档转成内存向量索引
   - 看 `search()`：为什么归一化后点积可排序
2. `app/llm.py`
   - 看 `build_rag_prompt()`：如何约束模型输出
   - 看 `generate_with_context()`：provider 分发逻辑
3. `app/main.py`
   - 看 `/search`：只检索便于调试
   - 看 `/ask`：串联检索和生成，返回 sources

## Day3 完成标准（Checklist）

- [ ] 能成功启动 `uvicorn app.main:app --reload --port 8001`
- [ ] `/health` 能返回文档与 chunk 统计
- [ ] `/search` 返回的 top_k 结果与你的问题相关
- [ ] `/ask` 返回 `answer + sources`
- [ ] 知道如何切换 `echo -> ollama/deepseek`

## 常见问题

### 1) 首次启动慢

首次会下载 embedding 模型权重，这是正常现象。后续会走本地缓存。

### 2) `No .txt documents found in docs_dir`

检查 `RAG_DOCS_DIR` 路径是否正确，以及目录下是否有 `.txt`。

### 3) `OLLAMA_MODEL is not set`

你把 `LLM_PROVIDER` 设成了 `ollama`，但没有设置 `OLLAMA_MODEL`。

### 4) `DEEPSEEK_API_KEY is not set`

你把 `LLM_PROVIDER` 设成了 `deepseek`，但未提供 API Key。

## 与你两周目标的关系

Day3 标志着你从“会调模型”升级到“能交付 AI 服务”。  
接下来你最该补的是：

1. 评估：建立 query-答案集并衡量命中率/回答准确性
2. 可观测性：记录检索命中和回答质量
3. 迭代：改 chunk 策略、加 rerank、引入缓存

这三件事做完，你就不是“会用 API 的开发”，而是具备 AI 工程闭环能力的工程师。
