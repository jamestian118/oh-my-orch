# .ai/handoff.md

> 规则：动态进度只写在这里；不要把动态内容写进 docs/ 或长期规范文件。

## 最新交接（追加在最上方）
- Date：2026-02-27 20:13:25 (Asia/Shanghai)
- Branch：ai/20260227-phase0-upgrade
- Commit：de36321
- git status（摘要）：`M README.md`、`M lib/context.py`、`M lib/integrations.py`、`M lib/orchestrator.py`、`M lib/orchestrator_pipeline.py`、`M tests/test_pipeline_resume_cleanup.py`、`M tests/test_step3_to_step5_orchestrator.py`、`M tests/test_step6_integrations.py`、`?? lib/csm_driver.py`
- 最小验证命令：`./scripts/verify`、`./scripts/secrets-check`
- 关键输出摘录（key output excerpts）：
  - `./scripts/verify -> [verify] OK`
  - `pytest -> 39 passed in 23.49s`
  - `./scripts/secrets-check -> [secrets-check] OK`
  - `pipeline 并发冲突路径返回: pipeline already running (pid=..., run_id=...)`

### Done
- 完成 1.14：`lib/integrations.py` 移除内联 `driver = """..."""`，新增独立驱动文件 `lib/csm_driver.py`，`CSMIntegration` 改为 `python <driver.py> <json payload>` 调用。
- 完成 1.15：`lib/orchestrator_pipeline.py` 新增 `pipeline.lock + pipeline.pid` 互斥机制，基于 `fcntl.flock(LOCK_EX|LOCK_NB)` 拒绝并发 pipeline run，并返回持有者 `pid/run_id`。
- 新增测试：
  - `tests/test_step6_integrations.py::test_csm_integration_invokes_external_driver_file`
  - `tests/test_pipeline_resume_cleanup.py::test_pipeline_rejects_concurrent_run_when_lock_is_held`
- 双语 usage 文档同步：`README.md` 补充 pipeline 并发锁文件与排障说明（ZH/EN）。

### Next Steps（3-8 条，按优先级）
1. 提交本阶段改动（1.14 + 1.15 + docs + tests）。
2. 如需保留 crash 现场，可评估在异常退出时选择“保留 pid 文件并附 stale 标记”的策略（当前为成功/失败后清理 pid 文件）。
3. 如需更强可观测性，可在 `status` 命令增加 lock owner 展示（读取 `.omo/pipeline.pid`）。

## 上一交接（2026-02-24 00:46:14）
- Date：2026-02-24 00:46:14 (Asia/Shanghai)
- Branch：ai/20260223-omo-step1-6
- Commit：d0a06db
- git status（摘要）：`M lib/orchestrator_pipeline.py`、`M lib/orchestrator_team.py`、`M omo.py`、`M tests/test_pipeline_run_registry.py`、`M tests/test_team_arbiter_flow.py`、`M tests/test_omo_cli.py`、`M README.md`、`M docs/architecture.md`
- 最小验证命令：`./scripts/verify`
- 关键输出摘录（key output excerpts）：
  - `./scripts/verify -> [verify] OK`
  - `pytest -> 37 passed in 32.62s`
  - `新增 team exit_code + pipeline decisions artifacts（context-pack/stage-results/final-gate）`

### Done
- team 增加 machine-readable `exit_code`（`0/1/42`）并写入 `meta.json`，CLI `omo.py` 优先透传 payload `exit_code`。
- pipeline 增加 `.ai/pipeline/runs/<run_id>/decisions/` 证据链：
  - `context-pack.json`
  - `stage-results.json`
  - `final-gate.json`
- pipeline 返回 payload 新增 `decisions_dir` 与 `decision_files`（非破坏性增量字段）。
- 文档同步：`README.md`、`docs/architecture.md` 补齐 team `exit_code` 与 pipeline decisions artifacts 契约。

### Next Steps（3-8 条，按优先级）
1. 提交本阶段改动（stage3: team exit_code + pipeline decisions artifacts + docs/tests）。
2. 如需更强 machine-readable 语义，可把 team `exit_code` 规则抽到常量模块统一管理。
3. 评估是否在 `pipeline` 也增加 `exit_code` 字段（与 team 统一输出风格）。
4. 若要对外集成 CI/脚本，可补充一条 `jq` 示例，直接消费 `decision_files` 与 `arbiter` 字段。

## 上一交接（2026-02-24 00:38:26）
- Date：2026-02-24 00:38:26 (Asia/Shanghai)
- Branch：ai/20260223-omo-step1-6
- Commit：3f56f0f
- git status（摘要）：`M lib/orchestrator_team.py`、`?? tests/test_team_arbiter_flow.py`、`M README.md`、`M docs/architecture.md`、`M .ai/verify-log.json`
- 最小验证命令：`./scripts/verify`
- 关键输出摘录（key output excerpts）：
  - `./scripts/verify -> [verify] OK`
  - `pytest -> 36 passed in 32.55s`
  - `team arbiter decisions 落盘: context-pack.json/codex.json/gemini.json/arbiter.json(+ask.json when ask=true)`

### Done
- 已提交上一阶段并行成果：`3f56f0f feat(orchestrator): add run registry dual-write and arbiter skeleton`。
- 下一阶段并行推进完成：`decision_arbiter` 接入 team 主流程并返回 `arbiter` 字段。
- 新增 team arbiter 回归测试：`tests/test_team_arbiter_flow.py`（默认 soft 兼容 + strict gate 阻断）。
- 文档契约同步：`README.md`、`docs/architecture.md` 更新 decisions artifacts 与 gate 语义。
- 主线程收口完成：统一 gate 模式 `off|soft|strict`（兼容 `1/true` 视为 `strict`），并修正文档中的 `context-pack.json` 命名。

### Next Steps（3-8 条，按优先级）
1. 提交本阶段改动（team arbiter integration + tests + docs）。
2. 评估是否把 `arbiter.ask=true` 的失败信息进一步映射到 machine-readable `exit_code`。
3. 若要全链路一致，可在 `pipeline` 补同构 decisions artifacts（与 team 对齐）。
4. 视需要把 `strict` gate 扩展为 CLI flag（避免仅靠 env var）。

## 上一交接（2026-02-24 00:24:47）
- Date：2026-02-24 00:24:47 (Asia/Shanghai)
- Branch：ai/20260223-omo-step1-6
- Commit：f7aa258
- git status（摘要）：`M lib/orchestrator_pipeline.py`、`M lib/orchestrator_team.py`、`?? lib/run_registry.py`、`?? lib/decision_arbiter.py`、`?? tests/test_pipeline_run_registry.py`、`?? tests/test_team_run_registry.py`、`?? tests/test_decision_arbiter.py`、`M docs/architecture.md`
- 最小验证命令：`./scripts/verify`
- 关键输出摘录（key output excerpts）：
  - `./scripts/verify -> [verify] OK`
  - `pytest -> 34 passed in 32.16s`
  - `新增 registry: .omo/project.json + .omo/runs/{pipeline,team}/<run_id> + .omo/latest/{pipeline,team}.json`

### Done
- 启用 3 个 worker 子代理并行推进（pipeline registry / team registry / decision arbiter skeleton）。
- 落地 pipeline 双写：在保留 `.ai/pipeline/*` 与现有返回契约前提下，新增 `.omo` 运行登记文件。
- 落地 team 双写：在保留 `.ai/team/*` 与现有返回契约前提下，新增 `.omo` 运行登记文件。
- 新增本地仲裁模块 skeleton：`lib/decision_arbiter.py` + 单测 `tests/test_decision_arbiter.py`，当前未接主流程。
- 新增回归测试：`tests/test_pipeline_run_registry.py`、`tests/test_team_run_registry.py`。
- 主线程整合：`lib/orchestrator_team.py` 去掉并行过渡用 optional import，改为正式强依赖 `run_registry`。

### Next Steps（3-8 条，按优先级）
1. 选择是否把 `lib/decision_arbiter.py` 接入 `team` 主流程（先 dry-run 开关接入更安全）。
2. 若接入主流程，补 `ask`/`fail-fast` 输出契约与 `exit_code` 映射测试。
3. 将 `.ai/team/runs/<run_id>/decisions/*.json`（context/codex/gemini/arbiter）落盘并补 docs 说明。
4. 整理并提交本次并行改动（建议按功能拆 2-3 个 commit，便于回滚）。

## 上一交接（2026-02-23 19:26:00）
- Date：2026-02-23 19:26:00 (Asia/Shanghai)
- Branch：ai/20260223-omo-step1-6
- Commit：f7aa258
- git status（摘要）：`D .ai/design-spec.md`、`M .ai/verify-log.json`、`M docs/architecture.md`、`M docs/quality.md`、`M scripts/arch-check`、`M scripts/verify`、`?? scripts/live-smoke`
- 最小验证命令：`./scripts/verify`
- 关键输出摘录（key output excerpts）：
  - `sanitize/classify: ./scripts/publish --dry-run --visibility public -> secrets=0, pii=0`
  - `git push -u origin master:main -> success`
  - `git push -u origin ai/20260223-omo-step1-6 -> success`
  - `PR: https://github.com/jamestian118/oh-my-orch/pull/1`
  - `@codex review comment: https://github.com/jamestian118/oh-my-orch/pull/1#issuecomment-3944189869`
  - `repo visibility: PUBLIC, default_branch: main`

### Done
- 本地提交完成（2 个 commit）：
  - `9e0ae95` `feat(orchestrator): align pipeline artifacts with team runs and BJT timestamps`
  - `f7aa258` `chore(public): sanitize absolute paths for github publish`
- 发布闭环完成：新建 public 仓库、推送 `main` 与 `ai/...` 分支、创建 PR、发布 `@codex review` 评论。
- public 发布前完成脱敏修复：绝对路径改为 `$HOME`/`Path.home()`，并将 `.ai/pipeline/` 纳入忽略，确保 sanitize `PII=0`。

### Next Steps（3-8 条，按优先级）
1. 与用户确认 `/team` 与 `/pipeline` 的长期职责边界（审查/交付分工）。
2. 如果保留 `scripts/publish` 全自动路径，建议后续给“脏工作区”增加 `--no-commit` 或“仅发布已提交内容”开关。
3. 评估是否把 `master` 分支本地也重命名为 `main`，减少分支认知差异。

## 上一交接
- Date：2026-02-23 19:05:00 (Asia/Shanghai)
- Branch：ai/20260223-omo-step1-6
- Commit：d743ff0
- 重点：完成 pipeline/team 对齐（runs 目录 + 北京时间 + pipeline-summary）。
