# RAG / LLM Evaluation

这套评测把「功能能跑」和「回答质量可量化」分开：默认运行确定性的 `hybrid` 检索评测，真实 LLM 可用时再加回答与引用检查。

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

`expected_evidence` 用于衡量检索是否找到了人工标注的依据；`expected_answer_keywords` 只在真实 LLM 生成模式下衡量回答是否包含关键事实。不可回答问题没有文档或证据标注，生成模式会检查模型是否明确拒答。

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
| No-answer refusal rate | 对知识库没有答案的问题，模型是否明确说明未找到资料 |

当前基线不把纯关键词指标误称为“语义正确率”。后续若接入 Ragas 或 LLM-as-a-judge，应继续复用这个已版本化的数据集，并把模型、提示词、温度、评审提示词一起记录下来，避免不可比较的分数。

当前 in-process BM25 适合中小型知识库和本项目的零额外服务部署。数据规模明显增大时，应将词法索引迁移到带中文分析器的 OpenSearch / Elasticsearch 等专用检索服务，继续保留同一套评测集作为迁移验收标准。
