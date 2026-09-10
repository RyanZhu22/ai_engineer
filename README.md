# 🎯 AI 工程师快速转行 · 行动纲领

> 4 年 SWE (Spring Boot / React / Docker) → 交付向 AI 工程师
> 目标市场：香港 · 时间窗口：6 个月可投，12 个月升级
>
> 📊 实时市场数据见 [`market-research-2026.md`](market-research-2026.md)（2026-08-10 抓取：79 个真实职位 + 29 个薪资）

跨终端继续项目时，先看 [`docs/project-status.md`](docs/project-status.md)；它记录当前工作区、验证结果、文件入口和下一步优先级。跨端开工/收尾与长任务规范见 [`docs/vibe-coding-workflow.md`](docs/vibe-coding-workflow.md)。

---

## 你现在的资产

| 已有能力 | 市场价值 | 差距 |
|----------|---------|------|
| Spring Boot / REST API | ✅ 高 | 无缝对接 FastAPI |
| React 全栈 | ✅ 加分 | 很多 JD 要求全栈 |
| Docker | ✅ 高 | 直接对接云部署 |
| AWS SAA 证书 | ✅ 高 | 这是面试硬通货 |
| CI/CD | ✅ 高 | MLOps 的基础 |
| 4 年工程经验 | ✅ 核心优势 | 大部分 AI 岗候选人的短板 |

**你的最大优势不是会多少 AI 框架，而是能把东西交付到生产环境。**

---

## 快速转行策略：专注 AI 工程师

基于 2026-08 真实市场数据，AI 工程师的硬性门槛是：

```
P0 (1-2月): Python AI生态 → LLM API → RAG链路
P1 (2-4月): Agent开发 → 向量数据库 → FastAPI
P2 (4-6月): 云AI服务(AWS Bedrock) → LLM评估 → MLOps
```

**你的优势：** Spring Boot/Docker/AWS/CI/CD/SQL 全部可直接迁移，只缺 Python AI + LLM/RAG/Agent 概念。

---

## 本周立即开始（前 7 天）

### Day 1-2：补完 Spring Boot baseline

- [ ] 确认 `/actuator/health/liveness` 和 `/actuator/health/readiness` 都能返回 200
- [ ] 配置从环境变量注入，代码中不出现 secret
- [ ] 记录启动时间、镜像大小、健康检查结果

### Day 3-4：Docker 化

- [ ] 构建 Docker image，记录 image size
- [ ] 以非 root 用户运行
- [ ] 验证 graceful shutdown

### Day 5-6：AWS 免费部署

- [ ] `aws configure`（你需要准备 AWS 账号）
- [ ] 创建 ECR repository
- [ ] Push Docker image
- [ ] EC2 t2.micro 部署（免费套餐）
- [ ] 验证公网访问

### Day 7：写一页 README

- [ ] 画出当前请求链路
- [ ] 写下失败时的恢复动作
- [ ] 记录本周的 baseline 数据

---

## 本周 checkpoint

把以下 4 项贴回来 review：

1. `curl` 的 health endpoint 输出
2. 启动时间、镜像大小表格
3. Dockerfile 是否构建成功
4. 你对 liveness/readiness 区别的解释
