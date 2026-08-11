# 🔍 香港 AI 工程师市场真实数据报告（2026年8月实时抓取）

> **数据来源**：本报告基于 2026-08-10 实时抓取的香港招聘网站数据
> - JobsDB (hk.jobsdb.com)：61 个 AI 相关职位，其中 29 个公开薪资
> - Talent.com（聚合 JobsDB/CTgoodjobs/Indeed/各公司 ATS）：18 个 AI 职位
> - 4 个完整 JD 深度解析：Buyandship、SCMP、Lalamove、Sia Partners

---

## 一、市场全景：谁在招 AI 工程师

### 抓取到的真实职位（61+18 = 79 个）

| 雇主类型 | 代表雇主 | 招聘方向 |
|---------|---------|---------|
| 🏦 金融/资管 | Page Executive、Top 资产管理公司、Quant 交易公司 | 投研 Copilot、AI 量化、LLM 驱动投资工具 |
| 🏥 保险 | **Manulife（3 个岗位）**、AI Adoption Manager | 内部 AI 转型、AI 治理 |
| 💼 咨询 | **Sia Partners（AI Engineer Manager）**、Infosys | 客户 AI 交付、RAG/Agent 方案 |
| 🚚 物流 | **Lalamove（Senior AI Engineer OCR/VLM）** | 计算机视觉、VLM、OCR |
| 📰 媒体 | **SCMP（AI Engineer Internal Automation）** | 内部 RAG + Agent 自动化 |
| 🛒 电商 | **Buyandship（Senior AI Engineer）** | LLM 应用、RAG、生产化 |
| 💬 SaaS | **Wati（Staff AI Engineer）** | 多模型网关、多 Agent（MCP）、语音 AI |
| 🚀 初创 | Crypto 初创（CAIO）、MatchaTalent | 全面 AI 化、LegalTech |

---

## 二、技能需求深度分析（基于真实 JD 原文）

### 🥇 第一梯队：必须掌握（出现在几乎所有 JD）

| 技能 | 出现强度 | 说明 |
|------|---------|------|
| **Python** | ★★★★★ | 所有 JD 第一要求。Buyandship：`Strong Python and AI libraries (NumPy, Pandas, Scikit-learn)` |
| **LLM API** | ★★★★★ | `OpenAI, Anthropic, Gemini` 明确点名。SCMP：`Hands-on experience working with LLM APIs` |
| **RAG 架构** | ★★★★★ | SCMP：`Retrieval-Augmented Generation (RAG) such as LangChain, LlamaIndex`；Buyandship：`Knowledge of vector databases and RAG architectures` |
| **Agent / 多智能体** | ★★★★★ | Sia：`agentic AI systems, including tool calling, orchestration, memory management`；SCMP：`multi-agent orchestration frameworks` |
| **LLM 框架** | ★★★★★ | `LangChain / LlamaIndex / CrewAI / Semantic Kernel / vLLM` 反复出现 |

### 🥈 第二梯队：高价值加分（多数 JD 要求）

| 技能 | 出现强度 | 说明 |
|------|---------|------|
| **向量数据库** | ★★★★ | `pgvector, Chroma, Milvus, Pinecone, Qdrant, Azure AI Search` |
| **云 AI 平台** | ★★★★ | Sia：`AWS/Bedrock, Azure/Foundry, GCP/Vertex, Alicloud/PAI, Tencent Cloud/TI` |
| **FastAPI/Flask** | ★★★★ | Buyandship：`Docker, Kubernetes, FastAPI, Flask` 是加分项 |
| **Docker/K8s** | ★★★★ | 几乎所有生产化 JD 都提到 |
| **MLOps/GenAIOps** | ★★★★ | Sia 有专门板块：`CI/CD, testing, monitoring, evaluation` |
| **Prompt Engineering** | ★★★ | SCMP：`fine-tuning prompt strategies` |
| **SQL/数据库** | ★★★ | Buyandship：`Experience with large datasets and SQL databases` |

### 🥉 第三梯队：行业特定（按目标行业补充）

| 技能 | 适用行业 |
|------|---------|
| **PyTorch / Hugging Face** | 咨询（Sia）、量化（需要模型微调） |
| **OCR / 计算机视觉 / VLM** | 物流（Lalamove）、文档处理 |
| **数据管道 ETL/Spark** | 金融、数据工程向 |
| **n8n 等编排工具** | 咨询交付（Sia 提到） |
| **粤语/英语/普通话三语** | 所有香港岗位（SCMP 明确要求） |

---

## 三、薪资真实数据（JobsDB 2026-08-10 抓取）

### 已公开薪资的 29 个职位统计

| 职级 | 职位示例 | 薪资范围（HKD/月） |
|------|---------|-------------------|
| 初级 (0-2年) | AI Solutions Engineer (32K)、AI Engineer ($20-27K)、Specialist | **$20,000 – $32,000** |
| 中级 (2-4年) | AI Engineer（多数）、AI Platform Engineer、AI System Engineer | **$28,000 – $45,000** |
| 中高级 (4-6年) | AI Technical Lead、AI Transformation Specialist、Senior AI Solution Engineer | **$35,000 – $60,000** |
| 高级/管理 (6年+) | Sia AI Engineer Manager、Manulife Senior Manager | **$60,000 – $120,000**（估） |

### 数据要点

- **AI Engineer 中位数**：约 **HKD $30,000 – $40,000/月**
- **Junior AI Engineer（Michael Page）**：$31,000 – $38,000/月
- **AI Technical Lead（Financial Services）**：$35,000 – $50,000/月
- **AI Transformation Specialist**：$40,000 – $60,000/月
- **LLM Engineer（Data and Optimization）**：$30,000 – $45,000/月
- **AI 咨询岗（Sia Partners）**：通常 $50,000 – $90,000/月（含项目奖金）

> ⚠️ 你目前 4 年 SWE 经验（HK$32K+32K bonus），如果直接转 AI 中级岗，薪资水平接近持平（$28-45K）；但如果走 **AI Platform Engineer / AI 咨询** 路线，薪资可以向上突破到 $50-60K+。

---

## 四、完整 JD 拆解（原文核心）

### 1️⃣ Buyandship · Senior AI Engineer（最匹配你现状）

```
✅ 要求：3+ 年开发，其中 1+ 年 Python AI 项目
✅ Strong Python + AI libraries (NumPy, Pandas, Scikit-learn)
✅ 至少一个 LLM 框架 + 主流 LLM API
✅ 向量数据库 + RAG 架构知识
✅ 云 AI 平台经验（加分）
✅ 版本控制、测试、CI/CD
✅ Docker, K8s, FastAPI, Flask 部署经验（加分）
✅ 大型数据集 + SQL
✅ 流利中英文
```

**你的现状**：4 年开发 ✅ | CI/CD ✅ | Docker ✅ | SQL ✅ | 缺 Python AI、RAG、LLM API

### 2️⃣ SCMP · AI Engineer (Internal Automation)

```
✅ 2+ 年软件工程/数据工程/系统自动化
✅ 生产级 GenAI 应用（RAG, Agents）交付经验
✅ LLM APIs (OpenAI, Anthropic, Gemini)
✅ LangChain, LlamaIndex, CrewAI, Semantic Kernel, vLLM
✅ Python + 系统集成
✅ 粤语/英语（普通话加分）
```

### 3️⃣ Sia Partners · AI Engineer Manager（进阶目标）

```
✅ 6+ 年 AI 工程/MLOps/DevOps/数据工程
✅ Python + PyTorch + Hugging Face + LangChain + LlamaIndex
✅ n8n 等 AI 编排平台
✅ AWS/Bedrock, Azure/Foundry, GCP/Vertex
✅ 容器化 + 微服务 + 云原生架构
✅ MLOps/GenAIOps: CI/CD, 监控, 评估, 可观测性
✅ LLM 评估框架（相关性、事实性、幻觉、延迟、成本、鲁棒性）
✅ 英语必须，粤语高度优先
```

### 4️⃣ Lalamove · Senior AI Engineer (OCR/VLM)

```
✅ 5+ 年生产级 ML 系统
✅ 计算机视觉、LLM、VLM、OCR、向量数据库
✅ ASR/TTS 加分
✅ 英语 + 普通话
```

---

## 五、结论：转行 AI 工程师需要什么技能

### 核心结论：6 个月可达成

基于真实 JD 分析，从你现在的 4 年 SWE 背景出发，需要补齐的技能按优先级排序：

### 🔴 P0：必须立即学（1-2 个月）— 所有 JD 的硬性门槛
1. **Python AI 生态**：NumPy → Pandas → scikit-learn（1 周上手，Buyandship 明确要求）
2. **LLM API 调用**：OpenAI / Anthropic / Gemini 任选 1-2 个（SCMP 明确点名）
3. **RAG 完整链路**：LangChain 或 LlamaIndex，加载 → 切分 → 向量化 → 检索 → 生成

### 🟠 P1：核心竞争（2-4 个月）— 拉开差距
4. **Agent 开发**：tool calling / function calling / MCP（SCMP、Sia 都要求 multi-agent）
5. **向量数据库**：pgvector（如果你会 PostgreSQL 最快）→ Chroma/Milvus
6. **FastAPI**：把 AI 服务封装成 REST API（你的 Spring Boot 经验直接平移）

### 🟡 P2：生产化（4-6 个月）— 薪资翻倍关键
7. **云 AI 服务**：AWS Bedrock 或 Azure Foundry（你有 AWS SAA 基础，最快）
8. **LLM 评估**：Ragas / 自建评测集（Sia 有专门板块，面试必问）
9. **MLOps/GenAIOps**：CI/CD for LLM、监控、成本控制

### 语言要求（香港特有）
- **英语**：必须（所有 JD 都要求）
- **粤语**：强烈加分（SCMP、Sia 都提到）
- **普通话**：加分（SCMP 提到）

---

## 六、与你现有技能的映射

| 你已经会的 | 直接可迁移到 | 节省时间 |
|-----------|-------------|---------|
| Spring Boot REST API | FastAPI / Flask | ✅ 架构思维一样 |
| Docker | AI 服务容器化 | ✅ 直接复用 |
| AWS SAA | AWS Bedrock / SageMaker | ✅ 云基础直接迁移 |
| CI/CD | MLOps pipeline | ✅ 概念一样 |
| SQL | 数据层设计 | ✅ 直接复用 |
| React | AI 应用前端 | ✅ 加分项 |

**你唯一需要从零学的**：Python AI 生态 + LLM/RAG/Agent 概念 + 向量数据库 —— 这比当年学 Spring Boot 简单得多。
