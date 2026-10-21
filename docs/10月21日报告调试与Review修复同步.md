# 10 月 21 日报告、调试与 Review 修复同步

被测基线：WhaleTestPro `0826e5d`。APITest 原基线：`149eb19`。本文记录提交前完成的源码同步与验证；未部署服务，也未修改 Excel 的人工记录。

## 核对结论

旧脚本的大多数公开协议仍兼容，不需要整体重写。需要补齐的是主仓 10 月 19 日后新增的 9 项 HTTP 操作，以及请求/断言封装和跨仓收集的三处适配：

- `POST /scenarios/{id}/debug`、`POST /scenarios/{id}/debug/extract`。
- `GET/POST /reports/folders`、`PUT/DELETE /reports/folders/{id}`。
- `POST /reports/executions/move`、`POST /reports/executions/delete`、`DELETE /reports/executions/{id}`。
- 公共请求封装原来只有 10 秒超时；同步运行链路现在允许 600 秒，普通 GET/配置请求保持原超时，显式 `timeout=` 优先。
- 独立 JSON 值断言不再让 `true == 1`、`false == 0` 或嵌套结构混淆；字段/响应整体类型检查拒绝布尔值冒充整数，缺失字段不能冒充 null。测试判定不导入主仓比较函数。
- `tests/__init__.py` 与统一限定导入避免后端的同名 `tests` 包抢占 APITest 离线契约。

按真实 OpenAPI 统计，主仓现为 **116 项 HTTP 操作**。此前 107 项记录是 10 月 18 日历史基线；单步调试新增 2 项，报告管理新增 7 项。

## 新增 HTTP 与离线映射

文件：`testcases/test_core/test_report_debug_delta.py`；离线入口：`tests/test_report_debug_delta_contract.py`。两边的参数化数量由自动检查核对。

| 测试函数 | 场景数 | 关键检查 |
|---|---:|---|
| report_folder_create_rename_duplicate_and_delete | 1 | 创建、重命名、大小写归一化重复 409、列表及删除 |
| report_folder_name_validation | 3 | 空串、空白、超长名称 422 且不落库 |
| report_move_between_folders_and_folder_delete_preserves_evidence | 4 | 用例/场景/套件/回归四种根报告；移动两次、旧目录清空、删除目录保留证据 |
| report_delete_removes_derived_evidence_preserves_cases | 8 | 四类报告 × 单条/批量删除；派生明细删除、来源用例保留 |
| report_selection_is_atomic_and_project_scoped | 1 | 有效与不存在 ID 混合选择不部分写入，外项目访问拒绝 |
| report_write_permission_toggle | 1 | 普通成员读取、禁止写入、打开/关闭 report.write 后即时生效 |
| step_debug_and_cached_extraction_do_not_save_assets_or_reports | 1 | 草稿不保存、不写报告，响应保留，提取缓存不重发 HTTP |
| failed_step_debug_keeps_response_or_explains_missing_input | 2 | 缺变量不发请求，状态断言失败仍能查看响应 |
| debug_requires_environment_and_rejects_foreign_scope | 1 | 必选环境、跨环境/项目拒绝、无效会话 409 |
| case_json_assertion_type_contract | 2 | 实际 JSON 数字 0 不满足 false，但满足 0 |
| 合计 | **24** | 本轮没有伪造旧设计编号或已执行状态 |

这些 HTTP 脚本沿用核心回归的写入开关，CI 原有 `testcases/test_core` 执行入口会收集它们，不需要另加一次运行。清理只使用 `CoreWorkspace` 本轮登记的团队和项目。

## 验证与边界

完整离线门禁：**257 passed，1 条已有 Starlette/httpx 弃用警告**，45.79 秒完成。相对于原 215 项，新增封装测试 17 项、24 项真实路由映射及 1 项映射一致性检查，全部通过。

HTTP 集合为 **385 项**（361 + 24，26 个脚本文件）；仅收集，不运行 HTTP fixture。实际 `app.openapi()` 为 116 项操作。`git diff --check` 通过，主仓工作区保持干净，Excel 未改动。没有把收集数量、离线通过数量当成部署环境的验收结果。

离线验证使用实际后端路由、独立 SQLite 和内存调试缓存；HTTP 传输、鉴权身份及下游响应被受控替代，阻断实际 HTTP、Redis、MySQL 和外部命令。启动器禁止读取两仓实际 `.env`。这不能替代真实 Redis 并发/TTL、MySQL 锁竞争、消息队列或 Locust 的验收；这些内部修复由主仓的对应测试验证。

本轮未连接云端、启动 Docker、发送 Webhook 或对 WhaleShop 发压测。Excel 仍为 361 项历史快照；新增 24 项尚未同步进去，没有改写任何执行结果。GitHub Actions 也不能据本地离线通过而宣称通过。
