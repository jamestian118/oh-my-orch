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
```

### I/O
- 输入：通常为命令行参数（dev 脚本会透传参数，若实现）
- 输出：stdout/stderr；失败返回非 0

### flags
- 无统一 flags；若后续为某脚本新增 flags，必须同步更新本文档（中英双语）

### dev
- 启动本地开发环境

### format
- 格式化代码

### lint
- 静态检查代码

### test
- 运行测试套件

### verify
- 最小验证入口，顺序执行格式化、代码检查、测试、自检与 gc(--strict)

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
- verify 失败：先看是哪一步失败（format/lint/test/arch-check/docs-check/secrets-check/gc），修复后重新运行 verify
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
```

### I/O
- Input: usually CLI args (dev may forward args if implemented)
- Output: stdout/stderr; non-zero exit on failure

### flags
- No unified flags. If any script gains flags, this doc must be updated (bilingual).

### dev
- Starts the local development environment

### format
- Formats the codebase

### lint
- Runs static code analysis

### test
- Runs the test suite

### verify
- Minimal verification entrypoint, sequentially runs format, lint, test, self-checks, and gc (--strict)

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
- If verify fails: identify the failed stage (format/lint/test/arch-check/docs-check/secrets-check/gc), fix it, then rerun verify.
- If secrets-check false-positives: tighten patterns or adopt a dedicated secrets scanner (still invoked via scripts/ and CI).
