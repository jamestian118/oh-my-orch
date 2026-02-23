# finalize-artifacts / milestone-finalize Usage

## 中文

### 1) 目的
`finalize-artifacts` 提供“方案2 + 合规闸门”的清理闭环：
1. `dry-run` 只生成清理 plan，不删除任何文件。
2. `confirm` 基于 plan 生成带 `plan_hash` / `approved_by` / `expiry` / `token` 的确认文件。
3. `apply` 在 verify 通过后执行删除，并进行严格校验（token、expiry、plan hash、roots 限定、git ignored）。

`milestone-finalize` 是上层封装：先自动运行 verify，再执行 `dry-run`，仅在交互式 TTY 下可选清理。

### 2) prerequisites
- `bash`（macOS 默认 bash 3.2+ 可用）
- `python3`
- `git`
- 在仓库根目录执行，且存在 `.harness` 标记文件

### 3) setup
```bash
# 进入项目根目录
cd /path/to/project

# 脚本应具备可执行权限（模板默认已设置）
chmod +x ./scripts/finalize-artifacts ./scripts/milestone-finalize
```

### 4) exact commands
```bash
# 1) 生成计划（默认 roots: .artifacts + test-results + scripts/.tmp + .ai/tmp-scripts）
./scripts/finalize-artifacts dry-run

# 2) 生成人工确认文件（默认 900 秒过期）
./scripts/finalize-artifacts confirm --approved-by "$USER"

# 3) 执行清理（apply 内部会先跑 ./scripts/verify）
./scripts/finalize-artifacts apply --token "<token-from-confirm>"

# 一步式 milestone 封板
./scripts/milestone-finalize
```

### 5) examples
```bash
# 自定义 roots + plan 路径
./scripts/finalize-artifacts dry-run \
  --root .artifacts \
  --root test-results \
  --plan .ai/finalize.plan.json

# 30 分钟有效期
./scripts/finalize-artifacts confirm \
  --plan .ai/finalize.plan.json \
  --confirm .ai/finalize.confirm.json \
  --approved-by "release-bot" \
  --expiry-seconds 1800

# 使用确认 token 执行 apply
./scripts/finalize-artifacts apply \
  --plan .ai/finalize.plan.json \
  --confirm .ai/finalize.confirm.json \
  --token "<token>"

# CI/非TTY 模式下，只跑 verify + dry-run，不删除
CI=true ./scripts/milestone-finalize
```

### 6) I/O
输入：
- `dry-run`：roots（默认 `.artifacts`、`test-results`、`scripts/.tmp`、`.ai/tmp-scripts`）、plan 输出路径（默认 `.ai/finalize-artifacts.plan.json`）
- `confirm`：plan 文件、批准人、过期秒数、可选 token
- `apply`：plan 文件、confirm 文件、token、可选 verify 命令

输出：
- plan：`.ai/finalize-artifacts.plan.json`
- confirm：`.ai/finalize-artifacts.confirm.json`
- apply 审计：`.ai/finalize-artifacts.last.json`
- 控制台候选清单与执行摘要

### 7) flags/options
`./scripts/finalize-artifacts dry-run`
- `--root <path>`：可重复，覆盖默认 roots
- `--plan <path>`：plan 输出路径

`./scripts/finalize-artifacts confirm`
- `--plan <path>`：输入 plan 文件
- `--confirm <path>`：confirm 输出路径
- `--approved-by <name>`：审批人
- `--expiry-seconds <sec>`：过期时间（秒）
- `--token <token>`：显式指定 token（可选）

`./scripts/finalize-artifacts apply`
- `--token <token>`：必须，和 confirm 文件一致
- `--plan <path>`：plan 文件
- `--confirm <path>`：confirm 文件
- `--last <path>`：apply 审计输出路径
- `--verify-cmd <cmd>`：apply 前执行的 verify 命令（默认 `./scripts/verify`）

`./scripts/milestone-finalize`
- `--root <path>`：传给 `dry-run`
- `--plan <path>`：传给 dry-run/confirm/apply
- `--confirm <path>`：传给 confirm/apply
- `--expiry-seconds <sec>`：传给 confirm
- `--approved-by <name>`：传给 confirm

### 8) fail-closed 行为
以下任一条件不满足，`apply` 会直接失败并且不删除：
- verify 失败
- confirm 过期
- token 不匹配
- plan hash 不匹配
- 候选不在 roots 下
- 候选不是 git ignored
- 候选在删除前消失（防止 plan 漂移）

### 9) troubleshooting
- 报错 `verify 失败`：先单独运行 `./scripts/verify` 修复失败步骤。
- 报错 `confirm 已过期`：重新执行 `confirm` 获取新 token。
- 报错 `token 校验失败`：确认 `apply --token` 与 confirm 文件一致。
- 报错 `候选不是 git ignored`：检查 `.gitignore`，仅允许清理被 ignore 的 artifacts。
- `milestone-finalize` 输出“跳过交互清理”：表示当前是 CI 或非 TTY，属于预期行为。

---

## English

### 1) Purpose
`finalize-artifacts` implements a Scheme-2 style compliance gate for cleanup:
1. `dry-run` creates a cleanup plan and never deletes files.
2. `confirm` creates a confirmation file containing `plan_hash`, `approved_by`, `expiry`, and `token`.
3. `apply` runs verify first, then performs strict checks (token, expiry, plan hash, roots boundary, git ignored) before deletion.

`milestone-finalize` is a wrapper: it runs verify first, then dry-run, and only allows cleanup interaction on TTY.

### 2) prerequisites
- `bash` (compatible with macOS default bash 3.2+)
- `python3`
- `git`
- Run from repo root with `.harness` marker present

### 3) setup
```bash
# Enter project root
cd /path/to/project

# Ensure executable bit (already set in template)
chmod +x ./scripts/finalize-artifacts ./scripts/milestone-finalize
```

### 4) exact commands
```bash
# 1) Generate plan (default roots: .artifacts + test-results + scripts/.tmp + .ai/tmp-scripts)
./scripts/finalize-artifacts dry-run

# 2) Generate confirmation (default expiry: 900s)
./scripts/finalize-artifacts confirm --approved-by "$USER"

# 3) Apply cleanup (apply runs ./scripts/verify first)
./scripts/finalize-artifacts apply --token "<token-from-confirm>"

# One-command milestone close-out
./scripts/milestone-finalize
```

### 5) examples
```bash
# Custom roots and plan path
./scripts/finalize-artifacts dry-run \
  --root .artifacts \
  --root test-results \
  --plan .ai/finalize.plan.json

# 30-minute confirmation window
./scripts/finalize-artifacts confirm \
  --plan .ai/finalize.plan.json \
  --confirm .ai/finalize.confirm.json \
  --approved-by "release-bot" \
  --expiry-seconds 1800

# Apply with confirmed token
./scripts/finalize-artifacts apply \
  --plan .ai/finalize.plan.json \
  --confirm .ai/finalize.confirm.json \
  --token "<token>"

# CI/non-TTY mode: verify + dry-run only, no deletion
CI=true ./scripts/milestone-finalize
```

### 6) I/O
Inputs:
- `dry-run`: roots (default `.artifacts`, `test-results`, `scripts/.tmp`, `.ai/tmp-scripts`), optional plan path
- `confirm`: plan path, approver, expiry seconds, optional explicit token
- `apply`: plan path, confirm path, token, optional verify command

Outputs:
- plan: `.ai/finalize-artifacts.plan.json`
- confirm: `.ai/finalize-artifacts.confirm.json`
- apply audit: `.ai/finalize-artifacts.last.json`
- console candidate list and execution summary

### 7) flags/options
`./scripts/finalize-artifacts dry-run`
- `--root <path>`: repeatable; overrides default roots
- `--plan <path>`: output plan path

`./scripts/finalize-artifacts confirm`
- `--plan <path>`: input plan path
- `--confirm <path>`: output confirm path
- `--approved-by <name>`: approver identity
- `--expiry-seconds <sec>`: confirmation lifetime
- `--token <token>`: explicit token override (optional)

`./scripts/finalize-artifacts apply`
- `--token <token>`: required; must match confirm file
- `--plan <path>`: plan path
- `--confirm <path>`: confirm path
- `--last <path>`: apply audit output path
- `--verify-cmd <cmd>`: verify command before deletion (default `./scripts/verify`)

`./scripts/milestone-finalize`
- `--root <path>`: forwarded to `dry-run`
- `--plan <path>`: forwarded to dry-run/confirm/apply
- `--confirm <path>`: forwarded to confirm/apply
- `--expiry-seconds <sec>`: forwarded to confirm
- `--approved-by <name>`: forwarded to confirm

### 8) fail-closed behavior
`apply` refuses deletion when any condition fails:
- verify fails
- confirmation expired
- token mismatch
- plan hash mismatch
- candidate not under roots
- candidate not git ignored
- candidate disappears before deletion (stale plan/race)

### 9) troubleshooting
- `verify failed`: run `./scripts/verify` directly and fix the failing stage first.
- `confirm expired`: rerun `confirm` to get a fresh token.
- `token mismatch`: ensure `apply --token` matches confirm content.
- `candidate is not git ignored`: update `.gitignore`; only ignored artifacts are deletable.
- `milestone-finalize` prints skip message: expected in CI or non-TTY mode.
