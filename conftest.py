import logging
import subprocess
import uuid
from pathlib import Path

import pytest
from config import BASE_URL, USERNAME, PASSWORD, RUNNER_BASE_URL
from common.request_util import RequestUtil

TEST_PROJECT_NAME_PREFIX = "auto_test_project_"

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


def clear_login_rate_limit():
    """清理被测服务的登录限流桶，允许测试创建多个独立登录身份。"""
    try:
        subprocess.run(
            [
                "docker",
                "exec",
                REDIS_CONTAINER,
                "sh",
                "-c",
                "redis-cli KEYS 'ratelimit:login:*' | xargs -r redis-cli DEL",
            ],
            capture_output=True,
            timeout=10,
        )
    except Exception:
        pass


@pytest.fixture(scope="session", autouse=True)
def reset_login_rate_limit():
    """会话开始前清掉登录限流计数桶,保证测试套可在 60s 内重复跑。

    后端 login_rate_limit = 每 IP 5 次/60s,且失败登录也计数(依赖在 s_login 前执行)。
    一次完整跑正好耗 5 次 localhost 登录,60s 内再跑就 429 级联。
    这里 best-effort 清桶:docker 不可达(如 CI 新容器)时静默跳过,不影响用例。
    """
    clear_login_rate_limit()

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

    为什么要专用账号:登出只应影响当前 Token,不应注销 admin 的共享会话。若直接注销
    admin 的 token,会把
    session 级 auth_client 的 admin token 一起拉黑 → 项目用例全 401。
    用独立账号,拉黑它不污染 admin 会话。
    """
    username, password = "logout_bot", "logout_bot_pwd"
    client.post("/auth/register", json={"username": username, "password": password})  # 已存在返 400,忽略
    clear_login_rate_limit()
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
def member_users(client, ensure_test_user):
    """创建成员权限测试所需的三种独立身份，并返回其黑盒客户端。"""
    users = {}

    for role in ("admin", "member", "outsider"):
        username = f"api_member_{role}_{uuid.uuid4().hex[:8]}"
        password = PASSWORD

        register = client.post(
            "/auth/register",
            json={"username": username, "password": password},
        )
        assert register.status_code == 201, (
            f"成员测试账号注册失败: role={role}, response={register.text}"
        )

        clear_login_rate_limit()
        login = client.post(
            "/auth/login",
            json={"username": username, "password": password},
        )
        assert login.status_code == 200, (
            f"成员测试账号登录失败: role={role}, response={login.text}"
        )

        token = login.json()["access_token"]
        users[role] = {
            "id": register.json()["id"],
            "username": username,
            "token": token,
            "client": RequestUtil(
                BASE_URL,
                headers={"Authorization": f"Bearer {token}"},
            ),
        }

    return users


@pytest.fixture
def member_project_context(auth_client, member_users, unique_name, project_cleanup):
    """创建一个 owner/admin/member 项目上下文，供成员权限黑盒用例复用。"""
    created = auth_client.post(
        "/projects",
        json={
            "name": unique_name("auto_member_project_"),
            "description": "成员管理接口自动化测试项目",
        },
    )
    assert created.status_code == 201, f"成员测试项目创建失败: {created.text}"
    project_id = created.json()["id"]
    project_cleanup(project_id)

    for role in ("admin", "member"):
        response = auth_client.post(
            f"/projects/{project_id}/members",
            json={"user_id": member_users[role]["id"], "role": role},
        )
        assert response.status_code == 201, (
            f"成员测试前置关系创建失败: role={role}, response={response.text}"
        )

    members = auth_client.get(f"/projects/{project_id}/members")
    assert members.status_code == 200, f"成员测试前置查询失败: {members.text}"
    member_rows = members.json()
    member_ids = {row["user_id"]: row["id"] for row in member_rows}
    role_user_ids = {
        "owner": next(row["user_id"] for row in member_rows if row["role"] == "owner"),
        "admin": member_users["admin"]["id"],
        "member": member_users["member"]["id"],
    }

    other_project_cache = {}

    def make_other_project():
        """创建第二个项目并把 outsider 加入，用于跨项目 IDOR 用例。"""
        if other_project_cache:
            return other_project_cache

        other = auth_client.post(
            "/projects",
            json={
                "name": unique_name("auto_member_other_project_"),
                "description": "跨项目权限测试项目",
            },
        )
        assert other.status_code == 201, f"跨项目测试项目创建失败: {other.text}"
        other_id = other.json()["id"]
        project_cleanup(other_id)

        added = auth_client.post(
            f"/projects/{other_id}/members",
            json={"user_id": member_users["outsider"]["id"], "role": "member"},
        )
        assert added.status_code == 201, f"跨项目测试成员创建失败: {added.text}"

        other_members = auth_client.get(f"/projects/{other_id}/members")
        assert other_members.status_code == 200, (
            f"跨项目测试成员查询失败: {other_members.text}"
        )
        outsider_id = next(
            row["id"]
            for row in other_members.json()
            if row["user_id"] == member_users["outsider"]["id"]
        )
        other_project_cache.update({"project_id": other_id, "member_id": outsider_id})
        return other_project_cache

    return {
        "project_id": project_id,
        "users": member_users,
        "clients": {
            "owner": auth_client,
            "admin": member_users["admin"]["client"],
            "member": member_users["member"]["client"],
            "outsider": member_users["outsider"]["client"],
        },
        "member_ids": member_ids,
        "member_id": lambda role: member_ids[role_user_ids[role]],
        "make_other_project": make_other_project,
    }


@pytest.fixture(scope="session")
def project_id(auth_client):
    project_name = f"{TEST_PROJECT_NAME_PREFIX}{uuid.uuid4().hex[:8]}"
    create_resp = auth_client.post(
        "/projects",
        json={
            "name": project_name,
            "description": "接口自动化测试项目"
        }
    )
    assert create_resp.status_code == 201, (
        f"公共测试项目创建失败: {create_resp.text}"
    )

    created_project_id = create_resp.json()["id"]
    yield created_project_id

    try:
        auth_client.delete(f"/projects/{created_project_id}")
    except Exception:
        pass


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
    """只带 X-Project-Id、不带 token 的 client，用于统一鉴权反例。"""
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
def seed_named_runnable_case(project_client, unique_name, api_cleanup):
    """创建可执行用例并返回 id/name，供需要校验报告展示名称的用例使用。"""
    interface = project_client.post("/interfaces", json={
        "name": unique_name("auto_report_if_"),
        "method": "GET",
        "url": "/health",
    })
    assert interface.status_code == 201, f"报告名称测试创建接口失败: {interface.text}"
    interface_id = interface.json()["id"]
    api_cleanup(f"/interfaces/{interface_id}")

    case_name = unique_name("auto_report_case_")
    case = project_client.post("/cases", json={
        "name": case_name,
        "interface_id": interface_id,
        "expected_status": 200,
    })
    assert case.status_code == 201, f"报告名称测试创建用例失败: {case.text}"
    case_id = case.json()["id"]
    api_cleanup(f"/cases/{case_id}")
    return {"id": case_id, "name": case_name}


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




