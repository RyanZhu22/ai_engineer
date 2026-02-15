# Day 4 - RAG 评测与迭代基线

Day3 你已经完成了“可运行系统”。  
Day4 的重点是：把系统变成“可评估、可迭代”的工程闭环。

## 目标

1. 用固定数据集跑自动评测（检索命中 + 问答来源命中）
2. 记录基线指标（作为后续优化对照）
3. 人工补评分（回答正确性、引用可靠性）

## 文件说明

- `eval_dataset.csv`：10 条评测问题模板
- `run_eval.py`：自动调用 Day3 API 并生成评测结果
- `requirements.txt`：Day4 脚本依赖
- `results/`：每次评测结果输出目录（自动创建）

## 先决条件

1. Day3 服务已经启动：
```bash
uvicorn app.main:app --host 127.0.0.1 --port 8001
```

2. Day3 的 `provider` 是你希望评估的模式（`deepseek` 或 `ollama`）。

## 快速开始

在 `day4` 目录执行：

```bash
cd day4
python -m pip install -r requirements.txt
python run_eval.py --base_url http://127.0.0.1:8001 --top_k 3
```

运行后会输出 summary，并在 `results/` 生成：

```text
results/eval_results_YYYYMMDD_HHMMSS.csv
```

## 自动指标定义

1. `search_hit@k`
- 定义：`/search` 返回的 top-k 文档中是否包含 `expected_doc`
- 用途：衡量检索召回质量

2. `ask_source_hit@k`
- 定义：`/ask` 返回 `sources` 中是否包含 `expected_doc`
- 用途：衡量问答链路中的来源命中质量

3. `avg_keyword_recall`
- 定义：答案中命中 `expected_keywords` 的比例均值
- 用途：粗粒度检查答案是否覆盖关键概念

## 人工评分标准（建议）

在结果 CSV 中有三列留给你手工打分：

- `manual_answer_score_0_2`
- `manual_source_score_0_2`
- `manual_notes`

推荐打分规则：

1. `manual_answer_score_0_2`
- 0：答非所问或明显错误
- 1：部分正确，但不完整或有歧义
- 2：正确、完整、表达清晰

2. `manual_source_score_0_2`
- 0：来源无关或缺失
- 1：来源部分相关
- 2：来源高度相关且可支撑结论

## 数据集字段说明（`eval_dataset.csv`）

- `id`：题目编号
- `query`：评测问题
- `expected_doc`：期望命中文档
- `expected_keywords`：答案应覆盖关键词（`;` 分隔）
- `notes`：题目备注

你可以继续扩展到 30-50 题，评测会更稳定。

## 常用命令

1. 只评估检索，不调用 `/ask`：
```bash
python run_eval.py --skip_ask
```

2. 指定不同数据集：
```bash
python run_eval.py --dataset my_eval_set.csv
```

3. 指定输出目录：
```bash
python run_eval.py --output_dir results_deepseek
```

## Day4 完成标准

- [ ] 至少运行一次 `run_eval.py` 并生成结果 CSV
- [ ] 记录你的基线指标（search hit@3、ask source hit@3、avg keyword recall）
- [ ] 对 10 条结果完成人工评分
- [ ] 输出一条“下一轮优化计划”（例如：改 chunk、改模型、加 rerank）

## 下一步（Day5 建议）

基于 Day4 基线做一次单变量实验：

1. 只改 embedding 模型
2. 只改 chunk 策略
3. 对比两次 CSV 指标变化

这样你会快速建立“优化动作 -> 指标变化”的工程直觉。
