# Auditable Business Agent 当前状态

## 项目位置

- 工作区：`/Users/ryan/developer/career_study/ai_engineer`
- 新项目：`projects/auditable-business-agent`
- 原有项目：`projects/llm-qa-service`

两个项目独立维护。新项目不修改原项目文件，也不依赖原项目运行时代码。

## 当前阶段

阶段 P6：本地 BGE 真实 Embedding、30 条 RAG 评测集、浏览器端到端测试和 CI 已完成；审批 Agent、审计链路和 React 演示页可运行。

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
- 将检索评测集扩充为 30 条查询（退货、维修、物流各 10 条），覆盖同义改写、时间边界、材料要求和物流延迟干扰，输出 Recall@1、Recall@K、MRR 和逐案例检索结果 JSON。
- 添加 Playwright 浏览器端到端测试：物流直通，以及退货暂停后由审批人恢复。
- 添加独立 E2E 测试账号初始化脚本和 GitHub Actions CI；CI 在配置 `OPENAI_API_KEY` Secret 时额外运行 OpenAI Embedding 对照评测。
- 添加 FastEmbed 本地 `BAAI/bge-small-zh-v1.5` 真实中文 Embedding；DeepSeek 继续只负责回复生成。
- 为不同 Embedding provider/维度使用独立 PGVector collection 和文档 ID 命名空间；迁移 `0004_vector_unconstrained` 解除 LangChain 表的固定向量维度限制。
- 将 BGE 真实检索评测加入 CI，默认 Docker 服务使用 BGE，并为模型缓存增加命名 volume。

本轮验证：33 个离线测试、4 条黄金案例和 2 条 Playwright E2E 通过。BGE 真实 Embedding 在 30 条检索评测集上达到 Recall@1=0.9667、Recall@2=1.0、MRR=0.9833；其中 1 条泛化物流状态查询在 Top-1 排位到延迟政策，Top-2 命中目标政策。local 256 维基线为 Recall@1=0.7667、Recall@2=1.0、MRR=0.8833。`alembic upgrade head` 已执行 `0004_vector_unconstrained`，Docker 镜像已重建并通过健康检查。OpenAI Embedding 仍是可选对照，CI 仅在 `OPENAI_API_KEY` Secret 存在时运行。

## 下一步

1. 扩充政策语料，增加跨主题干扰文档后再提高 BGE Recall@1 门槛。
2. 扩充黄金集，覆盖更多订单归属、文档缺失和模型失败降级案例。
3. 可选：配置 `OPENAI_API_KEY`，与本地 BGE 做成本、延迟和误召回对照。

## 暂不做

- 真实退款、发邮件或修改生产数据。
- 多 Agent 编排。
- 企业 SSO 和复杂组织权限。
- 在没有评测集前宣称准确率。
