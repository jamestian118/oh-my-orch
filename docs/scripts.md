# scripts（脚本说明）

## 中文（ZH）

### prereqs
- python3
- 建议使用虚拟环境（本模板使用 .venv）

### setup
```bash
./scripts/setup
```

### exact commands
```bash
./scripts/dev
./scripts/format
./scripts/lint
./scripts/test
./scripts/arch-check
./scripts/verify
./scripts/live-smoke
./scripts/finalize-artifacts dry-run
./scripts/milestone-finalize
./scripts/publish
```

### examples
```bash
# 本地开发
./scripts/dev

# 最小验证（milestone/stop/切换 CLI 前）
./scripts/verify

# 最小 live smoke（只做检查，不触发真实 chat）
./scripts/live-smoke --dry-run

# 在 verify 中启用 live smoke（默认关闭）
OMO_ENABLE_LIVE_SMOKE=1 ./scripts/verify
```

### I/O
- 输入：通常为命令行参数（`./scripts/dev` 会原样透传 `"$@"` 给 `python omo.py`）
- 输出：stdout/stderr；失败返回非 0

### flags
- 无统一 flags；若后续为某脚本新增 flags，必须同步更新本文档（中英双语）

### dev
- 启动本地开发入口（`omo.py`）
- 实际执行顺序：
  - `source .venv/bin/activate`
  - `python omo.py "$@"`

### format
- 格式化代码

### lint
- 静态检查代码

### test
- 运行测试套件并启用 coverage gate（`>=75%`）
- 当前参数：`--cov=lib --cov=src --cov=omo --cov-report=term-missing --cov-report=xml --cov-fail-under=75`
- 产物：`coverage.xml`

### verify
- 最小验证入口；先校验 `.harness` 存在，不存在则立即失败
- 顺序执行并汇总状态：`format -> lint -> test -> arch-check -> docs-check -> secrets-check -> gc --strict`
- 可选 live smoke：仅当 `OMO_ENABLE_LIVE_SMOKE=1` 时追加执行 `./scripts/live-smoke`；默认打印 skip 信息且不阻断
- 即使某一步失败，仍会继续后续步骤并在退出时写入 `.ai/verify-log.json`（含 `run_id/spans/overall`）
- 最终输出：全部通过打印 `[verify] OK`；任一步失败打印 `[verify] FAIL` 并以非 0 退出

### live-smoke
```bash
./scripts/live-smoke
./scripts/live-smoke --dry-run
./scripts/live-smoke --timeout 45
```
- 目标：提供最小 live path 验证，降低上游 CLI 漂移风险
- 检查项：
  - `claude/codex/gemini` binary 快速探测（优先 `--version`，失败回退 `-h`）
  - 一条最小 live 路径：`python omo.py pipeline "live smoke ping" --stop-after 0 --no-auto-confirm`（带 timeout）
- 输出：machine-readable JSON，至少包含 `checks`、`ok`、`reason` 字段
- 常用环境变量：
  - `OMO_LIVE_SMOKE_TIMEOUT_SEC`：live 路径 timeout（默认 60 秒）
  - `OMO_LIVE_SMOKE_PROBE_TIMEOUT_SEC`：binary probe timeout（默认 5 秒）
  - `OMO_LIVE_SMOKE_PROMPT`：覆盖默认 prompt（`live smoke ping`）

### finalize-artifacts
```bash
./scripts/finalize-artifacts dry-run
./scripts/finalize-artifacts confirm --approved-by “$USER”
./scripts/finalize-artifacts apply --token “<confirm-token>”
```
- Artifact 清理闸门（方案 2）：先生成 plan，再基于确认文件执行删除
- `dry-run`：默认扫描 `.artifacts`、`test-results`、`scripts/.tmp` 与 `.ai/tmp-scripts`，仅输出候选不删除
- `confirm`：写入 `plan_hash/approved_by/expiry/token`
- `apply`：先跑 verify，再校验 token/expiry/plan hash，仅删除 plan 中且满足 roots + git ignored 的候选
- 审计输出：`.ai/finalize-artifacts.last.json`

### milestone-finalize
```bash
./scripts/milestone-finalize
```
- Milestone 收尾入口：自动执行 verify + finalize-artifacts dry-run
- `CI=true` 或非 TTY：输出”跳过交互清理”，不执行删除
- 交互 TTY：输入 `yes` 后自动执行 confirm + apply；否则保留 artifacts

### publish
```bash
./scripts/publish
```
- 标准发布入口：执行 `sanitize -> classify -> publish -> visibility-verify`
- `publish` 子阶段保留旧行为：`milestone-finalize -> git add/commit -> git push -> gh pr view/create -> gh pr comment`
- `sanitize` 最少包含 secrets-check + 轻量 PII heuristic，`classify` 输出 visibility recommendation 与 reason
- 非 `dry-run` 下有阻断规则：`secrets>0` 阻断发布；`--visibility public` 且 `PII>0` 阻断发布
- 输出 machine-readable 证据：`manifest.json` + `publish-results.json`
- 常用参数：`--visibility <auto|public|private>`、`--dry-run`、`--artifact-root <dir>`、`--skip-finalize`、`--skip-codex-review`

### docs-check
- 确保系统核心文档存在及 scripts/ 下可执行脚本的文档覆盖率

### secrets-check
- 快速的敏感信息扫描

### setup
- 初始化项目依赖和环境

### arch-check
```bash
./scripts/arch-check
```
- 检查 src/ 中是否存在违规 import/from/require tests/ 的情况
- 违规：输出文件名和行号，exit 1
- 无违规：输出 OK，exit 0
- 已集成到 `./scripts/verify` 流程中（test 之后、docs-check 之前）

### gc
```bash
./scripts/gc
```
- 抗熵检查入口，扫描项目中违反 golden principles 的 drift
- 扫描边界：按各检查项的目标路径扫描；全仓 grep 类检查会排除 runtime artifacts（`.ai/team/`、`.ai/team/runs/`、`.ai/team/latest/`、`.ai/pipeline/runs/`、`.ai/pipeline/latest/`）
- 检查 1：scripts/ 下每个可执行脚本是否在 docs/scripts.md 中有记录
- 检查 2：裸 TODO（不含 issue 编号或截止日期）
- 检查 3：docs/ 中是否混入动态进度（日期模式）
- 非阻断：始终 exit 0，输出 drift report
- CI 定时运行：.github/workflows/gc.yml

### query-logs
```bash
./scripts/query-logs                  # 显示最近一次 verify 结果摘要
./scripts/query-logs --tail 20        # 显示日志最后 20 行
./scripts/query-logs --since YYYY-MM-DD
./scripts/query-logs --grep ERROR
```
- 查询 .ai/verify-log.json 历史和 .ai/logs/ 下的应用日志
- 无参数时显示最近一次 verify 结果摘要（表格形式）

### dev-with-telemetry
```bash
./scripts/dev-with-telemetry
```
- 包装 `./scripts/dev`，自动捕获 stdout/stderr 到 `.ai/logs/dev.log`，带时间戳
- 退出时输出日志路径

### troubleshooting
- verify 失败：先看是哪一步失败（format/lint/test/arch-check/docs-check/secrets-check/gc/live-smoke），若是 coverage gate 未达标，补测试后重新运行 verify
- live-smoke 失败：先跑 `./scripts/live-smoke --dry-run` 区分 binary 问题与真实 live 路径问题，再决定是否开启 `OMO_ENABLE_LIVE_SMOKE=1`
- secrets-check 误报：优先改为更精确规则或引入专用 secrets 扫描工具（仍通过 scripts/ 与 CI 入口统一调用）

---

## English (EN)

### prereqs
- python3
- virtual environment recommended (this template uses .venv)

### setup
```bash
./scripts/setup
```

### exact commands
```bash
./scripts/dev
./scripts/format
./scripts/lint
./scripts/test
./scripts/arch-check
./scripts/verify
./scripts/live-smoke
./scripts/finalize-artifacts dry-run
./scripts/milestone-finalize
./scripts/publish
```

### examples
```bash
# local dev
./scripts/dev

# minimal verification (before milestone/stop/CLI switch)
./scripts/verify

# minimal live smoke (checks only, no real chat)
./scripts/live-smoke --dry-run

# enable live smoke inside verify (disabled by default)
OMO_ENABLE_LIVE_SMOKE=1 ./scripts/verify
```

### I/O
- Input: usually CLI args (`./scripts/dev` forwards `"$@"` to `python omo.py` as-is)
- Output: stdout/stderr; non-zero exit on failure

### flags
- No unified flags. If any script gains flags, this doc must be updated (bilingual).

### dev
- Starts the local development entrypoint (`omo.py`)
- Runtime sequence:
  - `source .venv/bin/activate`
  - `python omo.py "$@"`

### format
- Formats the codebase

### lint
- Runs static code analysis

### test
- Runs the test suite with a coverage gate (`>=75%`)
- Current args: `--cov=lib --cov=src --cov=omo --cov-report=term-missing --cov-report=xml --cov-fail-under=75`
- Artifact: `coverage.xml`

### verify
- Minimal verification entrypoint; first checks `.harness`, and fails immediately if missing
- Runs and aggregates the exact sequence: `format -> lint -> test -> arch-check -> docs-check -> secrets-check -> gc --strict`
- Optional live smoke: only runs `./scripts/live-smoke` when `OMO_ENABLE_LIVE_SMOKE=1`; otherwise prints a skip message and does not block by default
- Even if one stage fails, it still executes remaining stages and writes `.ai/verify-log.json` on exit (`run_id/spans/overall`)
- Final output: prints `[verify] OK` when all pass; prints `[verify] FAIL` and exits non-zero if any stage fails

### live-smoke
```bash
./scripts/live-smoke
./scripts/live-smoke --dry-run
./scripts/live-smoke --timeout 45
```
- Purpose: add a minimal live-path guard to reduce upstream CLI drift risk
- Checks:
  - quick binary probes for `claude/codex/gemini` (prefer `--version`, fallback to `-h`)
  - one minimal live path: `python omo.py pipeline "live smoke ping" --stop-after 0 --no-auto-confirm` with timeout protection
- Output: machine-readable JSON with at least `checks`, `ok`, and `reason`
- Common env vars:
  - `OMO_LIVE_SMOKE_TIMEOUT_SEC`: timeout for live path (default: 60s)
  - `OMO_LIVE_SMOKE_PROBE_TIMEOUT_SEC`: timeout for binary probes (default: 5s)
  - `OMO_LIVE_SMOKE_PROMPT`: override default prompt (`live smoke ping`)

### finalize-artifacts
```bash
./scripts/finalize-artifacts dry-run
./scripts/finalize-artifacts confirm --approved-by "$USER"
./scripts/finalize-artifacts apply --token "<confirm-token>"
```
- Artifact cleanup gate (option 2): generate a plan first, then delete only with explicit confirmation
- `dry-run`: scans `.artifacts`, `test-results`, `scripts/.tmp`, and `.ai/tmp-scripts` by default, prints candidates only
- `confirm`: writes `plan_hash/approved_by/expiry/token`
- `apply`: runs verify first, validates token/expiry/plan hash, then deletes only planned candidates that are inside roots and git ignored
- Audit output: `.ai/finalize-artifacts.last.json`

### milestone-finalize
```bash
./scripts/milestone-finalize
```
- Milestone closeout entry: runs verify and finalize-artifacts dry-run automatically
- If `CI=true` or non-TTY: prints "跳过交互清理" and skips deletion
- If interactive TTY: type `yes` to run confirm + apply, otherwise keep artifacts

### publish
```bash
./scripts/publish
```
- Standard publish entrypoint: `sanitize -> classify -> publish -> visibility-verify`
- `publish` stage keeps existing behavior: `milestone-finalize -> git add/commit -> git push -> gh pr view/create -> gh pr comment`
- `sanitize` includes secrets-check + lightweight PII heuristic; `classify` emits visibility recommendation and reason
- Non-`dry-run` blocking rules: publish is blocked when `secrets>0`; publish is also blocked when `--visibility public` and `PII>0`
- Machine-readable evidence outputs: `manifest.json` + `publish-results.json`
- Common flags: `--visibility <auto|public|private>`, `--dry-run`, `--artifact-root <dir>`, `--skip-finalize`, `--skip-codex-review`

### docs-check
- Ensures core documentation exists and executable scripts under scripts/ are documented

### secrets-check
- Fast heuristic secrets scanning

### arch-check
```bash
./scripts/arch-check
```
- Checks whether src/ contains any forbidden import/from/require usage from tests/
- Violation found: prints file name and line number, exit 1
- No violation: prints OK, exit 0
- Integrated into `./scripts/verify` pipeline (after test, before docs-check)

### gc
```bash
./scripts/gc
```
- Anti-entropy check entry point; scans the project for drift against golden principles
- Scan boundary: each check runs on its target paths; repo-wide grep-style checks exclude runtime artifacts (`.ai/team/`, `.ai/team/runs/`, `.ai/team/latest/`, `.ai/pipeline/runs/`, `.ai/pipeline/latest/`)
- Check 1: every executable script in scripts/ is documented in docs/scripts.md
- Check 2: bare TODOs (missing issue number or deadline)
- Check 3: dynamic progress dates leaked into docs/
- Non-blocking: always exit 0, outputs drift report
- Scheduled CI: .github/workflows/gc.yml

### query-logs
```bash
./scripts/query-logs                  # show latest verify result summary
./scripts/query-logs --tail 20        # show last 20 lines from logs
./scripts/query-logs --since YYYY-MM-DD
./scripts/query-logs --grep ERROR
```
- Queries .ai/verify-log.json history and application logs under .ai/logs/
- With no args, displays the latest verify result summary in table format

### dev-with-telemetry
```bash
./scripts/dev-with-telemetry
```
- Wraps `./scripts/dev`, captures stdout/stderr to `.ai/logs/dev.log` with timestamps
- Prints log path on exit

### troubleshooting
- If verify fails: identify the failed stage (format/lint/test/arch-check/docs-check/secrets-check/gc/live-smoke), fix it, then rerun verify.
- If live-smoke fails: run `./scripts/live-smoke --dry-run` first to separate binary probe failures from real live-path failures, then decide whether to enable `OMO_ENABLE_LIVE_SMOKE=1`.
- If secrets-check false-positives: tighten patterns or adopt a dedicated secrets scanner (still invoked via scripts/ and CI).
