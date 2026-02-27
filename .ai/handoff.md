# .ai/handoff.md

> 规则：动态进度只写在这里；不要把动态内容写进 docs/ 或长期规范文件。

## 最新交接（追加在最上方）
- Date：2026-02-27 21:09:58 (CST)
- Branch：ai/20260227-phase0-upgrade
- Commit：46430a5
- git status（摘要）：`M lib/agents.py`、`M lib/bus.py`、`M lib/orchestrator_pipeline.py`、`M tests/test_pipeline_resume_cleanup.py`、`M tests/test_step1_core.py`、`?? lib/protocols.py`
- 最小验证命令：`$HOME/Documents/Code/universal-harness-kit/scripts/agent-policy-stack --tool codex --cwd "$PWD" --strict --strict-profile harness`、`./scripts/verify`、`./scripts/secrets-check`
- 关键输出摘录（key output excerpts）：
  - `agent-policy-stack(strict) -> strict_result=pass`
  - `./scripts/verify -> [verify] OK`
  - `pytest -> 51 passed in 23.57s`
  - `coverage gate -> Required test coverage of 75% reached. Total coverage: 82.18%`
  - `./scripts/secrets-check -> [secrets-check] OK`
  - `non-blocking noise -> verify 末尾仍出现 datetime.UTC traceback（exit code 仍为 0）`

### Done
- 完成 Phase 5 OMO lane 5.1-5.6：
  - 新增 `lib/protocols.py`，定义 `OrchestratorProtocol` 并在 `lib/orchestrator_pipeline.py` 全量替换 `orch: Any`。
  - `run_pipeline` 重构为多子函数编排（主函数 60 行；核心调度函数 46 行；其余 stage helper 均短函数化）。
  - preflight 增加 agent binary 可用性检查（`shutil.which`，缺失时 `blocked` + 落盘持久化 + 返回 `missing_agents`）。
  - `MessageBus.load` 从 `ValueError` 失败改为 `warning + 清空重建`。
  - `CLIAgent` 调用加入指数退避 retry（max 2，0.5s/1.0s）。
  - `cleanup` 增加 `git worktree list --porcelain` 扫描并清理 `omo-sandbox-*` 孤儿 worktree/branch。
- 测试补齐：
  - `tests/test_step1_core.py`：坏 JSONL 重建、CLI retry backoff。
  - `tests/test_pipeline_resume_cleanup.py`：agent binary preflight 阻断、orphan worktree 清理。

### Next Steps（3-8 条，按优先级）
1. 提交本阶段改动（建议 message：`refactor: complete phase5 architecture hardening for omo`）。
2. 后续可选：单独修复 `scripts/verify` 尾部 `datetime.UTC` traceback（当前不影响门禁 exit code）。

- Date：2026-02-27 20:57:12 (CST)
- Branch：ai/20260227-phase0-upgrade
- Commit：f183b52
- git status（摘要）：`M .gitignore`、`M docs/scripts.md`、`M requirements-dev.txt`、`M scripts/test`、`?? tests/test_src_main_and_types.py`
- 最小验证命令：`./scripts/verify`、`./scripts/secrets-check`
- 关键输出摘录（key output excerpts）：
  - `./scripts/verify -> [verify] OK`
  - `coverage gate -> Required test coverage of 75% reached. Total coverage: 79.94%`
  - `pytest -> 47 passed in 23.54s`
  - `./scripts/secrets-check -> [secrets-check] OK`
  - `non-blocking noise -> verify 末尾出现 datetime.UTC traceback（exit code 仍为 0）`

### Done
- 完成 Phase 4 lane 4.11/4.12：
  - 引入 `pytest-cov` 并在 `scripts/test` 启用 coverage gate（`--cov-fail-under=75`）。
  - 覆盖统计范围固定为 `lib + src + omo`，并输出 `term-missing + coverage.xml`。
  - 新增 `tests/test_src_main_and_types.py`，覆盖 `src/main.py` 与 `src/types/boundaries.py`。
  - 同步双语脚本文档 `docs/scripts.md`（test/verify 说明与 coverage 排障）。
  - 更新 `.gitignore` 忽略 `.coverage`/`coverage.xml`，避免每次 verify 产生脏工作区。

### Next Steps（3-8 条，按优先级）
1. 提交本阶段改动（建议 message：`test: add coverage gate and src tests for phase4`）。
2. 若要消除 verify 尾部 traceback，可后续修复 `scripts/verify` 的 `datetime.UTC` 兼容性（不影响当前 gate 结果）。

- Date：2026-02-27 20:44:45 (CST)
- Branch：ai/20260227-phase0-upgrade
- Commit：3d067e5
- git status（摘要）：`M README.md`、`M lib/agents.py`、`M lib/context.py`、`M lib/integrations.py`、`M lib/orchestrator.py`、`M lib/orchestrator_pipeline.py`、`M omo.py`、`M tests/test_omo_cli.py`、`M tests/test_step1_core.py`、`M tests/test_step3_to_step5_orchestrator.py`、`?? lib/logging_config.py`
- 最小验证命令：`./scripts/verify`、`./scripts/secrets-check`
- 关键输出摘录（key output excerpts）：
  - `./scripts/verify -> [verify] OK`
  - `pytest -> 43 passed in 23.54s`
  - `./scripts/secrets-check -> [secrets-check] OK`
  - `pipeline stage 日志: [stage 1/6] ... [stage 6/6]`

### Done
- 完成 Phase 3 OMO 核心任务：
  - 新增 logging 配置模块并支持全局 `--verbose/-v`、`--debug`。
  - pipeline stage 级进度日志输出（`[stage i/6] ...`）。
  - agent 调用结果持久化到 `run_dir/agents/*.json`（`returncode` + `stderr` 前 500 字符）。
  - stage 级 duration 记录到 `stage_results` 与 `meta.json.stage_durations`。
- 双语 usage 文档同步：`README.md` 更新新 flags、日志行为与产物目录说明。
- 测试补齐：CLI flag 转发、stage 日志、agent stderr 500 截断、duration contract、debug subprocess 日志。

### Next Steps（3-8 条，按优先级）
1. 提交当前改动（Phase 3 logging/progress/agent artifacts/duration）。
2. 如需更细粒度指标，可将 stage duration 进一步按子步骤（review/fix loop）拆分并单独入库。
3. 若要统一可观测性，可为 team 流程补充与 pipeline 同构的 stage progress 输出。

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
