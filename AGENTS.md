# AGENTS.md（Repo-Local Minimal）

## 1) Policy Stack 调用
- 每次进入项目（主 agent + 子 agent）前，先运行：
  `$HOME/Documents/Code/universal-harness-kit/scripts/agent-policy-stack --tool <codex|claude|gemini> --cwd "$PWD" --strict --strict-profile harness`

## 2) Repo 结构（Map）
- `src/`：业务代码
- `tests/`：测试
- `scripts/`：稳定入口脚本
- `docs/`：长期规范与说明
- `.ai/handoff.md`：动态进度与交接（唯一动态记录）

## 3) 最小执行与交接闭环
- Milestone / Stop / CLI 切换前必须运行：`./scripts/verify`
- 其余命令统一查阅：`docs/scripts.md`
- 完成 verify 后追加写入：`.ai/handoff.md`（`branch`、`commit`、`git status` 摘要、验证命令与关键输出、`Done`、`Next Steps`）
