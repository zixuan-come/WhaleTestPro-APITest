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
│   ├── assert_util.py      # 断言封装:状态码、JSON 字段、结构
│   └── yaml_util.py        # 读取 data/ 下的 YAML
├── config.py               # BASE_URL、测试账号、超时等配置
├── conftest.py             # 全局 fixture:client、登录取 token、项目上下文
├── data/                   # YAML 测试数据(用例数据外置)
├── testcases/              # 测试用例
├── requirements.txt
└── README.md
```

## 运行

```bash
pip install -r requirements.txt
cp .env.example .env  # Windows 可手动复制后填写本地账号

pytest                                   # 跑全部用例
pytest testcases/test_auth/test_login.py # 跑单个文件
pytest --cov --cov-report=term-missing   # 带覆盖率

# Allure 报告
pytest --alluredir=allure-results
allure serve allure-results
```
