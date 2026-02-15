# Day 2 - Vector Search (Embeddings)

本日目标：完成一个最小可用的“向量检索”系统，并理解从文档到检索结果的完整链路。  
你会得到一个能实际跑起来的检索脚本，而不是伪代码或概念演示。

## 学习目标

完成 Day2 后，你应该能解释并实践以下流程：

1. 文档切分（Chunking）
2. 文本向量化（Embedding）
3. 向量相似度计算
4. Top-K 召回
5. 输出可读检索结果

## 项目结构

```text
day2/
├─ data/
│  └─ docs/
│     ├─ rag_intro.txt
│     ├─ fastapi_notes.txt
│     └─ ai_engineer_path.txt
├─ requirements.txt
├─ vector_search.py
└─ README.md
```

- `data/docs/`：知识库文档目录，只读取 `.txt` 文件。
- `vector_search.py`：主脚本，包含加载、切分、建索引、检索、展示结果。
- `requirements.txt`：运行所需依赖。

## 环境要求

- Python `3.10+`（建议 `3.11`）
- 可访问 Hugging Face（首次运行会下载模型）
- 操作系统：Windows / macOS / Linux

## 安装步骤

在 `day2` 目录下执行：

```bash
cd day2
python -m venv .venv
```

激活虚拟环境：

- Windows (PowerShell)

```powershell
.venv\Scripts\Activate.ps1
```

- macOS / Linux (bash/zsh)

```bash
source .venv/bin/activate
```

安装依赖：

```bash
python -m pip install -r requirements.txt
```

## 一键运行（最小示例）

```bash
python vector_search.py --query "RAG 的流程是什么"
```

更多示例：

```bash
python vector_search.py --query "FastAPI 怎么跑" --top_k 2
python vector_search.py --query "AI 工程师需要哪些能力" --top_k 3
```

## 参数详解

脚本支持以下参数：

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--query` | 无（必填） | 检索问题文本 |
| `--docs_dir` | `data/docs` | 文档目录，只读取 `.txt` |
| `--top_k` | `3` | 返回结果数量 |
| `--max_chars` | `200` | 每条结果最大展示字符数 |
| `--model` | `sentence-transformers/all-MiniLM-L6-v2` | Embedding 模型名 |
| `--batch_size` | `32` | 批量向量化大小 |

示例：

```bash
python vector_search.py \
  --query "RAG 是什么" \
  --docs_dir "data/docs" \
  --top_k 5 \
  --max_chars 300 \
  --model "sentence-transformers/all-MiniLM-L6-v2" \
  --batch_size 16
```

## 代码执行流程（对应 `vector_search.py`）

1. `load_chunks(docs_dir)`
   - 遍历 `docs_dir/*.txt`
   - 以空行 `\n\n` 分段切分
   - 产出 `Chunk(doc_name, chunk_id, text)`

2. `build_index(chunks, model, batch_size)`
   - 将 chunk 文本列表送入 `SentenceTransformer.encode(...)`
   - 生成每个 chunk 的 embedding 向量
   - 使用 `normalize_embeddings=True`，向量被归一化

3. `search(query, model, vectors, top_k)`
   - 对 query 生成向量
   - 用 `np.dot(vectors, q_vec)` 计算相似度
   - 对分数排序，取 Top-K 索引

4. `main()`
   - 解析命令行参数
   - 校验文档目录与数据
   - 构建索引并执行查询
   - 打印排名、来源文档和片段内容

## 为什么 `dot` 可以当相似度

脚本中 chunk 向量与 query 向量都做了归一化。  
归一化后，向量点积等价于余弦相似度，因此可直接用 `np.dot` 排序。

## 如何添加自己的知识库

1. 在 `data/docs/` 下新增 `.txt` 文件。
2. 每段内容之间用空行分隔（这会影响切分粒度）。
3. 重新运行检索命令即可，无需手动重建索引文件（本项目为内存实时构建）。

建议：
- 单段不要过长，控制在 100-300 中文字或 1-3 个英文句子更易命中。
- 一段只表达一个主题，减少语义混杂。

## 常见问题排查

### 1) `ModuleNotFoundError: sentence_transformers`

原因：依赖未安装到当前 Python 环境。  
处理：

```bash
python -m pip install -r requirements.txt
```

### 2) 首次运行很慢

原因：首次会下载模型权重。  
处理：等待下载完成；后续会使用本地缓存，速度明显提升。

### 3) Windows 出现 symlink 警告

这是 Hugging Face 缓存机制提示，一般不影响运行结果。  
可忽略，或开启 Windows Developer Mode 以启用更优缓存方式。

### 4) `No .txt documents found in docs_dir`

原因：目录为空或路径错误。  
处理：确认 `--docs_dir` 指向正确目录，且目录下有 `.txt` 文件。

## 学习检查清单（建议逐项打勾）

- [ ] 我可以独立运行命令得到 Top-K 结果  
- [ ] 我知道 chunk 是怎么切出来的  
- [ ] 我知道为什么点积可用于相似度排序  
- [ ] 我能新增文档并观察检索结果变化  
- [ ] 我能通过 `--top_k`、`--max_chars` 调整输出行为  

## 进阶练习

1. 改切分策略：把 `\n\n` 切分改成固定长度滑窗，对比检索效果。
2. 对比模型：更换 `--model`，观察速度与结果相关性的差异。
3. 增加评估：自建 10 个 query + 标准答案，手动计算命中率。
4. 接入生成：把 Top-K 片段拼接给 LLM，形成最小 RAG 闭环。

## 本日结论

Day2 的核心不是“把向量算出来”，而是建立工程化思维：  
同一条检索链路可以直接迁移到生产系统（本地模型或 API embedding 都适用），
变化的只是模型与存储实现，不变的是“切分 -> 向量化 -> 相似度检索 -> 结果利用”。
