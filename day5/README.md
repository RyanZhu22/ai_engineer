# Day 5 - 单变量实验与结果对比

Day4 你已经得到基线。  
Day5 目标是做一次“单变量优化实验”，并用对比报告做工程决策。

## 今日目标

1. 只改一个变量（例如 embedding 模型）
2. 复跑 Day4 评测，得到 candidate 结果
3. 自动对比 baseline vs candidate
4. 写出保留/回滚结论

## 建议实验变量（优先级最高）

优先改 embedding 模型（单变量）：

```env
RAG_EMBED_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
```

说明：你的问题主要是中文，这个多语种模型通常会对中文检索更友好。

## 操作步骤

### 1) 记录 baseline 文件

你当前 baseline 可用：

`day4/results/eval_results_20260216_172232.csv`

### 2) 修改 Day3 配置并重启服务

在 `day3/.env` 中只改一项 `RAG_EMBED_MODEL`，其他保持不变。  
重启 Day3：

```bash
cd day3
uvicorn app.main:app --host 127.0.0.1 --port 8001
```

### 3) 复跑 Day4，得到 candidate

```bash
cd day4
python run_eval.py --base_url http://127.0.0.1:8001 --top_k 3
```

### 4) 运行 Day5 对比报告

```bash
cd day5
python compare_eval.py \
  --baseline ..\day4\results\eval_results_20260216_172232.csv \
  --candidate ..\day4\results\你的新文件.csv \
  --output comparison_report.md
```

输出文件：

- `day5/comparison_report.md`

### 5) 做结论记录

用 `day5/analysis_template.md` 填写：
- 是否保留该改动
- 回归题目及原因
- 下一次实验变量

## 结果判断标准（建议）

1. `Search hit@k` 不下降
2. `Ask source hit@k` 不下降
3. `Avg keyword recall` 提升，或保持不变但更稳定
4. 回归题数量可解释且可接受

## 常见误区

1. 一次改多个变量（无法定位收益来源）
2. 只看总分，不看逐题回归
3. 没有固定 baseline（无法证明优化有效）

## Day5 完成标准

- [ ] 完成一次单变量实验
- [ ] 生成 `comparison_report.md`
- [ ] 写完 `analysis_template.md`
- [ ] 明确下一次实验计划
