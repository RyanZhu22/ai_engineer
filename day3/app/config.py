import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

RAG_DOCS_DIR = Path(os.getenv("RAG_DOCS_DIR", str(BASE_DIR / "data" / "docs")))
RAG_EMBED_MODEL = os.getenv("RAG_EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
RAG_BATCH_SIZE = int(os.getenv("RAG_BATCH_SIZE", "32"))
RAG_DEFAULT_TOP_K = int(os.getenv("RAG_DEFAULT_TOP_K", "3"))
RAG_SOURCE_MAX_CHARS = int(os.getenv("RAG_SOURCE_MAX_CHARS", "220"))

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "echo").lower()
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
