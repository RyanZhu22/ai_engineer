# Day 2 - Vector Search (Embeddings)

目标：完成一个最小可用的“向量检索”流程（真实 embedding）。

## 你将学到
- 文档切分 -> 向量化（embedding） -> 检索 Top‑K
- 用脚本完成一个小型向量检索系统

## Setup

```bash
cd day2
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## Run

```bash
python vector_search.py --query "RAG 的流程是什么"
```

```bash
python vector_search.py --query "FastAPI 怎么跑" --top_k 2

## Model

默认使用 `sentence-transformers/all-MiniLM-L6-v2`，第一次运行会自动下载模型。
你也可以通过 `--model` 指定其他模型。
```

## 目录结构

- `data/docs/` 放你的文档（.txt）
- `vector_search.py` 向量检索脚本

## 说明

当前使用 `sentence-transformers` 的真实 embedding，流程与生产系统一致。
后续可替换为 API embedding，检索逻辑不变。
