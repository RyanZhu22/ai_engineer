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

## 待办

- [ ] Agent 开发（tool calling / function calling / MCP）
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
