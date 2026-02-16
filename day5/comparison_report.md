# Day5 Experiment Comparison Report

- Baseline: `..\day4\results\eval_results_20260216_172112.csv`
- Candidate: `..\day4\results\eval_results_20260216_172232.csv`

## Metrics

| Metric | Baseline | Candidate | Delta |
|---|---:|---:|---:|
| Search hit@k | 100.0% | 100.0% | +0.0% |
| Ask source hit@k | 100.0% | 100.0% | +0.0% |
| Avg keyword recall | 86.7% | 81.7% | -5.0% |

## Per-question Delta (keyword_recall)

- Improved: 0
- Regressed: 1
- Unchanged: 9

### Improved

None

### Regressed

| id | query | baseline | candidate | delta |
|---:|---|---:|---:|---:|
| 5 | 为什么固定输出结构能降低系统复杂度 | 1.000 | 0.500 | -0.500 |

### Unchanged

| id | query | baseline | candidate | delta |
|---:|---|---:|---:|---:|
| 1 | RAG 的核心流程是什么 | 0.667 | 0.667 | +0.000 |
| 2 | 为什么先做召回再优化提示词 | 1.000 | 1.000 | +0.000 |
| 3 | 如何在 RAG 中设计提示词约束 | 1.000 | 1.000 | +0.000 |
| 4 | 一个可靠 Prompt 模板通常包含什么 | 1.000 | 1.000 | +0.000 |
| 6 | AI Engineer 的核心能力分层有哪些 | 1.000 | 1.000 | +0.000 |
| 7 | 两周学习策略建议是什么 | 1.000 | 1.000 | +0.000 |
| 8 | 为什么模型强也会出现幻觉 | 1.000 | 1.000 | +0.000 |
| 9 | 从软件工程师转 AI 工程师应优先补什么 | 1.000 | 1.000 | +0.000 |
| 10 | RAG 场景下如何降低模型自由度 | 0.000 | 0.000 | +0.000 |

## Recommendation

- If `avg_keyword_recall` improved and regressions are limited, keep this change.
- Review regressed questions and inspect chunk/source differences before finalizing.
- Continue with one-variable-at-a-time experiments for reliable iteration.
