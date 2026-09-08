# RAG Evaluation Baseline

- 生成时间（UTC）：2026-09-02T15:02:28.269903+00:00
- 数据集：`evals/rag_eval_dataset.jsonl`
- 语料：`sample_data/employee-handbook.md`
- Embedding：`local`
- 检索模式：`hybrid`
- 检索 top_k：4

## Retrieval metrics

| Metric | Result |
|---|---:|
| Answerable cases | 29 |
| Unanswerable cases | 2 |
| Evidence Hit@1 | 100.0% |
| Evidence Hit@3 | 100.0% |
| Evidence Hit@4 | 100.0% |
| MRR | 1.0000 |
| Mean latency | 10.23 ms |
| P95 latency | 24.70 ms |

## Generation and citation metrics

- 生成模型：`deepseek-chat`
- 生成 temperature：0.0

| Metric | Result |
|---|---:|
| Answer keyword recall | 100.0% |
| All answer keywords present | 100.0% |
| Citation format present | 100.0% |
| Citation index valid | 100.0% |
| Citation supports expected evidence | 100.0% |
| Unanswerable source-grounded refusal rate | 100.0% |
| Mean generation latency | 2066.92 ms |
| P95 generation latency | 2843.69 ms |

## LLM-as-a-judge metrics

- 裁判模型：`deepseek-chat`
- 裁判 temperature：0.0
- 裁判提示词版本：`rag-faithfulness-v1`

| Metric | Result |
|---|---:|
| Judge JSON parse success | 100.0% (31/31) |
| Judge faithfulness | 100.0% (scored 31) |
| Judge answer correctness | 100.0% (scored 29) |
| Judge unanswerable refusal appropriate | 100.0% (scored 2) |
| Mean judge latency | 2141.50 ms |
| P95 judge latency | 2400.23 ms |

## Generation cases requiring review（具体失败回答）

所有生成样本均未触发当前的自动复核规则。

## Retrieval cases requiring review

所有可回答样本都在第一名命中标注证据。

## Interpretation

- 检索指标以人工标注的证据短语为准；它衡量的是正确片段是否被召回，而不是文风。
- 默认评测不调用 LLM，适合 CI 和模型/检索参数变更前后的可重复比较。
- 回答质量和引用指标只在真实 LLM 模式下有效；mock 模式的占位回复不会计入。
- LLM 裁判是辅助信号：先检查 JSON parse success，再只比较相同数据集、候选模型、裁判模型、temperature 与提示词版本的运行结果。
