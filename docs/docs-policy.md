# Documentation Policy（文档规范）

## 中文（ZH）
### README.md（项目完成后必须中英双语）
必须包含：
- 项目简介（overview）
- 详细使用方法（setup、exact commands、examples、I/O、flags）
- 常见问题与排障（troubleshooting）

### scripts/helper 变更时的文档要求
只要新增/修改任何可运行脚本或 helper，必须新增/更新一份中英双语 Markdown 使用说明（可放 docs/ 或脚本同级），内容必须覆盖：
- prereqs
- setup
- exact commands
- examples
- I/O
- flags
- troubleshooting

### 子目录级 AGENTS.md
- 当项目包含多个子模块时，可以在子目录放置 `AGENTS.md` 做局部规则补充
- 局部 AGENTS.md 可包含：该模块的专用 test/verify 命令、局部 invariants、局部文档指针
- 优先级：越靠近当前工作目录的 AGENTS.md 优先级越高，会覆盖上层的指导

## English (EN)
### README.md (bilingual required when project is done)
Must include:
- Overview
- Usage (setup, exact commands, examples, I/O, flags)
- Troubleshooting

### When adding/changing runnable scripts or helpers
Add/update a bilingual Markdown doc covering:
- prereqs
- setup
- exact commands
- examples
- I/O
- flags
- troubleshooting

### Subdirectory AGENTS.md
- When a project contains multiple submodules, place an `AGENTS.md` in subdirectories for local rule supplements
- A local AGENTS.md may include: module-specific test/verify commands, local invariants, local doc pointers
- Priority: the closer an AGENTS.md is to the current working directory, the higher its priority — it overrides guidance from parent directories
