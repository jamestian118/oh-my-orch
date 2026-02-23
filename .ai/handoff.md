# .ai/handoff.md

> 规则：动态进度只写在这里；不要把动态内容写进 docs/ 或长期规范文件。

## 最新交接（追加在最上方）
- Date：2026-02-23 19:05:00 (Asia/Shanghai)
- Branch：ai/20260223-omo-step1-6
- Commit：d743ff0
- git status（摘要）：`M .ai/handoff.md`、`M .ai/verify-log.json`、`M .gitignore`、`M README.md`、`M docs/scripts.md`、`M lib/orchestrator.py`、`M scripts/gc`、`M tests/test_step3_to_step5_orchestrator.py`、`?? lib/orchestrator_pipeline.py`、`?? lib/orchestrator_team.py`、`?? .ai/pipeline/`
- 最小验证命令：`./scripts/verify`
- 关键输出摘录（key output excerpts）：
  - `PYTHONPATH=. pytest -q tests/test_step3_to_step5_orchestrator.py tests/test_pipeline_resume_cleanup.py: 10 passed in 0.07s`
  - `./scripts/verify: [verify] OK`
  - `python omo.py pipeline "pipeline 结果闭环验证" --dry-run: run_id=20260223-190435-pipeline-结果闭环验证-2c3762e5`
  - `pipeline summary: .ai/pipeline/runs/<run-id>/pipeline-summary.md 已生成`
  - `python omo.py team "team 北京时间验证" --dry-run: run_id=20260223-190437-team-北京时间验证-c4cee456`
  - `team meta ran_at: 2026-02-23T19:04:37+08:00`

### Done
- Pipeline 工作流对齐 Team 产物模型：
  - 新增每次运行目录：`.ai/pipeline/runs/<run-id>/`。
  - 新增最新快照目录：`.ai/pipeline/latest/`。
  - 新增最终结果产物：`pipeline-summary.md` + `meta.json` + `latest/run.json`。
- run-id 与时间统一改为北京时间（`Asia/Shanghai`）：
  - Pipeline run-id：`YYYYMMDD-HHMMSS-<summary>-<hash8>`。
  - Team run-id 同步改为北京时间，`meta.json.ran_at` 与 state 中 `team.ran_at` 为 `+08:00`。
- 保持兼容性：
  - 根目录 `.ai/project-brief.md/.ai/exec-plan.md/.ai/review.md` 继续保留；同时同步复制到 pipeline run 目录。
- 文档与守护同步：
  - `README.md` 中英 I/O 增加 pipeline runs/latest 与北京时间说明。
  - `docs/scripts.md`、`scripts/gc` 同步将 `.ai/pipeline/runs|latest` 视为 runtime artifacts 排除项。
- 测试补齐：
  - `tests/test_step3_to_step5_orchestrator.py` 增加 pipeline run 目录/summary/meta 断言。
  - Team 测试新增北京时间断言（`+08:00`）。

### Next Steps（3-8 条，按优先级）
1. 若希望“最终结果”更可机器消费，可在 `meta.json` 增加 `final_decision/pass_fail_reason` 字段。
2. 若希望 pipeline/team 命名绝对 ASCII，可给 summary slug 增加 `ascii_only` 开关并更新 README。
3. 若要减少仓库噪声，可决定是否把现有 `.ai/pipeline/*.md` 历史静态文件迁入 `runs/legacy/`。
