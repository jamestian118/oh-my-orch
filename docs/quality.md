# Quality（质量）

## 中文（ZH）
### Definition of Done（DoD）
- ./scripts/verify 全绿
- tests 覆盖关键路径（至少 smoke）
- 若行为/接口/脚本使用方式变化：更新 README.md 与 docs（中英双语）
- publish 流程改动必须保留 `sanitize -> classify -> publish -> visibility-verify`，并产出 machine-readable evidence（`manifest.json` + `publish-results.json`）
- 非 dry-run 发布必须满足：`secrets=0`；若目标 visibility 为 `public`，则还需 `PII=0`
### Golden principles（用于抗熵/GC）
- 原则 1：scripts/ 目录下每个脚本必须在 docs/scripts.md 中有对应说明
- 原则 2：src/ 中不允许出现重复的工具函数（同名函数不得出现在多个文件中）
- 原则 3：所有 TODO 注释必须附带 issue 编号或截止日期（格式：TODO(#123) 或 TODO(2025-01-01)）
- 原则 4：docs/ 下的文档不允许包含动态进度信息（动态进度只写 .ai/handoff.md）
- 原则 5：artifacts 生命周期必须走 `finalize-artifacts` 闸门（plan -> confirm -> apply），且仅清理 git ignored 的 `.artifacts/`、`test-results/`、`scripts/.tmp/`、`.ai/tmp-scripts/` 范围

### 规则升级机制（Rule Escalation）
当同一类问题反复出现时，按以下路径逐步升级：
1. 第 1 次发现 → 写到 `.ai/handoff.md` 的 Lessons Learned
2. 第 2 次再出现 → 升级为 `docs/quality.md` 的 golden principle
3. 第 3 次还出现 → 升级为 `scripts/` 的机械化检查并加入 CI gate

### GC（周期性清理）
- 工具入口：./scripts/gc
- CI 定时：.github/workflows/gc.yml（可选）

## English (EN)
### Definition of Done
- ./scripts/verify passes
- tests cover critical paths (at least smoke)
- Update README/docs (bilingual) when behavior/CLI/scripts change
- Publish flow changes must keep `sanitize -> classify -> publish -> visibility-verify` and emit machine-readable evidence (`manifest.json` + `publish-results.json`)
- Non-dry-run publish must satisfy: `secrets=0`; and when target visibility is `public`, `PII=0` is also required

### Golden principles
- Principle 1: Every script in scripts/ must have a corresponding entry in docs/scripts.md
- Principle 2: No duplicate utility functions in src/ (same-named functions must not appear in multiple files)
- Principle 3: All TODO comments must include an issue number or deadline (format: TODO(#123) or TODO(2025-01-01))
- Principle 4: docs/ must not contain dynamic progress info (dynamic progress belongs in .ai/handoff.md only)
- Principle 5: Artifact lifecycle must go through the `finalize-artifacts` gate (plan -> confirm -> apply), and cleanup is limited to git-ignored `.artifacts/`, `test-results/`, `scripts/.tmp/`, and `.ai/tmp-scripts/`.

### Rule Escalation
When the same type of issue recurs, escalate progressively:
1. 1st occurrence → Document in `.ai/handoff.md` under Lessons Learned
2. 2nd occurrence → Promote to a golden principle in `docs/quality.md`
3. 3rd occurrence → Automate as a mechanical check in `scripts/` and add to CI gate

### GC
- Tool: ./scripts/gc
- Scheduled CI: .github/workflows/gc.yml (optional)
