# WhaleTestPro-APITest

针对 [WhaleTestPro](https://github.com/zixuan-come/WhaleTestPro) 接口测试平台的接口自动化测试项目。

以 **httpx 黑盒**方式打被测服务的 HTTP 接口(不 import 被测代码),数据驱动 + 分层封装,pytest 组织用例,Allure 出报告。

另有 `tests/` 离线跨仓契约测试，它会导入旁边的后端真实路由，使用隔离 SQLite；这部分不是实际部署环境的 HTTP 黑盒验收。

## 测试运行模式（2026-10-07 更新）

默认 `pytest` 同时收集离线与集成测试，可按标记选择：

```bash
# 离线门禁：不需要真实账号、Docker 或被测服务；跨仓测试需后端依赖。
python -m pip install -r requirements.txt -r ../WhaleTestPro/requirements.txt
python -m pytest -m offline --reruns 0

# 普通 HTTP 集成回归，不执行真实异步压测。
python -m pytest -m "integration and not async_e2e"

# 完整 HTTP 集成回归，包含 Worker + Locust 真正执行结束的校验。
python -m pytest -m integration
```

后端不在默认相邻目录时，设置 `WHALE_BACKEND_PATH`；找不到后端代码会失败，不会静默跳过门禁。
旧集成子目录执行账号注册自举与测试环境的 Redis 登录限流清理；本次独立核心子目录不清理共享 Redis，另用 3 个新账号和显式写入开关。
完整压测测试需要 app、RabbitMQ、Redis、Celery Worker、Locust Master/Worker；
`WHALE_PERF_BASE_URL` 是从 Locust 容器访问的目标地址，Compose 默认 `http://app:8000`。
本机直跑 Locust 时按实际可达地址修改，不能把宿主机端口误当成容器自己的服务端口。

压测用例不再仅验证入队：会等待 `done`，确认 Celery ID、起止时间、真实请求计数、失败数和过程采样；Worker 缺失或一直 queued 会失败。
CI 设置独立离线门禁，再启动真实 Worker/Locust 执行集成回归。新 CI 配置是否通过，需以 GitHub 实际运行结果为准。

## 核心链路同步（2026-10-10）

新增 `testcases/test_core/`：27 个函数、29 个 HTTP 场景（5 个冒烟），关联完整设计台账的 36 个编号。覆盖接口/用例/链路/场景执行、报告闭环、回归统计、混合套件去重、项目隔离、成员权限开关、引用迁移及删除后的历史保留。详细断言、编号对应和隔离要求见 [核心链路自动化映射](docs/核心链路自动化映射.md)。

核心 HTTP 回归默认跳过，确认是可重置的隔离环境后再显式启用：

```powershell
$env:LOCUST_SKIP_MONKEY_PATCH='1'
$env:WHALE_CORE_ALLOW_WRITES='1'
python -m pytest testcases/test_core --reruns 0 --alluredir=allure-results
Remove-Item Env:\WHALE_CORE_ALLOW_WRITES
```

先检查当前进程及 `.env`：进程环境变量优先，`.env` 只为未设置的变量提供默认值。`WHALE_BASE_URL` 是测试进程访问后端的地址，`WHALE_RUNNER_BASE_URL` 是后端执行引擎访问目标的地址；默认 Compose 分别使用宿主机 8001 和容器内 8000。切换隔离环境前，检查 PowerShell 中遗留的 `WHALE_BASE_URL`、`WHALE_RUNNER_BASE_URL`、`WHALE_PERF_BASE_URL` 和 `WHALE_PERF_FIXTURE_BASE_URL`；若要采用 `.env` 的默认值，可用 `Remove-Item Env:\WHALE_BASE_URL -ErrorAction SilentlyContinue` 移除对应进程变量（其余目标变量同理），再启动新的测试进程。仅清理本轮登记的团队/项目及其资产；由于没有账号删除接口，新注册用户需由隔离测试库的重置流程清理。连续重跑遇到登录 429 时等待限流窗口到期。

截至 2026-10-10，`tests/` 离线门禁记录为 **57 passed**（原有 24 条＋新增 33 条）。新增 33 条包含 29 个核心场景在真实路由、独立 SQLite、模拟鉴权/下游条件下的验证，以及 4 条支撑检查；不是 29 条实际部署环境 HTTP 通过。当时尚未执行实际 HTTP；后续隔离集成结果见下方日期记录。GitHub Actions 未因本地验证而视为通过，Excel 的“未执行”状态没有改写。

## 10 月 17 日接口增量同步（2026-10-18）

新增 `testcases/test_core/test_request_config_delta.py`：8 个函数、16 个 HTTP 场景，补齐接口 Path 参数、临时调试请求配置、用例独立请求配置、按接口筛选及邀请团队名称。沿用核心链路的隔离写入开关和资产清理；前端入口合并及样式改动不扩展接口回归。

这批脚本可由 `tests/test_request_config_delta_contract.py` 在真实路由＋独立 SQLite 上离线校验；本轮不连接当前手工测试环境。范围、逐项检查和执行记录见 [10 月 17 日接口增量同步](docs/10月17日接口增量同步.md)。原 639 条设计台账及历史验收结果保持各自记录，本次新增场景不冒用旧编号。

## 被测系统

WhaleTestPro 由 Docker Compose 独立起,测试代码只依赖其 `BASE_URL`:

```bash
# 在 WhaleTestPro 项目根执行
docker compose up -d --build
```

| 目标 | 地址 |
|------|------|
| 后端 API | http://localhost:8001 |
| Swagger | http://localhost:8001/docs |

鉴权:受保护接口需 `Authorization: Bearer <token>`;项目内接口、用例、环境、场景等资产接口还需 `X-Project-Id`。项目 CRUD 通过路径参数校验项目权限，团队成员接口通过 `team_id` 校验团队权限；健康检查、注册、登录和 Mock 命中路由保持公开。

## 技术栈

| 用途 | 技术 |
|------|------|
| HTTP 客户端 | httpx |
| 测试框架 | pytest |
| 数据驱动 | PyYAML |
| 覆盖率 | pytest-cov |
| 报告 | allure-pytest |

## 目录结构

```
WhaleTestPro-APITest/
├── common/                 # 通用封装
│   ├── request_util.py     # httpx 封装:统一 BASE_URL、默认请求头、超时与日志
│   ├── assert_util.py      # 契约断言:状态、结构、字段类型、错误详情与字段值
│   ├── core_flow.py        # 核心链路编号标签、独立资产准备与清理
│   └── yaml_util.py        # 读取 data/ 下的 YAML
├── config.py               # 服务地址与测试账号配置(从 .env 读)
├── conftest.py             # 全局 fixture:client、登录取 token、项目上下文、清理/自举
├── data/                   # YAML 测试数据(按模块和接口场景拆分)
├── docs/                   # 历史 YAML 台账 Excel + 完整设计编号的核心自动化映射
├── tools/gen_testcase_excel.py # 读 data/*.yaml 生成《接口测试用例》Excel,校验编号一致
├── testcases/              # 按资源/核心链路分目录，不表示全量接口已自动化
│   ├── test_core/          # 本次独立核心回归：执行/报告/隔离/套件/引用迁移
│   ├── test_auth/          # 注册 / 登录 / 登出
│   ├── test_project/       # 项目 CRUD + 角色权限 + 非空项目删除
│   ├── test_team/          # 团队成员查询、搜索、添加、改角色、移除
│   ├── test_interface/     # 接口 CRUD + 分类改名/删除
│   ├── test_case/          # 用例 CRUD + 执行 + 串联
│   ├── test_scenario/      # 场景 CRUD + 执行
│   ├── test_environment/   # 环境 CRUD
│   ├── test_mock/          # Mock CRUD + 动态命中
│   ├── test_schedule/      # 定时任务 CRUD
│   ├── test_perf/          # 压测任务 CRUD + 触发
│   ├── test_contract/      # 跨资源反例:缺头/缺字段/错类型/无 token/更新不存在
│   ├── test_boundary/      # 边界与畸形输入回归(空/超长 name、非法 cron、负并发)
│   ├── test_system/        # /health/live、/health/ready + /metrics
│   ├── test_report/        # 场景报告父记录与步骤明细
│   └── test_misc/          # 报告 / 回归 / demo 订单 / 流量录制
├── pytest.ini              # 用例发现规则、addopts
├── .github/workflows/ci.yml# CI:起被测全栈 → 跑黑盒回归 → 传 Allure 产物
├── requirements.txt
└── README.md
```

## 用例台账(Excel)

`docs/WhaleTestPro接口测试用例.xlsx` 是给人看的用例台账,单文件、每个资源一个 sheet
(用户认证/项目/团队成员/接口/用例/场景/环境/Mock/定时任务/压测/系统/报告与其他/通用契约反例)。

**它由脚本从 YAML 生成,不手动维护**:编号列与"预期结果"直接读 `data/*.yaml`,
保证台账和自动化数据零漂移。改了 YAML 重跑即可:

```bash
python tools/gen_testcase_excel.py
```

脚本会校验每个 YAML `case_id` 都进了台账,漏了直接报错退出。

该历史 YAML 表不包含本次纯 Python 核心场景，也不是 639 条完整设计主表。完整新版位于 WhaleTestPro 仓库 `docs/testing/testcases/`；本次通过 `design_case` 标签和映射文档关联其编号，不覆盖旧表。

## 断言契约(assert_util)

YAML 的 `expected` 声明哪项就校验哪项,各检查彼此独立:

| 键 / 方法 | 含义 |
|-----------|------|
| `status_code` | HTTP 状态码 |
| `body_type` | 响应体整体类型(`list` / `dict` …) |
| `required_fields` | 响应 dict 必须包含的字段 |
| `field_types` | 指定响应字段的数据类型 |
| `detail` | FastAPI 报错体的 `detail` 文案 |
| `assert_values` | 校验创建或修改后响应字段的实际值 |

## 回归覆盖重点

- **认证隔离**:校验 JWT 包含唯一 `jti`,同一账号连续登录得到不同 Token,登出只拉黑当前 Token。
- **团队权限**:覆盖 owner / admin / member / outsider 的成员查询、候选搜索、添加、改角色、移除，以及成员变化后项目权限立即生效。
- **项目生命周期**:覆盖项目修改以及带接口、用例的非空项目事务删除,避免外键冲突退化为 500。
- **输入边界**:空名称、超长名称、非法 Cron、零或负并发统一期望 `422`。
- **资源契约**:覆盖无 Token、缺 `X-Project-Id`、错误类型、跨项目访问和更新不存在资源。
- **报告闭环**:覆盖单用例报告分页、用例名称,以及一份场景报告对应多条步骤明细。
- **测试隔离**:HTTP fixture 创建独立项目/账号并清理本轮资产；账号无删除接口，测试库需重置。HTTP 黑盒不导入后端代码，`tests/` 离线契约另用真实路由与隔离 SQLite。

历史完整 HTTP 回归基线为 `233 collected / 232 passed / 1 skipped`；跳过项是需要预先录制真实流量的数据依赖场景。该结果不代表后续版本完成全量真实环境回归。

2026-10-10 前一批修复定时任务反例缺失环境和压测清理路由问题，离线验证为 `24 passed`，详情见被测仓库 `docs/Review修复与验证-2026-10-10.md`。后续核心同步曾记录 `57 passed`；2026-10-11 压测核心增量最终离线门禁为 `108 passed`、1 条已有 Starlette/httpx 弃用警告，未连接实际部署平台。历史离线记录和真实 HTTP 结果分开，不混用通过数量。

2026-10-11 随后修复夹具用户名及安全清理契约后，最终离线门禁为 `128 passed`、1 条已有警告；一次性双库、独立 Redis/RabbitMQ、真实 Celery/Locust 与专用 HTTP 模拟目标上的核心集成为 `56/56` 通过（29 项核心 HTTP + 27 项压测配置/运行），禁用自动重跑。证据见 [被测仓库隔离集成验收记录](https://github.com/zixuan-come/WhaleTestPro/blob/main/docs/testing/Review修复集成验证-2026-10-11.md)。这是当日源码及范围的历史验收，不代表后续重构或全部 93 个接口、639 条设计用例已实测；没有向 WhaleShop 或原业务服务发压测流量，新 GitHub Actions 仍以实际云端结果为准。

被测系统现在要求独立 `LOCUST_CONTROL_TOKEN`，Locust 8089 不向宿主机开放；本仓 CI 在 locust-master 容器内部执行带凭证的就绪探测。执行实际压测回归前，先确认后端、Worker 和 Locust Master 的控制凭证一致。

### HTTP 与链路压测的增量核心回归

`testcases/test_perf_core/` 补充 20 条配置用例和 7 条真实异步用例，不替换原 GET 回归。覆盖 POST/JSON、表单、UTF-8 raw、配置保存、步骤数量边界、422 反例、Token/订单 ID 提取传递、变量类型、失败断路、按步骤与整轮统计、排队/运行中删除 409。

`tests/test_perf_core_contract.py` 用真实后端路由和隔离 SQLite 验证这些脚本；Redis、身份、消息发布及 Worker 为受控替身。迭代逻辑执行真实后端引擎，但目标只调用纯夹具函数，不代表部署环境的 Celery/Locust/网络验收。503 控制故障以确定性故障注入验证记录及租约保留、恢复后可删除，不会停止实际 Master 制造故障。

核心回归需显式设置 `WHALE_PERF_CORE_ALLOW_WRITES=1`；发压测流量还需 `WHALE_PERF_ALLOW_LOAD=1` 和 `WHALE_PERF_FIXTURE_BASE_URL`。CI 在临时 Compose 网络内启动专用模拟服务（不暴露宿主端口），单用户、短时运行，结束后停止、核验删除本轮任务，再清理项目/团队。清理失败会报告失败并保留项目，不能将 409/503 当作清理成功。账号无删除接口，只留在隔离测试库。

用例来源、范围和运行方法见 [压测核心自动化映射](docs/压测核心自动化映射.md)。这批扩展只同步自动化及其设计映射，没有改写主仓的全量 Excel 台账，也不是 WhaleShop 性能测试报告。

## CI

`.github/workflows/ci.yml`：push/PR 到 main 触发。先由 `offline-contract` 安装两仓依赖并执行离线门禁；通过后 `api-test` 才启动临时测试环境。集成流程：checkout 两仓 →
起 MySQL 建影子库 → 起 app、Celery Worker、Locust Master/Worker（同时带起 redis/rabbitmq）→ 轮询 `/health/ready` 与带控制凭证的 Locust Worker 就绪 →
**独立核心 HTTP 门禁** → 启动不开放宿主端口的专用模拟夹具 → **HTTP/链路压测核心门禁** → 其余集成冒烟 → 其余 HTTP 回归 → 清理专用夹具 → 上传 Allure 原始结果 →
装 Java + Allure CLI 渲染 **HTML 报告** 并上传。两份产物:`allure-results`(原始)、
`allure-report`(可直接打开的 HTML)。**私有被测仓需在本仓 Secrets 配 `BACKEND_REPO_TOKEN`**
(有 repo 读权限的 PAT)。

## 运行

```bash
pip install -r requirements.txt
cp .env.example .env  # Windows 可手动复制后填写本地账号

pytest                                   # 跑全部用例
pytest -m smoke                          # 只跑核心链路冒烟(登录/建项目/建接口跑用例/探活)
pytest testcases/test_auth/test_login.py # 跑单个文件
pytest --cov --cov-report=term-missing   # 带覆盖率

# Allure 报告
pytest --alluredir=allure-results
allure serve allure-results
```

每次跑测试的 HTTP 明细(method/URL/状态码/耗时)落在 `logs/http.log`,失败时看它排查。
黑盒打真实网络,`pytest.ini` 默认 `--reruns 1`:偶发抖动自动重跑一次,稳定失败才算真挂。
本次独立核心门禁使用 `--reruns 0`，首次验收不以自动重跑掩盖稳定性问题。

## Roadmap / 有意不做

当前套件已覆盖各资源的 CRUD+执行、通用契约反例、边界与鉴权特征化、冒烟分层、
失败重试、HTTP 日志、CI+Allure HTML 报告。以下是**有意识划在 1.0 之外**的方向——
不是没想到,而是权衡后判断边际收益递减或超出黑盒测试职责,记在此以备后续:

- **响应体结构断言升级(JSON Schema)**:当前 `assert_values` 做的是字段级值比对,
  更严格的做法是给关键响应挂 JSON Schema 校验类型/必填/枚举。收益中等,待有稳定契约后再补。
- **契约模糊测试(schemathesis)**:被测系统有 `/openapi.json`,可用 schemathesis
  按 schema 自动生成用例做属性测试。适合契约稳定后引入,现阶段人工用例更可控。
- **Allure 报告发布**:CI 现在把 HTML 报告存成 artifact(需下载查看),
  后续可发到 GitHub Pages 直接在线看趋势。属部署层打磨,非测试能力。
- **lint 门禁(ruff)**:代码质量规范,对纯测试项目偏锦上添花,想要工程背书时再加。
- **覆盖率门禁**:❌ 明确不做。黑盒测的是被测系统的代码,而 `pytest-cov` 统计的是
  测试套件自身的行覆盖,对黑盒场景参考意义有限;`pytest-cov` 保留为"需要时能开"。
