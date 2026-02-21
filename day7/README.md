# Day 7 - Prompt 与回答质量 A/B 实验

你当前优先目标是“核心 AI Engineer 能力”，所以 Day7 聚焦在：
- Prompt 设计迭代
- 结构化输出约束
- 引用合规评测

## 今日目标

1. 对比 `prompt_style=v1` 与 `prompt_style=v2`
2. 评估回答结构是否稳定（format compliance）
3. 评估引用是否可追溯（citation compliance）
4. 结合关键词覆盖率做最终决策

## 前置条件

1. Day3 服务运行在 `http://127.0.0.1:8001`
2. Day4 题库可用：`day4/eval_dataset.csv`

## Step 1: 启动 Day3

```bash
cd day3
uvicorn app.main:app --host 127.0.0.1 --port 8001
```

## Step 2: 跑 baseline（v1）

```bash
cd day7
python -m pip install -r requirements.txt
python run_quality_eval.py \
  --base_url http://127.0.0.1:8001 \
  --dataset ../day4/eval_dataset.csv \
  --top_k 3 \
  --prompt_style v1 \
  --tag baseline
```

## Step 3: 跑 candidate（v2）

```bash
python run_quality_eval.py \
  --base_url http://127.0.0.1:8001 \
  --dataset ../day4/eval_dataset.csv \
  --top_k 3 \
  --prompt_style v2 \
  --tag candidate
```

## Step 4: 生成对比报告

将上一步输出的两个 summary json 路径填入：

```bash
python compare_quality_reports.py \
  --baseline reports/quality_summary_v1_baseline_XXXX.json \
  --candidate reports/quality_summary_v2_candidate_XXXX.json \
  --output reports/quality_comparison.md
```

## 关键指标解释

1. `format_ok_rate`
- 回答是否满足结构化字段（`answer/confidence/citations/grounded`）

2. `citation_compliance_rate`
- `citations` 是否都能在 `sources` 中找到对应标签

3. `expected_doc_cited_rate`
- 是否引用了题目期望文档（弱监督）

4. `avg_keyword_recall`
- 回答对目标关键词的覆盖比例

## 决策标准（建议）

1. `http_success_rate` 不下降
2. `format_ok_rate` 与 `citation_compliance_rate` 不下降
3. `avg_keyword_recall` 提升或至少不退化

满足以上条件，保留 `v2`。

## Day7 完成标准

- [ ] 生成 `quality_summary_v1_*.json`
- [ ] 生成 `quality_summary_v2_*.json`
- [ ] 生成 `quality_comparison.md`
- [ ] 用 `analysis_template.md` 写出结论
