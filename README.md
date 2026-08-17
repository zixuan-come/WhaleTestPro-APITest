# WhaleTestPro-APITest

针对 [WhaleTestPro](https://github.com/zixuan-come/WhaleTestPro) 接口测试平台的接口自动化测试项目。

以 **httpx 黑盒**方式打被测服务的 HTTP 接口(不 import 被测代码),数据驱动 + 分层封装,pytest 组织用例,Allure 出报告。

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

鉴权:受保护接口需 `Authorization: Bearer <token>`;项目内接口、用例、环境、场景等资产接口还需 `X-Project-Id`。项目 CRUD / 成员接口通过路径参数校验项目权限,不使用该请求头;健康检查、注册、登录和 Mock 命中路由保持公开。

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
│   └── yaml_util.py        # 读取 data/ 下的 YAML
├── config.py               # 服务地址与测试账号配置(从 .env 读)
├── conftest.py             # 全局 fixture:client、登录取 token、项目上下文、清理/自举
├── data/                   # YAML 测试数据(按模块和接口场景拆分)
├── docs/                   # 用例台账 Excel(由 tools 脚本从 data/ 生成)
├── tools/gen_testcase_excel.py # 读 data/*.yaml 生成《接口测试用例》Excel,校验编号一致
├── testcases/              # 测试用例(按资源分目录,覆盖全部接口)
│   ├── test_auth/          # 注册 / 登录 / 登出
│   ├── test_project/       # 项目 CRUD + 成员角色 + 非空项目删除
│   ├── test_interface/     # 接口 CRUD + 分类改名/删除
│   ├── test_case/          # 用例 CRUD + 执行 + 串联
│   ├── test_scenario/      # 场景 CRUD + 执行
│   ├── test_environment/   # 环境 CRUD
│   ├── test_mock/          # Mock CRUD + 动态命中
│   ├── test_schedule/      # 定时任务 CRUD
│   ├── test_perf/          # 压测任务 CRUD + 触发
│   ├── test_contract/      # 跨资源反例:缺头/缺字段/错类型/无 token/更新不存在
│   ├── test_boundary/      # 边界与畸形输入回归(空/超长 name、非法 cron、负并发)
│   ├── test_system/        # /health + /metrics
│   ├── test_report/        # 场景报告父记录与步骤明细
│   └── test_misc/          # 报告 / 回归 / demo 订单 / 流量录制
├── pytest.ini              # 用例发现规则、addopts
├── .github/workflows/ci.yml# CI:起被测全栈 → 跑黑盒回归 → 传 Allure 产物
├── requirements.txt
└── README.md
```

## 用例台账(Excel)

`docs/WhaleTestPro接口测试用例.xlsx` 是给人看的用例台账,单文件、每个资源一个 sheet
(用户认证/项目/接口/用例/场景/环境/Mock/定时任务/压测/系统/报告与其他/通用契约反例)。

**它由脚本从 YAML 生成,不手动维护**:编号列与"预期结果"直接读 `data/*.yaml`,
保证台账和自动化数据零漂移。改了 YAML 重跑即可:

```bash
python tools/gen_testcase_excel.py
```

脚本会校验每个 YAML `case_id` 都进了台账,漏了直接报错退出。

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
- **项目权限**:覆盖 owner / admin / member / outsider 的成员查询、候选搜索、添加、改角色、移除和越权场景。
- **项目生命周期**:覆盖项目修改以及带接口、用例的非空项目事务删除,避免外键冲突退化为 500。
- **输入边界**:空名称、超长名称、非法 Cron、零或负并发统一期望 `422`。
- **资源契约**:覆盖无 Token、缺 `X-Project-Id`、错误类型、跨项目访问和更新不存在资源。
- **报告闭环**:覆盖单用例报告分页、用例名称,以及一份场景报告对应多条步骤明细。
- **测试隔离**:fixture 自动创建独立项目和账号,测试结束后清理数据,不依赖 WhaleTestPro 内部代码。

当前完整回归基线为 `201 collected / 200 passed / 1 skipped`;跳过项是需要预先录制真实流量的数据依赖场景。

## CI

`.github/workflows/ci.yml`:push/PR 到 main 触发。流程:checkout 本仓 + 被测系统 →
起 MySQL 建影子库 → 起 app(自动带起 redis/rabbitmq)→ 轮询 `/health` →
**冒烟门禁(`pytest -m smoke`,挂了快速失败)** → 全量 pytest → 上传 Allure 原始结果 →
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
