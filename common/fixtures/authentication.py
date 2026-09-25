"""Existing account/client fixtures with unchanged scopes and bootstrap policy."""
import subprocess
import pytest
from config import BASE_URL, USERNAME, PASSWORD
from common.request_util import RequestUtil

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


@pytest.fixture(scope="session")
def reset_login_rate_limit():
    """会话开始前清掉登录限流计数桶,保证测试套可在 60s 内重复跑。

    后端 login_rate_limit = 每 IP 5 次/60s,且失败登录也计数(依赖在 s_login 前执行)。
    一次完整跑正好耗 5 次 localhost 登录,60s 内再跑就 429 级联。
    这里 best-effort 清桶:docker 不可达(如 CI 新容器)时静默跳过,不影响用例。
    """
    clear_login_rate_limit()


@pytest.fixture(scope="session")
def ensure_test_user(reset_login_rate_limit):
    """自举测试账号:注册 config 里的 USERNAME/PASSWORD,已存在(400)则忽略。

    后端不自动播种任何用户,现有环境的 admin 是当初手动注册的。CI 全新库里
    没有这个账号 → 登录必挂。这里保证被测账号一定存在,本地/CI 都能跑。
    依赖 reset_login_rate_limit 只为固定执行顺序(先清限流桶,再注册)。
    """
    assert USERNAME and PASSWORD, "集成测试需要配置 WHALE_USERNAME 和 WHALE_PASSWORD"
    response = RequestUtil(BASE_URL).post(
        "/auth/register", json={"username": USERNAME, "password": PASSWORD}
    )
    assert response.status_code in {201, 400}, f"测试账号自举失败: HTTP {response.status_code}"


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
