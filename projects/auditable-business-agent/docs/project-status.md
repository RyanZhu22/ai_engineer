# Auditable Business Agent 当前状态

## 项目位置

- 工作区：`/Users/ryan/developer/career_study/ai_engineer`
- 新项目：`projects/auditable-business-agent`
- 原有项目：`projects/llm-qa-service`

两个项目独立维护。新项目不修改原项目文件，也不依赖原项目运行时代码。

## 当前阶段

阶段 P3：基于 LangChain + pgvector 的政策向量检索已完成；审批 Agent、审计链路和 React 演示页可运行。

已完成：

- 创建独立项目目录。
- 确定业务场景为企业售后与客服工单。
- 确定第一版使用模拟业务系统和公开/脱敏数据。
- 确定 Agent、规则引擎、人工审批和审计记录的边界。
- 定义订单、售后请求、处理建议、审批、工单和审计事件模型。
- 实现模拟订单查询、带幂等键的模拟工单创建和追加式内存审计日志。
- 实现退货期限、保修期、订单不存在和订单归属校验等确定性规则。
- 为规则、审批约束、审计事件和幂等工单创建添加离线单元测试。
- 添加 SQLAlchemy repository、Alembic 初始迁移、PostgreSQL Docker Compose 配置和 SQLite 持久化测试。
- 提供 FastAPI：登录、创建案例、提交审批、查询案例和审计事件。
- 使用 LangGraph + PostgreSQL checkpoint 实现审批前暂停、审批后恢复。
- 添加本地用户管理命令和 JWT 角色校验；客服不能审批，审批人身份从 bearer token 派生。
- 添加 `0002_users` migration；本地 PostgreSQL 已升级至 `0002_users (head)`。
- 添加版本化政策文档和离线关键词检索；检索证据会以 `knowledge_retrieved` 事件进入审计轨迹。
- 添加 LangChain `Document`、文本切分、embedding、PGVector collection 和幂等政策导入；检索证据会记录 chunk 位置和来源。
- 添加 OpenAI-compatible 回复生成器；只有回复文案可由模型生成，规则与执行权限不交给模型。
- 添加 4 条黄金案例回归评测和 React 操作、审计页面。
- 添加 LangSmith 环境变量配置；提供密钥时可追踪 LangGraph 调用。

本轮验证：20 个离线测试通过；4 条黄金案例通过；`alembic heads` 指向 `0003_enable_vector`。2026-09-16 已在本地 Docker PostgreSQL 容器完成迁移，确认 `vector` 扩展、LangChain 的 `langchain_pg_collection` / `langchain_pg_embedding` 表存在，政策 collection 含 3 个 chunks，并成功召回退货、维修和物流政策。

## 下一步

1. 用真实 embedding 配置运行检索质量评测，记录 Recall@K、MRR 和错误案例。
2. 扩充黄金集，覆盖订单归属、文档缺失和模型失败降级。
3. 添加浏览器端到端测试与 CI。
4. 编写 Docker 生产镜像和简历项目说明。

## 暂不做

- 真实退款、发邮件或修改生产数据。
- 多 Agent 编排。
- 企业 SSO 和复杂组织权限。
- 在没有评测集前宣称准确率。
