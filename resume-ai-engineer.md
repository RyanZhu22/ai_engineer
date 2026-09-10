# [YOUR NAME]
**AI Engineer** · Hong Kong · [email@example.com] · [github.com/yourname] · [linkedin.com/in/yourname]

---

## Professional Summary

Software engineer with 4 years of backend & full-stack experience (Spring Boot, React, Docker, AWS) now delivering production-oriented LLM applications. Built and cloud-deployed a complete RAG + Agent + MCP stack: document ingestion → local Chinese embeddings → hybrid retrieval → citation-annotated answers, with tool calling, PostgreSQL persistence, CI quality gates, and 54 automated tests. Strong engineering fundamentals — architecture, testing, IaC, reliability, and security — that transfer directly to production AI systems.

## Core Skills

| Area | Skills |
|------|--------|
| **LLM / AI** | LLM APIs (OpenAI-compatible: DeepSeek / OpenAI / Ollama), RAG pipelines, hybrid retrieval (BM25/vector/RRF), sentence-level reranking, embeddings (bge-small-zh, OpenAI-compatible), pgvector, tool calling / function calling, Agent loop (ReAct), MCP (stdio + Streamable HTTP), prompt engineering, LLM evaluation, output safety (sanitization, allow-lists, resource caps) |
| **Backend** | Python (FastAPI, SQLAlchemy async, pytest), Java (Spring Boot), REST APIs, SSE streaming, PostgreSQL |
| **DevOps / Cloud** | Docker (128MB image, non-root), IaC (render.yaml Blueprint), GitHub Actions CI, AWS (SAA certified), CI/CD |
| **Frontend** | React, vanilla JavaScript, ChatGPT-style streaming UI |

## Featured Project

### LLM QA Service — Enterprise Knowledge-Base Q&A Platform
*FastAPI · PostgreSQL · pgvector · MCP · Docker · GitHub Actions · Render*
**Live**: https://llm-qa-service.onrender.com  |  Source: [github.com/yourname/ai_engineer]

- **RAG pipeline and measurable quality**: built txt/md/pdf ingestion, paragraph/sentence-aware chunking (500 chars, 50 overlap), local Chinese embeddings (BAAI/bge-small-zh), and a hybrid retriever combining pgvector candidates, Chinese BM25, sentence-level reranking, and RRF. On a versioned 31-case benchmark, mock hybrid retrieval reached **96.5% Evidence Hit@1 / 100% Hit@4 / 0.9828 MRR**; local bge hybrid reached **100% / 100% / 1.0000**.
- **Agent with tool calling**: ReAct-style loop where the model autonomously chooses between knowledge-base search, a safe calculator (AST whitelist — blocks `__import__`, function calls, huge exponents), and live time lookup. Enforces iteration (≤5) and tool-call (≤12) caps, argument validation, and output truncation so model-generated inputs can never exhaust resources.
- **MCP integration**: adapter converts allow-listed external tools (stdio + Streamable HTTP) into the local Tool abstraction, namespaced as `mcp_<server>_<tool>`, so the existing Agent loop works unchanged. Security by design: clients cannot supply commands, URLs or tokens; servers and tools are allow-listed by the deployer; per-call timeouts and output limits enforced.
- **Reliability, security, and delivery**: persisted conversations/documents/chunks in PostgreSQL via async SQLAlchemy; added password login with revocable bearer sessions and owner-level isolation across history, documents, RAG, Agent, and MCP permissions; added an httpx connection pool with bounded concurrency plus exponential-backoff retries for 429/5xx/network failures. **54 pytest tests** run with an offline hybrid-retrieval gate (Hit@1 ≥ 95%, Hit@4 = 100%); a live DeepSeek baseline also achieved 100% keyword, citation, and source-grounded refusal checks across 31 cases. Deployed via `render.yaml` Blueprint with secrets injected at the platform level, never committed.

## Work Experience

### Software Engineer — [Company A] · [City] · [2022 – 2026]
*[Please fill in 2–3 STAR bullets: what you built, team size, measurable impact. Suggested angles: Spring Boot REST services, React frontend, Docker containerization, CI/CD pipelines, AWS infra.]*
- [Bullet 1 — e.g. "Designed and built X serving Y users, cutting latency by Z%"]
- [Bullet 2]
- [Bullet 3]

### Software Engineer — [Company B] · [City] · [20XX – 2022]
- [Bullet 1]
- [Bullet 2]

## Certifications

- **AWS Certified Solutions Architect – Associate** (SAA)

## Education

- [Degree] · [University] · [Year]

## Languages

- English (professional) · Cantonese ([level]) · Mandarin ([level])
