# 可靠性规范 / Reliability

## 中文

### 可观测性规范

- **verify 日志**：每次运行 `./scripts/verify` 会输出 JSON 日志到 `.ai/verify-log.json`（每步 `name`/`status`/`duration_ms`）
- **失败可复现**：测试失败时必须输出可复现证据（最小复现命令 + 关键日志摘录 + 期望 vs 实际）
- **关键路径覆盖**：至少一个 smoke test 覆盖项目的关键路径（不仅是 `assert True`）

## English

### Observability Standards

- **verify logs**: Each run of `./scripts/verify` outputs a JSON log to `.ai/verify-log.json` (per-step `name`/`status`/`duration_ms`)
- **Reproducible failures**: On test failure, must output reproducible evidence (minimal repro command + key log excerpts + expected vs actual)
- **Critical path coverage**: At least one smoke test covers the project's critical path (not just `assert True`)
