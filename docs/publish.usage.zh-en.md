# publish Usage

## 中文（ZH）

### 概述
`./scripts/publish` 是标准化发布入口，默认执行 4 阶段：
1. `sanitize`：secrets-check + 轻量 PII heuristic
2. `classify`：输出 visibility recommendation 与 reason
3. `publish`：`milestone-finalize -> auto commit -> push -> ensure PR -> comment`
4. `visibility-verify`：使用 `gh repo view` 校验 expected vs actual visibility

阻断规则（非 dry-run）：
- `sanitize` 命中 secrets（`count > 0`）会直接阻断发布
- `--visibility public` 且命中 PII（`count > 0`）会直接阻断发布

脚本会产出 machine-readable JSON：
- `manifest.json`
- `publish-results.json`

### prerequisites
- `git`
- `grep`
- 仅在真实发布时需要：
  - `gh`（GitHub CLI）
  - 已完成 `gh auth login`
  - 当前目录是 git repo，且已配置 `origin`

### setup
```bash
chmod +x ./scripts/publish
```

### exact commands
```bash
# 默认全流程
./scripts/publish

# 指定 base 与 commit message
./scripts/publish --base main --commit-message "chore: publish"

# 指定期望 visibility（覆盖 auto）
./scripts/publish --visibility private
./scripts/publish --visibility public

# 仅跑 sanitize/classify（无远端/无 gh 场景推荐）
./scripts/publish --dry-run

# 自定义 artifact 根目录
./scripts/publish --artifact-root /tmp/sanitized_publish_artifacts

# 保留旧行为 flags
./scripts/publish --skip-finalize
./scripts/publish --skip-codex-review
./scripts/publish --review-comment "@codex review"
```

### examples
```bash
# 本地预检（只出 manifest + classify）
./scripts/publish --dry-run

# 强制按 private 校验远端可见性
./scripts/publish --visibility private

# 已做过 finalize 时，跳过 finalize 直接发布
./scripts/publish --skip-finalize --commit-message "chore: quick publish"
```

### I/O
- 输入：当前分支、工作区改动、CLI 参数
- 输出：
  - 阶段日志（stdout/stderr）
  - `manifest.json`
  - `publish-results.json`
  - 发布时输出 PR URL 与 visibility verify 结果

默认 artifact 路径：
- `SANITIZED_PUBLISH_ARTIFACT_ROOT` 未设置时，默认：
  - `/Users/Zhuanz/Documents/Code/_sanitized_publish_artifacts/runs/incremental_<timestamp>/reports/`

### JSON schema（简要）
`manifest.json` 重点字段：
- `inputs.base_branch` / `inputs.requested_visibility` / `inputs.expected_visibility`
- `sanitize.secrets_check.count`
- `sanitize.pii_heuristic.count`
- `classify.recommended_visibility`
- `classify.reason`

`publish-results.json` 重点字段：
- `status`（`dry-run|success|failed`）
- `steps.sanitize|classify|publish|visibility_verify`
- `visibility.requested|recommended|expected|actual|match`
- `repo.slug|repo.url|repo.pr_url`

### flags
- `--base <branch>`：指定 PR base 分支（默认 `main`）
- `--commit-message <msg>`：指定自动 commit message
- `--skip-finalize`：跳过 `milestone-finalize`
- `--skip-codex-review`：跳过 PR 评论
- `--review-comment <text>`：自定义 PR 评论内容
- `--visibility <auto|public|private>`：期望 visibility（默认 `auto`，即跟随 classify recommendation）
- `--artifact-root <dir>`：JSON 产物根目录
- `--dry-run`：只执行 sanitize/classify，不执行 publish/visibility-verify
- `-h|--help`：查看帮助

### cleanup stage 说明
- 垃圾清理仍在 `milestone-finalize` 阶段内：
  - 先执行 `verify`
  - 再执行 `finalize-artifacts dry-run`
  - 交互 TTY 仅在输入 `yes` 后才执行 confirm + apply

### troubleshooting
- `当前目录不是 git 仓库`：请在项目根目录执行
- `gh 未安装`：安装并登录（`brew install gh && gh auth login`）
- `缺少 origin remote`：先配置 remote（`git remote add origin <url>`）
- `visibility 校验失败`：检查 `--visibility` 与远端仓库实际可见性是否一致
- 仅想验证脱敏与分级：使用 `./scripts/publish --dry-run`

---

## English (EN)

### Overview
`./scripts/publish` is the standardized publish entrypoint with 4 stages by default:
1. `sanitize`: secrets-check + lightweight PII heuristic
2. `classify`: emits visibility recommendation and reason
3. `publish`: `milestone-finalize -> auto commit -> push -> ensure PR -> comment`
4. `visibility-verify`: validates expected vs actual visibility via `gh repo view`

Blocking rules (non dry-run):
- publishing is blocked when `sanitize` finds secrets (`count > 0`)
- publishing is blocked when `--visibility public` and PII findings exist (`count > 0`)

The script always emits machine-readable JSON:
- `manifest.json`
- `publish-results.json`

### prerequisites
- `git`
- `grep`
- Required only for real publish:
  - `gh` (GitHub CLI)
  - authenticated via `gh auth login`
  - current directory is a git repo with `origin`

### setup
```bash
chmod +x ./scripts/publish
```

### exact commands
```bash
# Default full pipeline
./scripts/publish

# Set base and commit message
./scripts/publish --base main --commit-message "chore: publish"

# Override expected visibility
./scripts/publish --visibility private
./scripts/publish --visibility public

# Run sanitize/classify only (recommended without remote/gh)
./scripts/publish --dry-run

# Custom artifact root
./scripts/publish --artifact-root /tmp/sanitized_publish_artifacts

# Existing flags remain supported
./scripts/publish --skip-finalize
./scripts/publish --skip-codex-review
./scripts/publish --review-comment "@codex review"
```

### examples
```bash
# Local preflight (manifest + classify only)
./scripts/publish --dry-run

# Enforce private visibility expectation
./scripts/publish --visibility private

# Skip finalize when already completed
./scripts/publish --skip-finalize --commit-message "chore: quick publish"
```

### I/O
- Inputs: current branch, working tree changes, CLI args
- Outputs:
  - stage logs (stdout/stderr)
  - `manifest.json`
  - `publish-results.json`
  - PR URL and visibility verification result during publish

Default artifact path:
- When `SANITIZED_PUBLISH_ARTIFACT_ROOT` is not set, default path is:
  - `/Users/Zhuanz/Documents/Code/_sanitized_publish_artifacts/runs/incremental_<timestamp>/reports/`

### JSON schema (summary)
Key fields in `manifest.json`:
- `inputs.base_branch` / `inputs.requested_visibility` / `inputs.expected_visibility`
- `sanitize.secrets_check.count`
- `sanitize.pii_heuristic.count`
- `classify.recommended_visibility`
- `classify.reason`

Key fields in `publish-results.json`:
- `status` (`dry-run|success|failed`)
- `steps.sanitize|classify|publish|visibility_verify`
- `visibility.requested|recommended|expected|actual|match`
- `repo.slug|repo.url|repo.pr_url`

### flags
- `--base <branch>`: set PR base branch (default `main`)
- `--commit-message <msg>`: set auto-commit message
- `--skip-finalize`: skip `milestone-finalize`
- `--skip-codex-review`: skip PR comment
- `--review-comment <text>`: override PR comment body
- `--visibility <auto|public|private>`: expected visibility (default `auto`, follows classify)
- `--artifact-root <dir>`: output root for JSON artifacts
- `--dry-run`: run sanitize/classify only; skip publish/visibility-verify
- `-h|--help`: show help

### Cleanup Stage
- Cleanup stays inside `milestone-finalize`:
  - runs `verify`
  - runs `finalize-artifacts dry-run`
  - executes confirm + apply only after interactive `yes`

### troubleshooting
- `当前目录不是 git 仓库` / not a git repo: run from project root
- `gh 未安装` / gh not found: install + login (`brew install gh && gh auth login`)
- missing `origin` remote: configure remote first (`git remote add origin <url>`)
- visibility mismatch: align `--visibility` with actual remote visibility
- sanitize/classify only validation: use `./scripts/publish --dry-run`
