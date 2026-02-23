# 执行计划：添加健康检查 API Endpoint / Execution Plan: Add Health-Check API Endpoint

## 目标 / Goal

添加 `GET /api/health` endpoint，返回服务健康状态的 JSON 响应，供运维监控和负载均衡器探活使用。
Add a `GET /api/health` endpoint that returns a JSON health-status response for ops monitoring and load-balancer probes.

## 范围 / Scope

- `src/runtime/` — 路由注册 / route registration
- `src/services/` — 健康检查逻辑 / health-check logic
- `tests/` — 单元测试与 smoke test / unit tests & smoke test
- `docs/` — API 文档更新 / API docs update

## 验收标准 / Acceptance Criteria

- [ ] `GET /api/health` 返回 HTTP 200 + `{"status":"ok","timestamp":"<ISO8601>"}` / returns HTTP 200 with JSON body
- [ ] 服务不健康时返回 HTTP 503 + `{"status":"degraded",...}` / returns 503 when unhealthy
- [ ] 新增 smoke test 覆盖 200 和 503 场景 / smoke test covers both 200 and 503
- [ ] `./scripts/verify` 全绿 / passes green
- [ ] docs/ 中 API 文档已更新 / API docs updated

## 风险 / Risks

| 风险 / Risk | 影响 / Impact | 缓解 / Mitigation |
|---|---|---|
| 无认证保护的 endpoint 暴露内部状态 / Unauthenticated endpoint leaks internals | 中 / Medium | 仅返回 status + timestamp，不暴露版本、依赖或内部 IP / Only return status + timestamp, no version/deps/internal IPs |
| 高频探活请求影响性能 / High-frequency probes impact performance | 低 / Low | 健康检查逻辑轻量化，无 DB 查询 / Keep check lightweight, no DB queries |

## 文件清单 / Files

- [ ] `src/runtime/routes.{ext}` — 注册 `/api/health` 路由 / register route
- [ ] `src/services/health.{ext}` — 新建，健康检查逻辑 / new file, health-check logic
- [ ] `tests/test_health.{ext}` — 新建，单元测试 + smoke test / new file, unit + smoke tests
- [ ] `docs/architecture.md` — 补充 health endpoint 说明 / add health endpoint section

## 验证策略 / Verification Strategy

- [ ] `./scripts/test` 全绿 / all tests pass
- [ ] `./scripts/verify` 全绿 / full verify green
- [ ] 手动 curl 验证：`curl -s http://localhost:<port>/api/health | jq .` 返回预期 JSON / manual curl returns expected JSON
- [ ] 停止依赖服务后再次 curl，确认返回 503 / stop dependency, confirm 503

## 决策点 / Decision Points

- [ ] 是否在响应中暴露详细版本信息（如 git SHA）？建议默认不暴露，需要时通过配置开启 / Expose detailed version info (e.g. git SHA)? Recommend off by default, enable via config if needed
- [ ] 是否需要 readiness 与 liveness 分离（如 K8s 场景）？当前仅实现单一 health endpoint，后续按需拆分 / Separate readiness vs liveness (K8s)? Start with single endpoint, split later if needed
