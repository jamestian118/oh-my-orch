# Security（安全）

## 中文（ZH）
### 红线（必须）
- 严禁将 secrets（密码/Token/私钥/服务器登录信息等）写入：代码仓库、README/docs、日志、commit message、PR description
- 优先使用环境变量或本地机密存储
- 若必须提供示例：使用 .env.example（不要放真实值）

### 检查（Checks）
- 本地：./scripts/secrets-check
- CI：.github/workflows/secrets.yml
- CI 触发：`pull_request`、`push (main)`、`workflow_dispatch`、`schedule`（UTC 03:17）
- CI 最小权限：`permissions: contents: read`

## English (EN)
### Non-negotiables
- Never commit secrets to repo/README/docs/logs/commit message/PR text
- Use env vars or local secret storage
- Provide examples via .env.example only (no real values)

### Checks
- Local: ./scripts/secrets-check
- CI: .github/workflows/secrets.yml
- CI triggers: `pull_request`, `push (main)`, `workflow_dispatch`, `schedule` (UTC 03:17)
- Minimum CI permission: `permissions: contents: read`
