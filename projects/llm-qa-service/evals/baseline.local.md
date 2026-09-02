# RAG Evaluation Baseline

- 生成时间（UTC）：2026-09-01T14:53:13.072051+00:00
- 数据集：`evals/rag_eval_dataset.jsonl`
- 语料：`sample_data/employee-handbook.md`
- Embedding：`local`
- 检索 top_k：4

## Retrieval metrics

| Metric | Result |
|---|---:|
| Answerable cases | 29 |
| Unanswerable cases | 2 |
| Evidence Hit@1 | 93.1% |
| Evidence Hit@3 | 96.5% |
| Evidence Hit@4 | 96.5% |
| MRR | 0.9483 |
| Mean latency | 6.41 ms |
| P95 latency | 10.73 ms |

## Generation and citation metrics

未执行。使用真实 `LLM_API_KEY` 后加 `--with-generation`，才会测回答关键词、引用与拒答。

## Retrieval cases requiring review

| ID | Category | Evidence rank | Question |
|---|---|---:|---|
| travel-tier2-hotel | travel | miss | 二线城市的酒店报销上限是多少？ |
| resignation-unused-leave | offboarding | 2 | 离职时没休完的年假怎么处理？ |

## Interpretation

- 检索指标以人工标注的证据短语为准；它衡量的是正确片段是否被召回，而不是文风。
- 默认评测不调用 LLM，适合 CI 和模型/检索参数变更前后的可重复比较。
- 回答质量和引用指标只在真实 LLM 模式下有效；mock 模式的占位回复不会计入。
