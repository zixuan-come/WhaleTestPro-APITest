import logging
import subprocess
import uuid
from pathlib import Path

import pytest
from config import BASE_URL, USERNAME, PASSWORD, RUNNER_BASE_URL
from common.request_util import RequestUtil

TEST_PROJECT_NAME = "auto_test_project"

# ---- HTTP 日志落文件 ----------------------------------------------------
# 把 whale.http(RequestUtil 产出的每条请求日志)挂到 logs/http.log。
# 在此处(conftest 导入期)建目录 + 装 handler,由我们自己控制顺序,
# 不走 pytest 的 log_file(它在插件 configure 阶段开文件,子目录不存在会炸)。
_LOG_DIR = Path(__file__).resolve().parent / "logs"
_LOG_DIR.mkdir(exist_ok=True)
_http_log = logging.getLogger("whale.http")
if not _http_log.handlers:  # 避免 -p 重载 conftest 时重复挂
    _handler = logging.FileHandler(_LOG_DIR / "http.log", encoding="utf-8")
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    _http_log.addHandler(_handler)
    _http_log.setLevel(logging.INFO)
    _http_log.propagate = False

# 被测服务的 redis 容器名(docker compose 默认命名 {project}-{service}-{index})
REDIS_CONTAINER = "whaletestpro-redis-1"


@pytest.fixture(scope="session", autouse=True)
def reset_login_rate_limit():
    """会话开始前清掉登录限流计数桶,保证测试套可在 60s 内重复跑。

    后端 login_rate_limit = 每 IP 5 次/60s,且失败登录也计数(依赖在 s_login 前执行)。
    一次完整跑正好耗 5 次 localhost 登录,60s 内再跑就 429 级联。
    这里 best-effort 清桶:docker 不可达(如 CI 新容器)时静默跳过,不影响用例。
    """
    try:
        subprocess.run(
            ["docker", "exec", REDIS_CONTAINER, "sh", "-c",
             "redis-cli KEYS 'ratelimit:login:*' | xargs -r redis-cli DEL"],
            capture_output=True, timeout=10,
        )
    except Exception:
        pass  # 环境里没有 docker / 容器名不同,忽略即可

@pytest.fixture(scope="session", autouse=True)
def ensure_test_user(reset_login_rate_limit):
    """自举测试账号:注册 config 里的 USERNAME/PASSWORD,已存在(400)则忽略。

    后端不自动播种任何用户,现有环境的 admin 是当初手动注册的。CI 全新库里
    没有这个账号 → 登录必挂。这里保证被测账号一定存在,本地/CI 都能跑。
    依赖 reset_login_rate_limit 只为固定执行顺序(先清限流桶,再注册)。
    """
    RequestUtil(BASE_URL).post(
        "/auth/register", json={"username": USERNAME, "password": PASSWORD}
    )


@pytest.fixture(scope="session")
def login_data(client, ensure_test_user):
    resp = client.post("/auth/login", json={"username": USERNAME, "password": PASSWORD})
    return resp.json()


@pytest.fixture(scope="session")
def access_token(login_data):
    return login_data["access_token"]


@pytest.fixture
def disposable_token(client):
    """给"会作废 token"的用例(如 logout)用:注册/登录一个专用账号,返回其 token。

    为什么要专用账号:后端 JWT 只含 sub+exp(整秒),同一用户同一秒登录会拿到
    完全相同的 token 字符串。若 logout 直接注销 admin 的 token,会把
    session 级 auth_client 的 admin token 一起拉黑 → 项目用例全 401。
    用独立账号,拉黑它不污染 admin 会话。
    """
    username, password = "logout_bot", "logout_bot_pwd"
    client.post("/auth/register", json={"username": username, "password": password})  # 已存在返 400,忽略
    resp = client.post("/auth/login", json={"username": username, "password": password})
    return resp.json()["access_token"]


@pytest.fixture(scope="session")
def auth_headers(access_token):
    return {"Authorization": f"Bearer {access_token}"}


@pytest.fixture(scope="session")
def client():
    return RequestUtil(BASE_URL)


@pytest.fixture(scope="session")
def auth_client(access_token):
    headers = {"Authorization": f"Bearer {access_token}"}
    return RequestUtil(BASE_URL, headers=headers)


@pytest.fixture(scope="session")
def project_id(auth_client):
    resp = auth_client.get("/projects")
    assert resp.status_code == 200

    projects = resp.json()

    for project in projects:
        if project["name"] == TEST_PROJECT_NAME:
            return project["id"]

    create_resp = auth_client.post(
        "/projects",
        json={
            "name": TEST_PROJECT_NAME,
            "description": "接口自动化测试项目"
        }
    )
    assert create_resp.status_code == 201

    return create_resp.json()["id"]


@pytest.fixture(scope="session")
def project_headers(project_id):
    return {"X-Project-Id": str(project_id)}


@pytest.fixture(scope="session")
def project_client(access_token, project_id):
    headers = {
        "Authorization": f"Bearer {access_token}",
        "X-Project-Id": str(project_id)
    }
    return RequestUtil(BASE_URL, headers=headers)


@pytest.fixture(scope="session")
def project_only_client(project_id):
    """只带 X-Project-Id、不带 token 的 client。用于"无 token"特征化用例：
    验证各资源的鉴权现状——interfaces/scenarios 会 401，其余资源目前无鉴权(可直接读写)。
    """
    return RequestUtil(BASE_URL, headers={"X-Project-Id": str(project_id)})


@pytest.fixture
def unique_name():
    """生成唯一项目名，避免多次跑测试撞 name UNIQUE 约束。

    用 name_prefix 拼 8 位随机 hex：auto_project_create_ab12cd34
    """
    def _make(prefix="auto_project_"):
        return f"{prefix}{uuid.uuid4().hex[:8]}"
    return _make


@pytest.fixture
def api_cleanup(project_client):
    """通用清理登记表：测试里 register("/interfaces/{id}") 登记创建出来的资源，
    用例结束后按后进先出统一删掉，保证黑盒测试可重复跑、不留垃圾数据。
    删除失败(已被用例自己删/404)不该让用例误报，忽略即可。
    """
    paths = []

    def register(delete_path):
        paths.append(delete_path)
        return delete_path

    yield register

    for path in reversed(paths):
        try:
            project_client.delete(path)
        except Exception:
            pass


@pytest.fixture
def seed_interface(project_client, unique_name, api_cleanup):
    """造一个接口并登记清理，返回其 id。给 case / scenario 等依赖接口的用例做前置。"""
    def _make():
        resp = project_client.post("/interfaces", json={
            "name": unique_name("auto_if_"),
            "method": "GET",
            "url": "http://localhost:8001/health",
        })
        assert resp.status_code == 201, f"前置建接口应成功: {resp.text}"
        iid = resp.json()["id"]
        api_cleanup(f"/interfaces/{iid}")
        return iid
    return _make


@pytest.fixture
def seed_case(project_client, seed_interface, unique_name, api_cleanup):
    """造一个用例(自带接口)并登记清理，返回其 id。"""
    def _make():
        iid = seed_interface()
        resp = project_client.post("/cases", json={
            "name": unique_name("auto_case_"),
            "interface_id": iid,
            "expected_status": 200,
        })
        assert resp.status_code == 201, f"前置建用例应成功: {resp.text}"
        cid = resp.json()["id"]
        api_cleanup(f"/cases/{cid}")
        return cid
    return _make


@pytest.fixture
def runner_env(project_client, unique_name, api_cleanup):
    """造一个 base_url 指向被测服务【容器内地址】的环境,返回其 id。

    执行引擎在被测容器内跑,访问自身要用内部端口(RUNNER_BASE_URL,默认 8000),
    宿主的 8001 在容器内不通。给 case/scenario 执行用例(需 env_id)做前置。
    """
    resp = project_client.post("/environments", json={
        "name": unique_name("auto_run_env_"),
        "base_url": RUNNER_BASE_URL,
    })
    assert resp.status_code == 201, f"前置建执行环境应成功: {resp.text}"
    eid = resp.json()["id"]
    api_cleanup(f"/environments/{eid}")
    return eid


@pytest.fixture
def seed_runnable_case(project_client, unique_name, api_cleanup):
    """造一个"能真正跑通"的用例:接口 url 用路径(/health),配合 runner_env 的
    base_url 拼成完整地址,expected_status=200 → 执行必 passed。返回 case id。
    """
    def _make(path="/health", expected_status=200):
        iid = project_client.post("/interfaces", json={
            "name": unique_name("auto_run_if_"),
            "method": "GET",
            "url": path,
        }).json()["id"]
        api_cleanup(f"/interfaces/{iid}")
        cid = project_client.post("/cases", json={
            "name": unique_name("auto_run_case_"),
            "interface_id": iid,
            "expected_status": expected_status,
        }).json()["id"]
        api_cleanup(f"/cases/{cid}")
        return cid
    return _make


@pytest.fixture
def project_cleanup(auth_client):
    """函数级清理登记表：测试里 register(pid) 登记创建出来的项目，
    用例结束后统一删掉，保证黑盒测试不往被测库里留垃圾数据（可重复跑）。
    """
    created_ids = []

    def register(project_id):
        created_ids.append(project_id)
        return project_id

    yield register

    for pid in created_ids:
        # 已被用例自己删掉的会返 404，忽略即可；清理失败不该让用例误报
        try:
            auth_client.delete(f"/projects/{pid}")
        except Exception:
            pass




