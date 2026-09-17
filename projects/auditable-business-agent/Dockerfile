# syntax=docker/dockerfile:1

FROM node:22-alpine AS frontend-builder
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1

COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /uvx /bin/
WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY app ./app
RUN uv sync --frozen --no-dev

COPY alembic.ini ./
COPY migrations ./migrations
COPY sample_data ./sample_data
COPY --from=frontend-builder /build/frontend/dist ./frontend/dist

EXPOSE 8000

CMD ["sh", "-c", "/app/.venv/bin/alembic upgrade head && /app/.venv/bin/python -m app.seed && exec /app/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000"]
