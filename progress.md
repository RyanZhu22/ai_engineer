# 📊 每日进度追踪

> 每天 10 分钟更新。目标：每周完成一个可展示的交付物。

## ✅ 已完成里程碑

| 交付物 | 状态 | 日期 | 说明 |
|--------|------|------|------|
| 市场调研（79 职位 + 29 薪资） | ✅ | 08-10 | `market-research-2026.md` |
| LLM QA 服务（FastAPI + SSE + 多供应商） | ✅ | 08-10 | 本地可跑 |
| 存储升级 PostgreSQL + pgvector | ✅ | 08-11 | docker compose |
| RAG 全链路（上传/切分/检索/生成/来源） | ✅ | 08-11 | bge-small-zh 本地 embedding |
| Docker image（128MB）+ 容器验证 | ✅ | 08-11 | 7 个 pytest 通过 |
| **Render 云端部署** | ✅ | 08-11 | 公网可上传 + RAG 问答 |
| **Agent 开发（tool calling / 工具循环）** | ✅ | 08-13 | 3 个内置工具 + 流式追踪 + 安全边界 |
| **MCP 接入（stdio / Streamable HTTP）** | ✅ | 08-13 | allow-list + Agent 复用 + 24 个测试 |
| **云端 MCP 配置 + 端到端验证** | ✅ | 08-13 | Render 控制台配置 `MCP_SERVERS_JSON`，Agent 混合调用内置 + MCP 工具 |

## 待办

- [ ] LLM 评估（Ragas / 评测集）
- [ ] LLMClient 重试 + 连接池上限
- [ ] 混合检索（BM25 + 向量）
- [ ] 简历更新

## 面试问题积累

> 每天记 1 个面试问题 + 你的回答思路

### 问题 1：liveness 和 readiness 有什么区别？
**回答思路：**
- liveness = 容器是否活着，如果挂了就重启（kill & restart）
- readiness = 容器是否准备好接收流量，如果没准备好就摘除（不路由流量）
- 关键：readiness 失败 ≠ 重启，liveness 失败 = 重启

### 问题 2：什么是 IaC / Blueprint？（08-11 新增）
**回答思路：**
- 声明式配置描述云资源（web 服务 + 数据库），点一下 Apply 自动创建
- 类比 docker-compose（本地）→ render.yaml（云端）→ Terraform（企业通用）
- 可版本控制、可复现、可审计

### 问题 3：什么是 function calling / tool calling？（08-12 新增）
**回答思路：**
- LLM 不直接回答，而是返回「要调用哪个函数 + JSON 参数」
- Agent 循环：模型决策 → 执行工具 → 结果回喂 → 直到给出最终回答（ReAct）
- 工具用 name + description + JSON Schema 描述，模型靠 description 理解何时调用
- 面试亮点：把「检索知识库 / 计算器 / 查时间」包装成工具，LLM 按需自主选择

### 问题 4：为什么要用工具而不是让 LLM 自己算？（08-12 新增）
**回答思路：**
- LLM 擅长语言理解，不擅长精确计算和实时信息
- 训练数据有截止时间，不知道「现在几点」；算术容易出错
- 工具（calculator/get_current_time）是确定性的，可复现、可测试
- RAG 检索 = 一种特殊的工具调用（把检索器包装成 search_knowledge_base）

### 问题 5：MCP 与 function calling 有什么关系？（08-13 新增）
**回答思路：**
- function calling = 模型输出「函数名 + JSON 参数」的调用格式；MCP = 外部工具、资源和提示词的标准协议
- 本项目先把本地/远程 MCP tool 适配为同一个 `Tool` 抽象，再交给原有 Agent loop，避免重写编排逻辑
- 安全重点：MCP server 与 tool 都由部署者 allow-list；客户端不能传 command、URL、token；设置超时、数量和输出长度上限
