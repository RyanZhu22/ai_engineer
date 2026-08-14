# [YOUR NAME]
**AI Engineer** · Hong Kong · [email@example.com] · [github.com/yourname] · [linkedin.com/in/yourname]

---

## Professional Summary

Software engineer with 4 years of backend & full-stack experience (Spring Boot, React, Docker, AWS) now delivering production-grade LLM applications. Built and deployed a complete RAG + Agent + MCP stack: document ingestion → chunking → local Chinese embeddings → pgvector retrieval → citation-annotated answers, with a tool-calling Agent loop and MCP integration running live on the cloud behind CI/CD and 24 automated tests. Strong engineering fundamentals — architecture, testing, IaC, security — that transfer directly to production AI systems.

## Core Skills

| Area | Skills |
|------|--------|
| **LLM / AI** | LLM APIs (OpenAI-compatible: DeepSeek / OpenAI / Ollama), RAG pipelines, embeddings (bge-small-zh, OpenAI-compatible), pgvector, tool calling / function calling, Agent loop (ReAct), MCP (stdio + Streamable HTTP), prompt engineering, LLM output safety (sanitization, allow-lists, resource caps) |
| **Backend** | Python (FastAPI, SQLAlchemy async, pytest), Java (Spring Boot), REST APIs, SSE streaming, PostgreSQL |
| **DevOps / Cloud** | Docker (128MB image, non-root), IaC (render.yaml Blueprint), GitHub Actions CI, AWS (SAA certified), CI/CD |
| **Frontend** | React, vanilla JavaScript, ChatGPT-style streaming UI |

## Featured Project

### LLM QA Service — Enterprise Knowledge-Base Q&A Platform
*FastAPI · PostgreSQL · pgvector · MCP · Docker · GitHub Actions · Render*
**Live**: https://llm-qa-service.onrender.com  |  Source: [github.com/yourname/ai_engineer]

- **RAG pipeline end-to-end**: document ingestion (txt/md/pdf) → paragraph/sentence-aware chunking (500 chars, 50 overlap) → local Chinese embeddings (BAAI/bge-small-zh, zero API cost, no data egress) → pgvector cosine retrieval → answer generation with source citations. Measured retrieval precision improved from 0.03–0.46 (feature-hash mock) to 0.56–0.73 (bge-small-zh).
- **Agent with tool calling**: ReAct-style loop where the model autonomously chooses between knowledge-base search, a safe calculator (AST whitelist — blocks `__import__`, function calls, huge exponents), and live time lookup. Enforces iteration (≤5) and tool-call (≤12) caps, argument validation, and output truncation so model-generated inputs can never exhaust resources.
- **MCP integration**: adapter converts allow-listed external tools (stdio + Streamable HTTP) into the local Tool abstraction, namespaced as `mcp_<server>_<tool>`, so the existing Agent loop works unchanged. Security by design: clients cannot supply commands, URLs or tokens; servers and tools are allow-listed by the deployer; per-call timeouts and output limits enforced.
- **Production engineering**: conversations and vector chunks persisted in PostgreSQL via async SQLAlchemy; SSE streaming for ChatGPT-style UX; 24 deterministic pytest tests (mock-LLM based) wired into GitHub Actions CI; deployed via IaC (render.yaml Blueprint) with secrets injected at the platform level, never in git.

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
