# Day 1 - Hello LLM API

一个最小化的 FastAPI 服务，用来对接不同的 LLM 提供商。默认使用 `echo`，不需要任何外部依赖即可跑通链路。

## 功能
- `GET /health` 健康检查。
- `POST /llm` 输入 `prompt`，返回模型输出与当前 provider。

## 技术栈
- Python 3.x
- FastAPI
- httpx
- python-dotenv

## 目录结构
- `app/main.py` FastAPI 入口与路由
- `app/llm.py` LLM 调用逻辑与 provider 分发
- `app/config.py` 环境变量配置
- `.env.example` 环境变量模板
- `requirements.txt` 依赖清单

## 快速开始
1. 创建虚拟环境
2. 安装依赖
3. 复制并编辑环境变量
4. 启动服务

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

## 环境变量说明
- `LLM_PROVIDER` 选择提供商：`echo` | `ollama` | `deepseek`
- `OLLAMA_BASE_URL` Ollama 基础地址，默认 `http://localhost:11434`
- `OLLAMA_MODEL` Ollama 模型名，例如 `llama3`
- `DEEPSEEK_API_KEY` DeepSeek API Key
- `DEEPSEEK_BASE_URL` DeepSeek 基础地址，默认 `https://api.deepseek.com`
- `DEEPSEEK_MODEL` DeepSeek 模型名，默认 `deepseek-chat`

## Provider 配置示例

### echo（默认）
不需要额外配置，直接启动即可。

### ollama
```bash
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3
```

### deepseek
```bash
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=your_api_key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
```

## 调用示例

### 健康检查
```bash
curl -s http://127.0.0.1:8000/health
```

### LLM 请求
```bash
curl -s http://127.0.0.1:8000/llm \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"Hello LLM"}'
```

## 返回示例
```json
{
  "provider": "echo",
  "output": "[echo] Hello LLM"
}
```

## 常见问题
- 返回 400 且提示 `MODEL is not set`：请检查对应 provider 的模型配置是否填写。
- 返回 400 且提示 `API_KEY is not set`：请检查 DeepSeek API Key 是否正确填写。
- 连接失败：确认 `OLLAMA_BASE_URL` 或 `DEEPSEEK_BASE_URL` 是否可达。

## 备注
- `.env` 建议加入 `.gitignore`，避免提交敏感信息。
- 本仓库未包含 git 初始化与远程连接步骤，按你的需求自行处理。
