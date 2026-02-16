# Day 6 - RAG 可观测性实战

Day4/Day5 你已经会评估“质量”。  
Day6 的目标是评估“系统状态”：稳定性、延迟、错误分布、热点查询。

## 今日目标

1. 为 Day3 采集请求日志
2. 生成日志分析报告
3. 执行一次 SLO 检查
4. 输出可执行优化计划

## 你会练到的能力

- AI 服务可观测性基础（日志 + 指标）
- 延迟与错误定位
- 用 SLO 做上线决策
- 将“质量评测”与“系统指标”结合

## 前置条件

1. Day3 服务可启动
2. Day4 评测脚本可执行（用于制造流量）

## Step 1: 启动 Day3（含日志）

`day3/app/main.py` 已接入日志与指标：
- 自动写入：`day3/logs/rag_requests.jsonl`
- 指标接口：`GET /metrics/summary`

启动命令：

```bash
cd day3
uvicorn app.main:app --host 127.0.0.1 --port 8001
```

## Step 2: 生成流量样本

建议直接跑 Day4 一次：

```bash
cd day4
python run_eval.py --base_url http://127.0.0.1:8001 --top_k 3
```

这会向 `/search` 和 `/ask` 发请求，便于 Day6 分析。

## Step 3: 查看实时指标

```bash
curl -s http://127.0.0.1:8001/metrics/summary
```

你将看到：
- `total_requests`
- `error_rate`
- `avg/p50/p95 latency`
- `endpoint_stats`
- `top_queries`
- `top_source_docs`

## Step 4: 生成日志分析报告

```bash
cd day6
python analyze_logs.py --log_path ../day3/logs/rag_requests.jsonl --output reports/log_report.md
```

输出：
- `day6/reports/log_report.md`

## Step 5: 执行 SLO 检查

默认阈值：
- `error_rate <= 2%`
- `p95_latency <= 3000ms`

```bash
python check_slo.py --log_path ../day3/logs/rag_requests.jsonl
```

只检查 `/ask`：

```bash
python check_slo.py --log_path ../day3/logs/rag_requests.jsonl --ask_only
```

自定义阈值：

```bash
python check_slo.py --log_path ../day3/logs/rag_requests.jsonl --max_error_rate 0.01 --max_p95_ms 2000
```

## Step 6: 输出复盘

用模板填写：
- `day6/analysis_template.md`

重点回答：
1. 现在的主要风险是错误率还是延迟？
2. 主要慢请求和热点查询是什么？
3. 下一轮优化优先改什么？

## Day6 完成标准

- [ ] `/metrics/summary` 有数据
- [ ] 成功生成 `reports/log_report.md`
- [ ] 至少执行一次 `check_slo.py`
- [ ] 写出一条明确的优化动作与验证方式
