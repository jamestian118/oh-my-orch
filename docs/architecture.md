# Architecture（架构与边界）

## 中文（ZH）
### 目标
- 让代码结构与边界对 agent 可读，并可逐步被 CI/linters 强制（invariants）

### 不变式（Invariants）
- 依赖方向：tests/ 可以 import src/ 与 lib/；src/ 与 lib/ 不可 import tests/；scripts/ 不参与 import（由 `./scripts/arch-check` 自动检测）
- 边界校验：外部输入（HTTP request body、CLI args、env vars、file I/O）必须在入口处做 schema/type 校验
- 外部系统访问：所有外部 HTTP/DB/MQ 调用必须通过 src/clients/ 目录下的统一 client（集中重试/限流/观测）

### 层级模型（Layer Model）
src/ 内部按以下层级组织，依赖只允许从高层指向低层，同层之间不可互相依赖：

| 层级 | 目录 | 允许依赖 |
|------|------|----------|
| 1（最低） | types/ | 无外部依赖 |
| 2 | config/ | types/ |
| 3 | clients/ | types/ config/ |
| 4 | services/ | types/ config/ clients/ |
| 5 | runtime/ | types/ config/ clients/ services/ |
| 6（最高） | ui/ 或 cmd/ | 所有低层 |

由 `./scripts/arch-check` 自动检测违规。

### 边界类型（Boundary Types）
`src/types/` 下定义模块间的数据形状（boundary types）。所有外部输入必须在入口处用 boundary type 校验后再传入内层。参考模板：`src/types/boundaries.*`。

### 验证方式
- 本地：./scripts/verify
- CI：.github/workflows/verify.yml

## English (EN)
### Goals
- Make structure & boundaries legible to agents, enforce via CI/linters (invariants)

### Invariants
- Dependency direction: tests/ may import src/ and lib/; src/ and lib/ must NOT import tests/; scripts/ does not participate in imports (enforced by `./scripts/arch-check`)
- Boundary validation: external inputs (HTTP request body, CLI args, env vars, file I/O) must be validated with schema/type at entry points
- External access: all external HTTP/DB/MQ calls must go through unified clients under src/clients/ (retries/rate-limit/observability centralized)

### Layer Model
Modules under src/ are organized into layers. Dependencies may only point downward (high to low); no same-layer or upward imports allowed.

| Level | Directory | Allowed Dependencies |
|-------|-----------|---------------------|
| 1 (lowest) | types/ | None |
| 2 | config/ | types/ |
| 3 | clients/ | types/ config/ |
| 4 | services/ | types/ config/ clients/ |
| 5 | runtime/ | types/ config/ clients/ services/ |
| 6 (highest) | ui/ or cmd/ | All lower layers |

Enforced by `./scripts/arch-check`.

### Boundary Types
`src/types/` defines data shapes (boundary types) for module interfaces. All external inputs must be validated with boundary types at entry points before passing to inner layers. See template: `src/types/boundaries.*`.

### Verification
- Local: ./scripts/verify
- CI: .github/workflows/verify.yml

## Team Decision Arbiter（Integrated with Gate）
### 中文（ZH）
- 模块：`lib/decision_arbiter.py`（已接入 `team` 主流程）
- 位置：`codex/gemini` 结构化决策产出后、`team-summary` 汇总前，输出 `winner`、`confidence`、`ask`、`conflicts`。
- 决策产物：`.ai/team/runs/<run-id>/decisions/` 下落盘 `context-pack.json`、`codex.json`、`gemini.json`、`arbiter.json`，用于审计与复现。
- Gate 控制：`OMO_TEAM_ARBITER_GATE=off|soft|strict`；默认兼容策略为 `soft`（保留历史输出契约，仅附加 arbiter 决策，不自动阻断），`strict` 才执行 fail-fast 阻断，`off` 完全回退旧行为。

### English (EN)
- Module: `lib/decision_arbiter.py` (wired into the `team` runtime path)
- Placement: after structured `codex/gemini` decisions and before final `team-summary`, returning `winner`, `confidence`, `ask`, and `conflicts`.
- Decision artifacts: `.ai/team/runs/<run-id>/decisions/` persists `context-pack.json`, `codex.json`, `gemini.json`, and `arbiter.json` for auditability and replay.
- Gate control: `OMO_TEAM_ARBITER_GATE=off|soft|strict`; default compatibility strategy is `soft` (keep legacy output contract, append arbiter decisions, no automatic blocking), while `strict` enforces fail-fast blocking and `off` fully falls back to legacy behavior.
