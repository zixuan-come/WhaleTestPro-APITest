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

鉴权:除注册/登录外,接口需 `Authorization: Bearer <token>` + `X-Project-Id` 双请求头。

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
│   ├── request_util.py     # httpx 封装:统一 BASE_URL、注入 token / X-Project-Id
│   ├── assert_util.py      # 契约断言:status_code / body_type / required_fields / detail
│   └── yaml_util.py        # 读取 data/ 下的 YAML
├── config.py               # BASE_URL、测试账号、超时等配置(从 .env 读)
├── conftest.py             # 全局 fixture:client、登录取 token、项目上下文、清理/自举
├── data/                   # YAML 测试数据(用例数据外置,按资源一文件)
├── docs/                   # 用例台账 Excel(由 tools 脚本从 data/ 生成)
├── tools/gen_testcase_excel.py # 读 data/*.yaml 生成《接口测试用例》Excel,校验编号一致
├── testcases/              # 测试用例(按资源分目录,覆盖全部接口)
│   ├── test_auth/          # 注册 / 登录 / 登出
│   ├── test_project/       # 项目 CRUD
│   ├── test_interface/     # 接口 CRUD + 分类改名/删除
│   ├── test_case/          # 用例 CRUD + 执行 + 串联
│   ├── test_scenario/      # 场景 CRUD + 执行
│   ├── test_environment/   # 环境 CRUD
│   ├── test_mock/          # Mock CRUD + 动态命中
│   ├── test_schedule/      # 定时任务 CRUD
│   ├── test_perf/          # 压测任务 CRUD + 触发
│   ├── test_contract/      # 跨资源反例:缺头/缺字段/错类型/无 token/更新不存在
│   ├── test_boundary/      # 边界与畸形输入特征化(空/超长 name、非法 cron、负并发)
│   ├── test_system/        # /health + /metrics
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

YAML 的 `expected` 里声明了哪几项就查哪几项,四类独立:

| 键 | 含义 |
|----|------|
| `status_code` | HTTP 状态码 |
| `body_type` | 响应体整体类型(`list` / `dict` …) |
| `required_fields` | 响应 dict 必须包含的字段(只查存在性) |
| `detail` | FastAPI 报错体的 `detail` 文案 |

## 被测系统缺陷特征化(characterization)

黑盒探测发现多处被测系统行为问题,用**特征化用例**钉住现状——不是测试写错,而是
用例断言"当前(有缺陷的)行为",一旦后端修复即变红提醒复核。**不修改被测系统**。

| 现象 | 现状断言 | 说明 |
|------|----------|------|
| 鉴权不一致 | `create_no_token` 系列期望 201 | 仅 `interfaces` / `scenarios` / `projects` 强制 token(缺则 401);`cases` / `environments` / `mocks` / `schedules` / `perf` 无鉴权,不带 token 也能建 → 疑似漏 `Depends(get_current_user)` |
| JWT 不唯一 | logout 用独立账号 | token 仅含 `sub`+`exp`(整秒),同用户同秒登录得到完全相同 token;注销会误伤同串 token,故 `disposable_token` fixture 用专用账号隔离 |
| 空 name 不校验 | `data/boundary.yaml` 空 name 期望 201 | 6 类资源建资源时 name 传空串照建,应 400/422 |
| 超长 name 崩服务 | 超长 name 期望 **500** | name 超 255 字符未捕获直接 500(应 400/422)——真 BUG,5 类资源一致 |
| 非法 cron 崩服务 | `schedule_invalid_cron` 期望 **500** | 定时任务 cron 传 `not-a-cron` 未校验直接 500(应 400/422)——真 BUG |
| perf 并发数不校验 | `perf_users_zero/negative` 期望 201 | `users=0` / `users=-5` 也接受,应 `>=1` |

边界特征化集中在 `testcases/test_boundary/`(数据 `data/boundary.yaml`,哨兵
`{{LONG}}` 由测试替换成 300 个 `a`)。另在通用契约里补了 `test_update_not_found`:
`interface` / `scenario` / `environment` / `mock` / `schedule` 更新不存在的 id
(带合法 body)→ 404,验证的是"找不到"而非"参数错"。

若某资源后端补上鉴权/校验/修了 500,对应用例会从现状码翻红——
这正是特征化的目的:把"已知缺口"变成可回归的信号。

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
