# RAG / LLM Evaluation

这套评测把「功能能跑」和「回答质量可量化」分开：默认运行确定性的 `hybrid` 检索评测，真实 LLM 可用时再加回答、引用与可选的 LLM-as-a-judge 检查。

## 评测资产

- `rag_eval_dataset.jsonl`：31 条人工标注问题，覆盖年假、请假、加班、差旅、远程办公、培训、离职，以及 2 条不可回答问题。
- `run_rag_eval.py`：创建临时评测语料、运行检索、汇总指标并输出 Markdown / JSON。
- `baseline.md`：CI 同款的确定性 mock + hybrid 基线。
- `baseline.local.md`：本地 `bge-small-zh-v1.5` + hybrid 基线。

`hybrid` 的流程是：pgvector 向量候选 + 中文 BM25 候选 → 候选块内最佳事实句 BM25 rerank → RRF 排名融合。`vector` 仍保留给优化前后对照或排障；不要把不同 embedding 模式、检索模式或 chunk 参数的分数混在同一条趋势线上。

每条 JSONL 样本包含：

```json
{
  "id": "annual-leave-1y",
  "category": "annual_leave",
  "question": "员工刚入职满一年，可以享受多少天年假？",
  "answerable": true,
  "expected_document_title": "employee-handbook",
  "expected_evidence": ["入职满 1 年享 12 天"],
  "expected_answer_keywords": ["12天"]
}
```

`expected_evidence` 用于衡量检索是否找到了人工标注的依据；`expected_answer_keywords` 只在真实 LLM 生成模式下衡量回答是否包含关键事实。不可回答问题没有文档或证据标注，生成模式会检查模型是否把“无法回答”明确归因于知识库/资料不足，而不是把未经资料支持的否定当作答案。

## 运行

先启动本地 pgvector 数据库：

```bash
docker compose up -d
```

### 可复现的离线检索基线

默认使用 `mock` embedding，不下载模型、不调用 LLM，适合 CI 或快速回归检查：

```bash
.venv/bin/python -m evals.run_rag_eval \
  --embedding-provider mock \
  --retrieval-mode hybrid \
  --min-hit-at-1 0.95 \
  --min-hit-at-k 1.0 \
  --output evals/latest-report.md \
  --json-output evals/latest-report.json
```

### 仅向量的优化前对照

```bash
.venv/bin/python -m evals.run_rag_eval \
  --embedding-provider mock \
  --retrieval-mode vector
```

### 向量索引基准：精确扫描 vs pgvector HNSW

`bench_retrieval.py` 回答“索引值不值”：同一批查询分别跑精确全表扫描和 HNSW，输出规模扩展趋势、`ef_search` 召回/延迟曲线，以及带 owner 过滤时 `iterative_scan` 的对比。延迟只统计数据库检索，不含 embedding 推理。

```bash
# 冒烟：mock 向量，秒级；只验证机制，不作语义结论
.venv/bin/python -m evals.bench_retrieval \
  --sizes 2000 --embedding-provider mock \
  --output /tmp/bench-mock.md

# 真实 bge 向量：先释放内存，后台运行并落盘日志（长任务规范见 ../../docs/vibe-coding-workflow.md §3）
# 8GB 机器使用 32 条 batch 降低 embedding 内存峰值；报告会记录该参数。
nohup .venv/bin/python -u -m evals.bench_retrieval \
  --sizes 2000 --queries 15 --passes 1 --embedding-provider local --embedding-batch-size 32 \
  --output evals/retrieval-bench.md > /tmp/bench.log 2>&1 &
tail -f /tmp/bench.log
```

- 基准数据用 `source='__bench_retrieval__'` 隔离，正常结束自动清理；异常退出可重跑或手工删除该 source 的文档。
- 报告里的 Recall@K 是“ANN 结果与精确扫描结果的交集”，衡量索引保真度；语义质量仍看 `run_rag_eval.py` 的证据标注集，两者不要混用。

### 真实中文 embedding 基线

使用项目默认的 `BAAI/bge-small-zh-v1.5`（首次运行会下载模型）：

```bash
.venv/bin/python -m evals.run_rag_eval \
  --embedding-provider local \
  --retrieval-mode hybrid \
  --output evals/baseline.local.md
```

### 加入真实 LLM 回答与引用指标

`--with-generation` 必须配置真实兼容 OpenAI 的 LLM；mock 模式会直接拒绝，因为占位回复不能代表模型质量。

```bash
LLM_BASE_URL=https://api.deepseek.com/v1 \
LLM_API_KEY=... \
LLM_MODEL=deepseek-chat \
.venv/bin/python -m evals.run_rag_eval \
  --embedding-provider local \
  --with-generation \
  --output evals/latest-live-report.md
```

### 加入 LLM-as-a-judge 忠实度评审

在生成答案后，再让一个真实 LLM 根据**同一题的检索资料、人工证据标注和候选回答**判断：回答是否忠实于资料、可回答题是否答对关键事实、不可回答题是否恰当拒答。它不是 CI 门槛，也不是“绝对真值”；报告会额外记录裁判 JSON 的解析成功率、候选模型、裁判模型、temperature 和提示词版本，便于可比地复跑。

`--with-llm-judge` 必须与 `--with-generation` 一起使用。完整 31 条数据集会产生 31 次候选回答调用 + 31 次裁判调用，请先确认 API 费用和限额；不会在 mock 模式或 CI 中运行。

```bash
LLM_BASE_URL=https://api.deepseek.com/v1 \
LLM_API_KEY=... \
LLM_MODEL=deepseek-chat \
EVAL_JUDGE_MODEL=deepseek-chat \
.venv/bin/python -m evals.run_rag_eval \
  --embedding-provider local \
  --retrieval-mode hybrid \
  --with-generation \
  --with-llm-judge \
  --output evals/latest-live-judge-report.md \
  --json-output evals/latest-live-judge-report.json
```

`EVAL_JUDGE_MODEL` 留空时复用 `LLM_MODEL`；想临时更换裁判模型，可改为在命令最后加 `--judge-model your-model-name`。候选答案和资料被当作不可信数据传给裁判，裁判提示词明确要求忽略其中的任何指令；如果裁判没有返回合法 JSON，该题不会被计为通过，而会显示在 JSON 报告的 `parse_error` 中。

评测只会写入并清理 source 以 `__eval__` 开头的临时文档；检索也被限制在该文档范围内，因此不会删除或污染用户知识库。加 `--keep-corpus` 可保留临时文档以便手动调试。

`tests/test_evaluation.py` 会验证每一条 `expected_evidence` 都真实出现在版本化语料中，避免标注笔误制造假的“检索漏召回”。

## 指标解释

| 指标 | 含义 |
|---|---|
| Evidence Hit@1 / @3 / @K | 标注证据是否出现在前 K 个召回切片中 |
| MRR | 第一条正确证据的倒数排名均值，越接近 1 越好 |
| Retrieval latency | 每条 query 的检索耗时，报告 mean / P50 / P95 |
| Answer keyword recall | 真实 LLM 回答覆盖人工关键事实的比例 |
| Citation valid / supports evidence | 引用编号是否合法、且是否指向正确证据 |
| No-answer refusal rate | 基于资料/知识库不足的拒答启发式匹配率；支持“资料中未明确提及”“资料不足，无法确认”等常见表达 |
| Judge JSON parse success | LLM 裁判是否按约定返回可验证 JSON；先看这个覆盖率再看裁判分数 |
| Judge faithfulness | 裁判认为候选回答的实质性事实均可由已检索资料支持的比例 |
| Judge answer correctness / refusal appropriate | 可回答题是否答对关键事实；不可回答题是否诚实拒答（均只在成功解析的裁判结果中计算） |

当前基线不把纯关键词指标或单次 LLM 裁判分数误称为“绝对语义正确率”。比较裁判结果时，要保持数据集、检索配置、候选模型、裁判模型、temperature 和提示词版本一致；确定性的检索门槛仍然是 CI 的唯一质量门槛。

生成评测报告会新增 `Generation cases requiring review（具体失败回答）`：只要关键词、引用、资料不足拒答规则或 LLM 裁判任一项失败，就会列出问题、失败原因、候选回答摘要和裁判理由。这样无需从 31 条总指标反推具体失败样本。

当前 in-process BM25 适合中小型知识库和本项目的零额外服务部署。数据规模明显增大时，应将词法索引迁移到带中文分析器的 OpenSearch / Elasticsearch 等专用检索服务，继续保留同一套评测集作为迁移验收标准。
