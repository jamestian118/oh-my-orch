# 执行计划：修复 Token 过期认证 Bug / Execution Plan: Fix Token Expiry Auth Bug

## 目标 / Goal

修复认证 token 过期时服务返回 HTTP 500 而非 401 的 bug，确保过期 token 被正确识别并返回标准 401 响应。
Fix the bug where expired auth tokens cause HTTP 500 instead of 401, ensuring expired tokens are correctly identified and return a standard 401 response.

## 范围 / Scope

- `src/services/auth` — 认证中间件 / auth middleware
- `src/clients/` — 客户端 token 校验 / client token validation
- `tests/` — 回归测试 + 边界测试 / regression + edge-case tests

## 验收标准 / Acceptance Criteria

- [ ] 过期 token 请求返回 HTTP 401 + `{"error":"token_expired","message":"..."}` / expired token returns 401 with JSON error
- [ ] 有效 token 行为不变 / valid token behavior unchanged
- [ ] 现有测试全部通过，无回归 / existing tests pass, no regression
- [ ] 新增边界测试：刚过期、远过期、时钟偏移场景 / new edge-case tests: just-expired, long-expired, clock-skew
- [ ] `./scripts/verify` 全绿 / passes green

## 风险 / Risks

| 风险 / Risk | 影响 / Impact | 缓解 / Mitigation |
|---|---|---|
| 修改认证逻辑影响其他 middleware | 高 / High | 仅修改 token 过期分支，不动其他校验路径；改后跑全量测试 / Only modify expiry branch, run full test suite |
| 错误地拒绝有效 token | 高 / High | 新增正向测试确认有效 token 仍通过 / Add positive test confirming valid tokens still pass |
| 时区/时钟偏移导致误判 | 中 / Medium | 使用 UTC 统一比较，允许可配置的 clock skew tolerance / Use UTC, configurable clock-skew tolerance |

## 文件清单 / Files

- [ ] `src/services/auth/middleware.{ext}` — 修复过期 token 异常处理 / fix expired-token error handling
- [ ] `src/services/auth/token.{ext}` — 增加 `TokenExpiredError` 区分 / add `TokenExpiredError` distinction
- [ ] `src/clients/http_client.{ext}` — 确认 401 响应正确传播 / verify 401 propagation
- [ ] `tests/test_auth_expiry.{ext}` — 新建，过期 token 边界测试 / new file, expiry edge-case tests

## 验证策略 / Verification Strategy

- [ ] `./scripts/test` 全绿 / all tests pass
- [ ] `./scripts/verify` 全绿 / full verify green
- [ ] 手动测试：使用过期 token 发请求，确认返回 401 / manual test with expired token, confirm 401
- [ ] 手动测试：使用有效 token 发请求，确认正常通过 / manual test with valid token, confirm success

## 决策点 / Decision Points

- [ ] 是否同时修复 refresh token 逻辑？建议本次仅修复 401 返回，refresh token 作为独立任务 / Fix refresh token logic too? Recommend fixing only 401 return now, refresh token as separate task
- [ ] 是否在 401 响应中包含 `Retry-After` header？建议暂不包含，后续按需添加 / Include `Retry-After` header in 401? Recommend skip for now, add later if needed
