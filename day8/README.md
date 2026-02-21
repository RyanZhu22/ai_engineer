# Day 8 - 工具调用与多步工作流

Day8 的核心目标是掌握 AI Engineer 的关键能力：  
**让模型/Agent按需调用工具，而不是只输出一段文本。**

## 你会练到什么

1. 工具注册（tool registry）
2. 任务规划（plan tool calls）
3. 多步执行（multi-step execution trace）
4. 结果汇总（final answer synthesis）
5. 行为评测（tool match / keyword hit）

## 项目结构

```text
day8/
├─ app/
│  ├─ main.py          # FastAPI 接口
│  ├─ agent.py         # 规划与执行逻辑
│  └─ tools.py         # calculator/search_docs 工具
├─ data/docs/          # 本地知识文档
├─ eval_dataset.csv    # 工具调用评测数据
├─ run_tool_eval.py    # 自动评测脚本
├─ analysis_template.md
├─ requirements.txt
└─ README.md
```

## API 设计

1. `GET /health`
- 查看服务状态和工具数量

2. `GET /tools`
- 查看当前可用工具及描述

3. `POST /agent`
- 输入：`query`, `max_steps`
- 输出：
  - `tool_calls`（每步工具调用轨迹）
  - `used_tools`
  - `final_answer`

## 快速开始

```bash
cd day8
python -m pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8002
```

## 请求示例

### 1) 数学计算

```bash
curl -s http://127.0.0.1:8002/agent \
  -H "Content-Type: application/json" \
  -d "{\"query\":\"请计算 23 * (7 + 3)\",\"max_steps\":4}"
```

### 2) 知识检索

```bash
curl -s http://127.0.0.1:8002/agent \
  -H "Content-Type: application/json" \
  -d "{\"query\":\"RAG 的核心流程是什么\",\"max_steps\":4}"
```

### 3) 多工具问题

```bash
curl -s http://127.0.0.1:8002/agent \
  -H "Content-Type: application/json" \
  -d "{\"query\":\"请计算 100 / 4 并告诉我 RAG 为什么先检索\",\"max_steps\":4}"
```

你会看到 `tool_calls` 中按步骤调用 `calculator` 和 `search_docs`。

## 自动评测

在 Day8 目录运行：

```bash
python run_tool_eval.py --base_url http://127.0.0.1:8002 --dataset eval_dataset.csv
```

输出：
- `reports/tool_eval_summary_*.json`
- `reports/tool_eval_detail_*.csv`

关键指标：
1. `http_success_rate`
2. `tool_match_rate`（期望工具是否被调用）
3. `keyword_hit_rate`（回答是否覆盖目标关键词）

## 你应该关注的工程点

1. 工具 schema 是否清晰（输入输出稳定）
2. planner 是否容易误判（错工具、漏工具）
3. trace 是否可观测（每步 reason/args/result）
4. 失败是否可诊断（错误信息是否可读）

## Day8 完成标准

- [ ] 能跑通 `POST /agent`
- [ ] 至少完成 3 类问题（计算/检索/多工具）
- [ ] 成功运行 `run_tool_eval.py`
- [ ] 填写 `analysis_template.md` 输出下一轮改进计划
