# LLM QA Service 生产运维手册

本文只记录可复现的运维动作；密码、API key、数据库 URL 不写入仓库。

## 发布与 schema

1. 发布前在 CI 运行 `pytest -q` 和 mock hybrid 评测。
2. 生产环境设置 `AUTO_CREATE_SCHEMA=false`。
3. 发布命令先执行 `alembic upgrade head`，成功后再启动 Web 进程。
4. 回滚代码时不要自动回滚数据库；先确认旧代码兼容当前 revision。

查看当前 revision：

```bash
alembic current
alembic history --verbose
```

## 备份

使用受控机器和 secret 环境变量执行，备份文件放在加密的对象存储，不放进 git：

```bash
export BACKUP_FILE="/secure/backups/llmqa-$(date -u +%Y%m%dT%H%M%SZ).dump"
pg_dump --format=custom --no-owner --file "$BACKUP_FILE" "$DATABASE_URL"
chmod 600 "$BACKUP_FILE"
```

至少保留一份跨区域副本，并记录备份时间、schema revision 和校验值。生产数据库启用 TLS，
不要把 `DATABASE_URL` 打印到日志。

## 恢复演练

恢复到隔离的 staging 数据库，不直接覆盖生产库：

```bash
createdb llmqa_restore
pg_restore --clean --if-exists --no-owner --dbname "$RESTORE_DATABASE_URL" "$BACKUP_FILE"
DATABASE_URL="$RESTORE_DATABASE_URL" alembic current
```

恢复后验证 `/health`、账号登录、历史列表、文档检索和 HNSW 索引存在，再记录演练耗时（RTO）
与可接受数据丢失窗口（RPO）。本地已在临时数据库完成一次 `pg_dump` → `pg_restore` 演练，验证
`alembic_version=0001_initial`、`audit_logs` 和 HNSW 索引均可恢复；本项目目前没有从 Render 生产库
执行真实恢复，需在具备运维权限后补做。

## session 和审计清理

登录 token 只保存哈希，过期 session 与旧审计记录由受控 cron/Job 清理：

```bash
python -m app.maintenance cleanup-sessions
```

默认审计保留 90 天，可用 `AUDIT_RETENTION_DAYS` 或 `--audit-retention-days` 调整。清理命令不暴露为
业务 API；运行结果只输出删除数量。

## 限流与观测

生产设置 `RATE_LIMIT_ENABLED=true`。默认限制为每个来源地址每分钟 10 次登录、30 次高成本请求；
多实例部署时必须把进程内限流迁移到 Redis 或 API gateway。

每个响应带 `X-Request-ID`，请求日志只包含方法、路径、状态、延迟、用户 ID 和 request ID，不包含
请求正文、密码、token 或 LLM key。Prometheus 可抓取 `GET /metrics`；当前指标是单进程累计值，
重启后清零。
