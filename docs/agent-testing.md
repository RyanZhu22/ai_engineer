# 🧪 Agent 功能测试手册

> 用途：验证 Agent（tool calling / MCP）功能是否正常。照做即可，每条都有「预期」和「判断标准」。
> 适用：本地（dev）与云端（Render）通用，把 URL 换掉即可。
>
> 当前项目状态、路径和 P0/P1 待办见 [`project-status.md`](project-status.md)。P0-1 已启用登录，所有业务 API 示例都要带 bearer token。

---

## 0. 三种验证方式，各管什么

| 方式 | 命令/操作 | 验证什么 | 频率 |
|------|----------|---------|------|
| 自动化测试 | `pytest` | 循环逻辑、安全边界、容错（确定性，无真实 LLM） | 每次改动代码 |
| 手动 curl | 下文的 curl 命令 | 真实模型决策是否调对工具 | 功能自测 |
| 前端 UI | 浏览器操作 | 用户体验、流式展示 | 交付前 |

---

## 1. 自动化测试（最核心，先跑这个）

```bash
cd projects/llm-qa-service
source .venv/bin/activate
python -m pytest -q
```

**预期**：当前为 `54 passed`（用例数随功能增加会变化）。
**判断标准**：
- 有失败 → 看失败用例名定位问题
- 全绿 ≠ 全部正常，只代表「循环逻辑对」（mock LLM 模拟模型决策，不验证真实模型）

---

## 2. 启动本地服务

```bash
cd projects/llm-qa-service
docker compose up -d
source .venv/bin/activate
python -m uvicorn app.main:app --host 127.0.0.1 --port 8010
```

**预期**：启动无报错。另开一个终端跑下面的 curl。

先创建测试账号并登录，把返回的 `access_token` 设为环境变量。密码至少 12 位：

```bash
cd projects/llm-qa-service
docker compose up -d
.venv/bin/python -m app.manage_users agent_test
# 如果账号已存在，换一个测试用户名
# 执行下面的登录请求后，复制 JSON 中的 access_token
curl -s -X POST http://127.0.0.1:8010/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"agent_test","password":"<创建账号时的密码>"}'
export TOKEN='<登录 /auth/login 返回的 access_token>'
```

除 `/health` 外，下面的业务请求均需要添加：

```bash
-H "Authorization: Bearer $TOKEN"
```

```bash
curl -s http://127.0.0.1:8010/health
# 预期：{"status":"UP",...,"mode":"live"}
# mode 是 live = 配置了真实 LLM key；mock = 没配 key（也能测，回复带 [MOCK MODE] 前缀）

curl -s http://127.0.0.1:8010/auth/me \
  -H "Authorization: Bearer $TOKEN"
# 预期：返回 agent_test 账号信息
```

---

## 3. 对照组：普通聊天（不带 Agent）

```bash
curl -s -X POST http://127.0.0.1:8010/chat \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"message":"帮我算 (125+75)*0.08"}'
```

**预期**：有回复，但**没有** tool_calls 字段。
**作用**：确认 Agent 是额外能力，普通链路没被改坏。

---

## 4. Agent 核心：三个内置工具

每个场景看两个东西：**① 调了哪个工具**（`tool_calls[0].name`）；**② 最终回答是否正确**。

### 4.1 计算器

```bash
curl -s -X POST http://127.0.0.1:8010/agent \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"message":"帮我算 (125+75)*0.08"}'
```

**预期**：`tool_calls[0].name == "calculator"`，回复含 `16`。
**判断标准**：模型把算术外包给确定性工具 → Agent 决策正确。

### 4.2 当前时间

```bash
curl -s -X POST http://127.0.0.1:8010/agent \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"message":"现在香港几点了？"}'
```

**预期**：`tool_calls[0].name == "get_current_time"`，回复是真实时间（非"我的训练数据截止…"）。
**判断标准**：LLM 无法答实时信息 → 必须调工具，这是 Agent 存在意义的证明。

### 4.3 知识库检索（RAG 工具）

先上传一个文档（知识库有内容才测得出）：

```bash
curl -s -X POST http://127.0.0.1:8010/documents/upload \
  -H "Authorization: Bearer $TOKEN" -F "file=@员工手册.md"
# 或从网页上传：打开 http://127.0.0.1:8010 → 上传区域拖入 txt/md/pdf

curl -s -X POST http://127.0.0.1:8010/agent \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"message":"员工年假有多少天？"}'
```

**预期**：`tool_calls[0].name == "search_knowledge_base"`，回答内容来自手册。
**判断标准**：模型**自主决定**要检索（而不是每次都检索）——可对比普通 /chat 带 use_rag。

### 4.4 多工具协作（进阶场景）

```bash
curl -s -X POST http://127.0.0.1:8010/agent \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"message":"员工年假12天，我入职满2年，按手册我该有多少天？帮我算下多休几天"}'
```

**预期**：`tool_calls` 长度 ≥ 2（先 search 再 calculator 或反之），回答综合两个来源。
**判断标准**：这是 Agent 最强的场景——一次请求编排多个工具。

---

## 5. 流式端点（前端体验）

```bash
curl -s -N -X POST http://127.0.0.1:8010/agent/stream \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"message":"帮我算 2+3"}'
```

**预期**：SSE 事件序列（顺序很重要）：
```
data: {"type":"conversation_id",...}   ← 会话 id
data: {"type":"tool_call","name":"calculator","result":"5"}   ← 工具执行过程
data: {"type":"delta","content":"2 + 3 = 5"}                   ← 逐字流式
data: {"type":"done",...}                                      ← 结束
```
**判断标准**：tool_call 事件在 delta 之前；前端（`app/static/index.html`）会显示工具调用标签。

---

## 6. MCP 工具

### 6.1 本地演示 server

**只测一轮**：起服务时注入 MCP 配置（command 用你的 venv python 绝对路径）：

```bash
cd projects/llm-qa-service
source .venv/bin/activate
MCP_SERVERS_JSON="{\"demo\":{\"transport\":\"stdio\",\"command\":\"$(which python)\",\"args\":[\"-m\",\"app.demo_mcp_server\"],\"cwd\":\"$(pwd)\",\"allowed_tools\":[\"lookup_demo_policy\"]}}" \
  python -m uvicorn app.main:app --host 127.0.0.1 --port 8010
```

> 注意：外层用双引号，`$(which python)` / `$(pwd)` 才会展开成真实路径。云端（Render）不需要这两个字段，直接用 `"command":"python"`。

然后：

```bash
# ① 查看暴露的工具
curl -s http://127.0.0.1:8010/mcp/tools \
  -H "Authorization: Bearer $TOKEN"
# 预期：{"servers":{"demo":["mcp_demo_lookup_demo_policy"]},"tools":[...]}

# ② Agent 实际调用 MCP 工具
curl -s -X POST http://127.0.0.1:8010/agent \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"message":"我们公司年假多少天？","use_mcp":true}'
# 预期：tool_calls[0].name == "mcp_demo_lookup_demo_policy"，回复含 "12 天年假"
```

**云端版本**：Render 控制台 → Environment 已配置 `MCP_SERVERS_JSON`（值见 `.env.example` 第 44 行格式），把 URL 换成 `https://llm-qa-service.onrender.com` 即可，无需 command/cwd（容器里 `python -m app.demo_mcp_server` 直接可用）。

### 6.2 安全行为（必测）

```bash
# ① 未配置 MCP 时请求 MCP → 必须 503 + 明确报错，而不是静默忽略
curl -s -X POST http://127.0.0.1:8010/agent \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"message":"你好","use_mcp":true}'
# 预期：HTTP 503，{"detail":"未配置 MCP server；请设置 MCP_SERVERS_JSON"}

# ② 未配置 MCP 时查工具列表 → 503
curl -s http://127.0.0.1:8010/mcp/tools \
  -H "Authorization: Bearer $TOKEN"
# 预期：HTTP 503
```

---

## 7. 参数校验与安全边界

```bash
# ① 超限迭代数 → 422（pydantic 校验）
curl -s -X POST http://127.0.0.1:8010/agent \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"message":"你好","max_iterations":11}'
# 预期：HTTP 422

# ② 空消息 → 422
curl -s -X POST http://127.0.0.1:8010/agent \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"message":""}'
# 预期：HTTP 422
```

**安全计算器**（单元级，直接跑测试即可，测试用例已覆盖）：
```bash
python -m pytest tests/test_api.py::test_calculator_rejects_unsafe_or_resource_intensive_expression -q
# 验证：__import__('os').system(...) / 10**99 / 超长表达式 全部被拒
```

---

## 8. 前端 UI 验证（交付前最后一步）

浏览器打开 `http://127.0.0.1:8010`（云端为 `https://llm-qa-service.onrender.com`）：

| 步骤 | 操作 | 预期 |
|------|------|------|
| 1 | 登录测试账号，再勾选「🤖 Agent 模式（自动调用工具）」 | 聊天切换为 agent 模式 |
| 2 | 发送「帮我算 12*8+4」 | 气泡内出现工具调用标签（calculator），回答含 100 |
| 3 | 发送「现在几点」 | 标签为 get_current_time，回答是当前时间 |
| 4 | 勾选「🔌 使用已配置 MCP 工具」（云端） | 发送「年假多少天」→ 标签为 mcp_demo_lookup_demo_policy |
| 5 | 刷新页面 | 历史仍在（PostgreSQL 持久化） |

---

## 9. 一键回归清单（每次改动后）

```bash
cd projects/llm-qa-service && source .venv/bin/activate
python -m pytest -q                            # 1. 当前 54 个全绿
curl -s http://127.0.0.1:8010/health           # 2. UP
# 3. 登录后：算数 → calculator；4. 时间 → get_current_time；5. 手册问题 → search_knowledge_base
# 6. use_mcp:true（未配置时）→ 503；7. max_iterations:11 → 422；8. 退出后 token → 401
```

全过 = Agent 功能正常。回答质量好坏（答得对不对）不在本手册范围，那是 LLM 评估（Ragas/评测集）的事。
