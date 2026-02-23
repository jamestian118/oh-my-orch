# oh-my-orch (omo)

## 中文（ZH）

### 项目简介（overview）
`oh-my-orch` 是一个多智能体编排器，协调 `Claude Code`、`Codex CLI`、`Gemini CLI` 在同一任务上协作。  
核心目标是把关键上下文沉淀到结构化文件（`.ai/project-brief.md`、`.ai/exec-plan.md`、`.ai/review.md`），并在 `.omo/pipeline-state.json` 中持久化阶段状态，支持 `resume/cleanup`。

### 使用方法（usage）
#### prerequisites
- Python 3.11+（模板默认 `.venv`）
- 已安装并登录：`claude`、`codex`、`gemini`（非 `--dry-run` 时）
- 项目已通过 `./scripts/setup`

#### setup
```bash
./scripts/setup
```

#### exact commands
```bash
# 查看完整 CLI 帮助
python omo.py --help

# Chat 模式（@agent 快捷语法）
python omo.py @claude "设计认证模块" --dry-run
python omo.py @codex chat "执行重构计划" --cwd . --no-auto-confirm

# Chat 模式（标准子命令）
python omo.py chat codex "执行重构计划" --dry-run

# Pipeline 模式
python omo.py pipeline "给项目添加用户认证" --dry-run

# Team 模式
python omo.py team "微服务还是单体" --dry-run

# 状态与历史
python omo.py status --cwd .
python omo.py history --limit 30

# 压缩、重置、恢复、清理
python omo.py compress --target-agent codex --max-chars 4000 --dry-run
python omo.py reset --cwd .
python omo.py resume --dry-run
python omo.py cleanup --cwd .
```

#### examples
```bash
# 仅跑到 stage1（便于调试）
python omo.py pipeline "实现审计日志" --dry-run --stop-after 1

# 控制 compress 输出长度（默认 5000）
python omo.py compress --target-agent gemini --max-chars 2000 --dry-run

# 真实模式（需要本机 CLI 与依赖就绪）
python omo.py pipeline "接入 SSO 登录"
```

#### I/O
- 输入：CLI 参数（任务描述、模式、`--dry-run`、`--stop-after` 等）
- 输出：标准 JSON 到 stdout（便于管道/自动化消费）
- 状态文件：`.omo/pipeline-state.json`
- 会话文件：`.omo/session.jsonl`、`.omo/chat-history.jsonl`
- 关键产物（兼容入口）：`.ai/project-brief.md`、`.ai/exec-plan.md`、`.ai/review.md`
- Pipeline 产物目录：`.ai/pipeline/runs/<run-id>/`（每次运行新目录；`run-id` 命名为“日期-时间-梗概-短哈希”：`YYYYMMDD-HHMMSS-<summary>-<short-hash>`，时间为北京时间 `Asia/Shanghai`；含 `project-brief.md`、`exec-plan.md`、`review.md`、`pipeline-summary.md`、`meta.json`）
- Pipeline 最新快照：`.ai/pipeline/latest/`（含 `pipeline-summary.md`、`run.json`）
- Team 产物目录：`.ai/team/runs/<run-id>/`（`run-id` 同样使用北京时间 `Asia/Shanghai`，格式 `YYYYMMDD-HHMMSS-<summary>-<short-hash>`；示例：`20260223-184512-auth-refactor-a1b2c3d4`；含 `agents/*.md`、`team-summary.md`、`meta.json`）
- Team decisions artifacts：`.ai/team/runs/<run-id>/decisions/`（`context-pack.json`、`codex.json`、`gemini.json`、`arbiter.json`）
- Team 最新摘要：`.ai/team/latest/team-summary.md`
- 最终 team summary 由 Gemini 汇总输出（基于 team viewpoints）。
- `OMO_TEAM_ARBITER_GATE`（`off|soft|strict`）：`off` 关闭 team arbiter gate（兼容旧行为）；`soft`（默认）写入 decisions artifacts 但不阻断；`strict` 在 arbiter 判定 `ask/fail-fast` 时阻断并返回失败状态。

#### flags
- `-h, --help`：顶层命令和各子命令都支持帮助信息
- `--cwd <path>`：`@agent` 快捷语法与全部子命令支持
- `--dry-run`：`chat`、`pipeline`、`team`、`compress`、`resume` 与 `@agent` 支持
- `--no-auto-confirm`：`chat`、`pipeline`、`team`、`resume` 与 `@agent` 支持
- `--stop-after <stage-index>`：仅 `pipeline` 支持
- `--limit <n>`：仅 `history` 支持，默认 `20`
- `--target-agent <claude|codex|gemini>`：仅 `compress` 支持，默认 `codex`
- `--max-chars <n>`：仅 `compress` 支持，默认 `5000`

### 常见问题与排障（troubleshooting）
- `pipeline` 卡在策略检查：先手动运行  
  `./scripts/verify` 与  
  `$HOME/Documents/Code/universal-harness-kit/scripts/agent-policy-stack --tool codex --cwd "$PWD" --strict --strict-profile harness`
- 真实 CLI 调用失败：先验证 `claude/codex/gemini` 在当前 shell 可执行并已登录，再重跑命令
- 需要快速清理残留 worktree：执行 `python omo.py cleanup`

---

## English (EN)

### Overview
`oh-my-orch` is a multi-agent CLI orchestrator that coordinates `Claude Code`, `Codex CLI`, and `Gemini CLI` for one task.  
It persists truth-source artifacts in `.ai/*` and runtime state in `.omo/pipeline-state.json`, enabling resume/cleanup workflows.

### Usage
#### prereqs
- Python 3.11+ (template uses `.venv`)
- Installed and authenticated CLIs: `claude`, `codex`, `gemini` (for non-`--dry-run`)
- Environment bootstrapped with `./scripts/setup`

#### setup
```bash
./scripts/setup
```

#### exact commands
```bash
# Print complete CLI help
python omo.py --help

# Chat mode (@agent shorthand)
python omo.py @claude "Design an auth module" --dry-run
python omo.py @codex chat "Execute the refactor plan" --cwd . --no-auto-confirm

# Chat mode (explicit subcommand)
python omo.py chat codex "Execute the refactor plan" --dry-run

# Pipeline mode
python omo.py pipeline "Add user authentication" --dry-run

# Team mode
python omo.py team "Microservice vs monolith?" --dry-run

# State and history
python omo.py status --cwd .
python omo.py history --limit 30

# Compress/reset/resume/cleanup
python omo.py compress --target-agent codex --max-chars 4000 --dry-run
python omo.py reset --cwd .
python omo.py resume --dry-run
python omo.py cleanup --cwd .
```

#### examples
```bash
# Stop after stage1 for debugging
python omo.py pipeline "Implement audit logging" --dry-run --stop-after 1

# Control compress output length (default: 5000)
python omo.py compress --target-agent gemini --max-chars 2000 --dry-run

# Live mode (requires working CLIs and deps)
python omo.py pipeline "Integrate SSO login"
```

#### I/O
- Input: CLI args (task text, mode, `--dry-run`, `--stop-after`, etc.)
- Output: JSON payload to stdout
- State files: `.omo/pipeline-state.json`
- Session files: `.omo/session.jsonl`, `.omo/chat-history.jsonl`
- Key artifacts (compat paths): `.ai/project-brief.md`, `.ai/exec-plan.md`, `.ai/review.md`
- Pipeline artifacts: `.ai/pipeline/runs/<run-id>/` (new directory per run; `run-id` format `YYYYMMDD-HHMMSS-<summary>-<short-hash>` in Beijing time `Asia/Shanghai`; includes `project-brief.md`, `exec-plan.md`, `review.md`, `pipeline-summary.md`, `meta.json`)
- Latest pipeline snapshot: `.ai/pipeline/latest/` (contains `pipeline-summary.md`, `run.json`)
- Team artifacts: `.ai/team/runs/<run-id>/` (`run-id` also uses Beijing time `Asia/Shanghai` with `YYYYMMDD-HHMMSS-<summary>-<short-hash>`; example: `20260223-184512-auth-refactor-a1b2c3d4`; includes `agents/*.md`, `team-summary.md`, `meta.json`)
- Team decisions artifacts: `.ai/team/runs/<run-id>/decisions/` (`context-pack.json`, `codex.json`, `gemini.json`, `arbiter.json`)
- Latest team summary: `.ai/team/latest/team-summary.md`
- The final team summary is consolidated by Gemini (from team viewpoints).
- `OMO_TEAM_ARBITER_GATE` (`off|soft|strict`): `off` disables the team arbiter gate (legacy-compatible behavior); `soft` (default) writes decisions artifacts without blocking; `strict` blocks and returns failed status on arbiter `ask/fail-fast`.

#### flags
- `-h, --help`: available on the top-level command and every subcommand
- `--cwd <path>`: supported by `@agent` shorthand and all subcommands
- `--dry-run`: supported by `chat`, `pipeline`, `team`, `compress`, `resume`, and `@agent`
- `--no-auto-confirm`: supported by `chat`, `pipeline`, `team`, `resume`, and `@agent`
- `--stop-after <stage-index>`: `pipeline` only
- `--limit <n>`: `history` only, default `20`
- `--target-agent <claude|codex|gemini>`: `compress` only, default `codex`
- `--max-chars <n>`: `compress` only, default `5000`

### Troubleshooting
- Pipeline blocked by policy checks: run  
  `./scripts/verify` and  
  `$HOME/Documents/Code/universal-harness-kit/scripts/agent-policy-stack --tool codex --cwd "$PWD" --strict --strict-profile harness`
- Live CLI failures: verify `claude/codex/gemini` availability and auth in your current shell
- To clean residual worktree quickly: run `python omo.py cleanup`
