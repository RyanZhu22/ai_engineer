# 向量检索基准：精确扫描 vs pgvector HNSW

| 项 | 值 |
|---|---|
| 切片规模 | 2005 |
| 查询数 | 15（来自 `evals/rag_eval_dataset.jsonl`） |
| embedding | `local`（维度 512） |
| embedding batch size | 32 |
| 索引参数 | m=16, ef_construction=64 |
| pgvector | 0.8+（`hnsw.iterative_scan` 需要 0.8.0） |

> 延迟只统计数据库检索（查询向量预先算好，不含 embedding 推理）。
> 每个配置跑 1 轮、取每查询最小值再算分位数：本机 Docker VM 有其他容器
> 抢 CPU，单次采样会被 10ms 级噪声污染。噪声只会让结果偏慢，不会偏快。

## 1. 规模扩展：精确扫描 O(N) vs HNSW（ef_search=100）

| 切片数 | 精确 P50 (ms) | 精确 P95 (ms) | HNSW P50 (ms) | HNSW P95 (ms) | P95 加速 | Recall@10 | 建索引 (s) |
|---|---|---|---|---|---|---|---|
| 2005 | 8.31 | 9.88 | 7.41 | 9.07 | 1.1× | 1.000 | 0.32 |

规模每 ×10，精确扫描延迟随之线性增长（全表顺序扫描 + 排序），HNSW 基本持平：
索引查询代价主要跟图和候选队列有关，不随表大小线性增长。

## 2. ef_search 曲线（规模 2005，Recall@10）

| ef_search | Recall@10 | P50 (ms) | P95 (ms) | min (ms) |
|---|---|---|---|---|
| 10 | 0.624 | 2.46 | 3.86 | 2.26 |
| 40 | 1.000 | 7.88 | 9.12 | 7.07 |
| 100 | 1.000 | 7.41 | 9.07 | 6.9 |
| 200 | 1.000 | 7.65 | 8.81 | 6.97 |

## 3. 带过滤检索（模拟 owner / 权限过滤，ef_search=100）

可见切片 100/2005；精确扫描基线 P50=2.88ms

| iterative_scan | Recall@10 | 平均返回 | P50 (ms) | P95 (ms) |
|---|---|---|---|---|
| off | 1.000 | 10.0/10 | 2.33 | 3.48 |
| relaxed_order | 1.000 | 10.0/10 | 2.46 | 3.1 |

过滤性强时 HNSW 只取 `ef_search` 个候选再应用 WHERE，候选不足会让返回条数和召回
一起下降；`hnsw.iterative_scan` 让索引继续往下扫，直到凑够 `LIMIT` 或达到
`hnsw.max_scan_tuples`。

## 复现命令

```bash
.venv/bin/python -m evals.bench_retrieval --sizes 2000 --queries 15 \
  --top-k 10 --passes 1 --embedding-provider local \
  --embedding-batch-size 32 \
  --ef-search 10,40,100,200 --filter-ratio 0.05 \
  --output evals/retrieval-bench.md
```

> Recall@K 衡量索引保真度（与精确扫描结果的一致性），不衡量语义相关性；
> 语义质量见 `evals/run_rag_eval.py` 的人工标注证据集。
