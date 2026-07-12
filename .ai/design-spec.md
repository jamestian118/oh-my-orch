# oh-my-orch (omo) — 多智能体编排器设计规格书

## 一、项目概述

多 CLI 智能体编排器，协调 Claude Code、Codex CLI、Gemini CLI 三个工具在同一任务上协作。

- CLI 命令名：`omo`
- 语言：Python 3.11+，纯标准库，零 SDK 依赖
- 调用方式：纯 CLI subprocess（不走 API）
- 交互模式：交互式阶段用 `subprocess.run` 阻塞启动 CLI，CLI 退出后自动继续下一阶段
- 始终在同一个终端窗口，不开新窗口

## 二、三个 CLI 的角色分工

| 角色 | CLI | 核心优势 | 职责 |
|------|-----|---------|------|
| 神经系统 | Gemini (1M window) | 最大 context、最低成本 | 上下文压缩(独占) + 全局分析 + Review(conductor) |
| 大脑 | Claude (200K, 最强推理) | 架构设计、精细推理 | 方案设计(agent team) + 最终审查 |
| 双手 | Codex (128K, 强执行力) | 并行执行、批量修改 | 并行实现(多子代理) + 并行修复 |

## 三、用户界面

```bash
# Chat 模式
omo @claude "设计一个 REST API 方案"
omo @gemini "分析这段代码的性能瓶颈"
omo @codex "执行上面的重构方案"

# Pipeline 模式
omo pipeline "给项目添加用户认证"

# Team 模式
omo team "微服务还是单体？"

# 辅助命令
omo status          # 当前 session 状态
omo history         # MessageBus 历史
omo compress        # 手动触发 Gemini 压缩
omo reset           # 清空当前 session
omo resume          # 断点续传
omo cleanup         # 清理残留 worktree
```

## 四、Pipeline 模式详细流程

### 阶段 0: Gemini 项目分析（非交互，必选）

- 调用：`gemini -p "{prompt}"` 非交互模式
- 产出：`.ai/project-brief.md`（项目结构、技术栈、与任务相关的代码）
- 利用 1M 窗口读取整个项目

### 阶段 1: Claude 方案设计（交互式）

- 注入方式：先 `claude -p "{initial_prompt}" --output-format json` 创建会话获取 session_id，再 `claude --resume {session_id}` 进入交互
- 初始 prompt 包含："读取 .ai/project-brief.md，启用 agent team 并行探索方案，讨论完毕后将最终方案写入 .ai/exec-plan.md"
- 用户在 Claude 会话中持续讨论（多轮），exit 退出后编排器自动继续
- 产出：`.ai/exec-plan.md`（标准化格式）

### 阶段间: 用户确认 + Gemini 压缩

- 编排器检查 `.ai/exec-plan.md` 是否存在
  - 不存在 → Gemini fallback 从 handoff 提取，或重新进入 Claude
- 显示方案摘要，用户确认 `[Y/n/edit]`
- Gemini -p 压缩 handoff 为 ~3K tokens 辅助摘要（辅助性，丢了不影响）

### 阶段 2: Codex 并行执行（交互式，worktree 中）

- 编排器创建 worktree：`git worktree add .omo/sandbox -b omo-sandbox-{timestamp}`
- 调用：`codex "{initial_prompt}"` 在 worktree 目录中启动
- 初始 prompt 包含："{压缩摘要} 完整方案在 .ai/exec-plan.md，严格按此执行。启用多 agent 子代理并行实现。"
- 用户观察执行过程，exit 退出后编排器继续
- 产出：worktree 中的代码变更（git diff）

### 阶段 3: Gemini conductor Review（交互式，worktree 中）

- 调用：在 worktree 目录中启动 `gemini` 交互式会话
- 初始 prompt："读取 .ai/exec-plan.md 了解方案意图。使用 conductor 扩展来 review 当前项目。结果写入 .ai/review.md"
- 触发方式：`/conductor:review` 斜杠命令 或 自然语言
- Conductor 三阶段：1)分析(list_directory+read_file+codebase_investigator) 2)评估(子代理多维度审查) 3)输出报告
- 产出：`.ai/review.md`（结构化 issue 列表）

#### Gemini Conductor 使用细节

- 触发方式：`/conductor:review` 斜杠命令 或 自然语言 "使用 conductor 扩展来 review 当前项目"
- 触发前必须先 cd 到目标项目目录（即 worktree 目录）
- Conductor 内部三阶段流程：
  1. 分析阶段：自动调用 list_directory、read_file、codebase_investigator 扫描项目
  2. 评估阶段：利用子代理 (Sub-agents) 对代码模式、潜在 Bug、架构问题多维度审查
  3. 输出报告：在对话中输出，或将重构建议写入 `~/.gemini/tmp/zhuanz/plans/`
- Conductor 自带代码扫描能力，不需要编排器把 diff 塞进 prompt
- 如果 Conductor 将建议写入 plans 目录，需要用户确认后才执行

### 阶段 4: Codex 并行修复（交互式，worktree 中）

- 调用：`codex "{prompt}"` 在 worktree 目录中启动
- 初始 prompt："读取 .ai/review.md，启用多 agent 子代理并行修复所有 blocking issues。"
- 产出：修复后的代码变更

### 阶段 5: Claude 最终审查 + 验收

- 先跑 `scripts/verify`（UHK 验收闸门）
- 再调用 `claude -p` 非交互审查：对照 exec-plan.md + review.md + git diff
- 通过 → merge worktree → 完成
- 不通过 → 回阶段 4（最多 2 次循环，超过交给用户 [R/M/S/Q]）

## 五、Team 模式详细流程

1. 阶段 0: Gemini -p 项目分析简报（同 Pipeline）
2. 同时启动三个交互式会话（依次 exec，每个退出后启动下一个）：
   - Claude（agent team）："从架构设计和长期维护角度讨论"
   - Codex（多子代理）："从实现复杂度和开发效率角度分析"
   - Gemini（conductor）："从成本、性能、团队规模角度分析"
3. 三个 CLI 各自 /handoff 后退出
4. 阶段间: Gemini -p 压缩三份 handoff 为对比表
5. Claude 做最终总结（综合推理最强）

## 六、Chat 模式

- `omo @claude "prompt"` → 启动 Claude 交互式会话，注入 prompt + MessageBus 历史作为 context
- 切换 agent 时自动 handoff：MessageBus 内存传递（热 handoff）+ handoff-bundle 快照（冷 handoff 备份）
- 累积 context 超过 HARD_LIMIT 时自动触发 Gemini -p 压缩

### Gemini 压缩层详细设计

Gemini 作为 context 压缩器的工作方式：

调用方式：`gemini -p "{压缩 prompt}"` 非交互模式

压缩输出的标准格式：
1. 任务目标（一句话）
2. 已做的关键决策及理由（bullet list）
3. 当前进度和未完成项
4. 代码变更摘要（文件名 + 改动要点）

压缩 prompt 是目标感知的——根据下一个 agent 调整侧重：
- 给 Codex：侧重"改什么文件、改成什么样、验收标准"
- 给 Claude：侧重"设计决策、约束条件、风险点"
- 给 Gemini review：侧重"原始方案意图、变更范围、关注点"

两层保障机制：
- 内存级 MessageBus（热 handoff，快）：编排器内部 agent 切换时使用
- cli-handoff-bundle 快照文件（冷 handoff，持久可恢复）：编排器崩溃后恢复用

## 七、Context 预算机制

动态百分比计算，按目标 agent 的可用窗口：

```
AGENT_PROFILES = {
    "claude": {"window": 200_000, "overhead": 18_000},
    "gemini": {"window": 1_000_000, "overhead": 5_000},
    "codex":  {"window": 128_000, "overhead": 15_000},
}

SOFT_RATIO      = 0.15     # 可用窗口的 15%，开始警告
HARD_RATIO      = 0.25     # 可用窗口的 25%，强制压缩
ABS_CAP         = 50_000   # 绝对上限（防 lost-in-the-middle + 成本控制）
COMPRESS_TARGET = 5_000    # 压缩后目标大小
```

实际限制值：
- Claude: soft=27K, hard=45K
- Gemini: soft=50K(capped), hard=50K(capped)
- Codex: soft=17K, hard=28K

Token 估算用字符数粗估：`len(text) // 3`

### 预算演进记录

初版使用固定值（SOFT=12K, HARD=20K, CODEX=10K, COMPRESS=2K），后经分析发现：
- 固定 20K 对 Claude 200K 窗口只用了 11%，对 Gemini 更是浪费 98%
- COMPRESS_TARGET=2K 太小，复杂架构讨论压缩后会丢失关键技术细节（接口签名、数据结构等）
- Codex 128K 是真正瓶颈，但旧方案 10K 也偏保守

改为动态百分比后，每个 agent 都能充分利用自己的窗口。ABS_CAP=50K 不是因为窗口不够，而是防止 lost-in-the-middle 注意力下降 + 成本线性增长。

## 八、信息传递机制

核心原则：**关键信息通过结构化文件传递（无损），压缩只提供辅助上下文（有损但不影响执行）**。

### 标准化产出文件

| 阶段 | 产出文件 | 写入者 |
|------|---------|--------|
| 阶段 0 | `.ai/project-brief.md` | Gemini |
| 阶段 1 | `.ai/exec-plan.md` | Claude |
| 阶段 2 | git diff（天然存在） | Codex |
| 阶段 3 | `.ai/review.md` | Gemini conductor |

即使 Gemini 压缩完全失败，Pipeline 仍能跑——真相源在文件里，agent 直接读文件。

### exec-plan.md 标准格式

```markdown
# Execution Plan / 实施方案

## Goal / 目标
一句话描述

## Tasks / 任务拆解
### Task 1: [标题]
- Files: `src/auth/handler.py` (新建), `src/routes.py` (修改)
- Change: [具体改什么]
- Depends on: 无
- Parallel: 可以和 Task 2 并行

## Interfaces / 关键接口定义
[具体的函数签名、数据结构、API schema]

## Constraints / 约束条件
[不能改动的文件/接口、性能要求、安全要求]

## Verification / 验收命令
- `scripts/verify`
- `pytest tests/test_auth.py`
```

### review.md 标准格式

```markdown
# Code Review Results

## Blocking Issues (必须修复)
### B1: [标题]
- File: `src/auth/handler.py:42`
- Problem: [具体问题]
- Fix: [具体修改建议]

## Non-blocking Issues (建议修复)
### N1: [标题]
- File: `src/routes.py:15`
- Problem: [具体问题]
- Suggestion: [建议]
```

## 九、可靠性机制

### 文件存在性检查
每阶段完成后检查产出文件，缺失时提供 fallback：
- 重新进入 CLI 补写
- Gemini -p fallback 从 handoff 自动提取

### 断点续传
`.omo/pipeline-state.json` 记录当前阶段和已完成产出，`omo resume` 恢复。

### 循环保护
阶段 4→5 最多重试 2 次，超过后交给用户 `[R]重试 / [M]手动修复 / [S]跳过 / [Q]退出`。

### Worktree 管理
- Pipeline 启动时自动检测残留 worktree
- `omo cleanup` 手动清理
- merge 成功后自动删除 worktree

## 十、项目结构

```
oh-my-orch/
├── pyproject.toml
├── omo.py                  # CLI 入口
├── lib/
│   ├── agents.py           # AgentWorker：CLI subprocess 封装
│   ├── bus.py              # MessageBus + JSONL 持久化
│   ├── context.py          # ContextManager：预算 + Gemini 压缩
│   ├── orchestrator.py     # pipeline / team / chat 编排逻辑
│   └── integrations.py     # CSM / UHK / handoff 集成
└── .omo/                   # 运行时状态（项目级，gitignored）
    ├── session.jsonl        # MessageBus 持久化
    ├── budget.json         # token 消耗追踪
    └── pipeline-state.json # 断点续传状态
```

## 十一、集成依赖

```
CSM (claude-session-manager):
  方式：直接 Python import lib.store.SessionStore
  路径：/Users/Zhuanz/Documents/Code/claude-session-manager
  用途：omo history / omo resume / 会话发现

cli-handoff-bundle:
  方式：读取快照文件 + ai_handoff_watch 后台自动生成
  路径：~/Documents/Code/cli-handoff-bundle/_handoff/sessions/
  用途：冷 handoff 备份、崩溃恢复

UHK (universal-harness-kit):
  方式：subprocess 调用 bash 脚本
  路径：/Users/Zhuanz/Documents/Code/universal-harness-kit
  用途：agent-policy-stack 前置检查、scripts/verify 验收
```

## 十二、实施顺序

```
Step 1: agents.py + bus.py       ← 核心骨架
Step 2: context.py               ← 预算 + Gemini 压缩
Step 3: omo.py (Chat 模式)       ← 最小可用
Step 4: orchestrator.py (Pipeline) ← 含 worktree 隔离
Step 5: orchestrator.py (Team)   ← 并行思考
Step 6: integrations.py          ← CSM / UHK 集成
```

## 十三、架构决策记录

### 为什么纯 CLI 不走 API

- 零 API key 管理，零 SDK 依赖
- 三个 CLI 都自带认证（用户已登录）
- CLI 模式下 agent 保留完整工具能力（文件读写、bash 执行）
- 代价是每次调用都是冷启动新 subprocess，但换来了架构简单性

### 为什么用文件传递而非纯压缩

初版设计中 Gemini 压缩是阶段间信息传递的唯一通道（出现 5 次）。后发现风险：
- 压缩是有损的，Claude 设计的方案经 Gemini 压缩后可能丢失接口签名、数据结构等关键细节
- Codex 拿到不完整方案会实现出错

改为"文件即真相源"后：
- 关键信息通过 .ai/exec-plan.md 等文件无损传递
- 压缩降级为辅助上下文（实际只需要 1 处：阶段 1→2 的 handoff 摘要）
- 即使压缩完全失败 Pipeline 仍能跑

### 为什么 subprocess.run 而非 PTY/新窗口

- subprocess.run 继承父进程的 tty，CLI 可以正常接管终端
- CLI 退出后 Python 代码自动继续下一阶段——天然的阶段切换信号
- 不需要 pexpect/pty 管理交互式进程的复杂性
- 始终在同一个终端窗口，用户不用在多窗口间跳转

### 为什么 Team 模式用 Claude 总结而非 Codex

初版设计 Codex 做总结。后发现 Codex 强项是执行不是综合分析，Claude 的推理能力更适合综合三个视角给出结论。

### Handoff 噪声优化（已完成）

在设计过程中对 cli-handoff-bundle 和 CSM 做了噪声优化：
- ai_handoff_watch.py：过滤 Codex 的 developer/system/tool 角色消息、跳过 AGENTS.md 系统注入
- ai_handoff_watch.py：默认参数调整 tail 10→6, excerpt 240→150, full 12000→6000, handoff.md 嵌入 6000→3000
- mcp_server.py：get_session_context 只保留 user/assistant，条数 30→20，截断 2000→1200
- mcp_server.py：get_handoff_snapshot 截断 15000→8000
- 效果：Codex 快照平均从 35KB 降到 ~19KB，CSM MCP 最坏情况从 75KB 降到 ~24KB
