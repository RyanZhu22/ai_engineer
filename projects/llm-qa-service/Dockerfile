FROM python:3.13-slim
WORKDIR /app

# 先装依赖（利用层缓存，改动代码时不用重装）
COPY pyproject.toml ./
RUN pip install --no-cache-dir \
    "fastapi>=0.115" "uvicorn[standard]>=0.30" "pydantic>=2.7" \
    "pydantic-settings>=2.3" "httpx>=0.27" "python-dotenv>=1.0" \
    "python-multipart>=0.0.9" \
    "sqlalchemy>=2.0" "psycopg[binary]>=3.1" "pgvector>=0.3" \
    "pypdf>=4.0" "fastembed>=0.3"

# 再复制代码（代码变化不会触发重装依赖）
COPY app ./app

# 非 root 用户运行（生产安全最佳实践）
RUN useradd -m appuser && chown -R appuser /app
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
