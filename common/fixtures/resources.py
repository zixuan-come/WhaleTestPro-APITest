"""Project/asset fixtures; preserve LIFO cleanup and failed-load retention."""
import uuid
import pytest
from config import BASE_URL, RUNNER_BASE_URL
from common.request_util import RequestUtil
from common.fixtures.runtime import cleanup_log as _cleanup_log

TEST_PROJECT_NAME_PREFIX = "auto_test_project_"


class ResourceCleanupState:
    def __init__(self):
        self.retained_projects = set()
        self.retained_teams = set()


@pytest.fixture(scope="session")
def cleanup_state():
    """Never cascade-delete parents after an unconfirmed perf cleanup."""
    return ResourceCleanupState()


@pytest.fixture(scope="session")
def team_factory(auth_client, cleanup_state):
    """Create explicit teams and clean them after dependent projects are removed."""
    created = []
    def make(owner=None):
        owner = owner or auth_client
        response = owner.post("/teams", json={"name": f"auto_team_{uuid.uuid4().hex[:12]}"})
        assert response.status_code == 201, f"前置建团队失败: {response.text}"
        team_id = response.json()["id"]
        created.append((owner, team_id))
        return team_id
    yield make
    for owner, team_id in reversed(created):
        if team_id in cleanup_state.retained_teams:
            _cleanup_log.warning("压测清理未确认，保留测试团队 id=%s", team_id)
            continue
        response = owner.delete(f"/teams/{team_id}")
        assert response.status_code in {200, 404}, f"清理测试团队失败: {response.text}"


@pytest.fixture(scope="session")
def team_id(team_factory):
    return team_factory()


@pytest.fixture(scope="session")
def project_id(auth_client, team_id, cleanup_state):
    project_name = f"{TEST_PROJECT_NAME_PREFIX}{uuid.uuid4().hex[:8]}"
    create_resp = auth_client.post(
        "/projects",
        json={
            "name": project_name,
            "description": "接口自动化测试项目",
            "team_id": team_id,
        }
    )
    assert create_resp.status_code == 201, (
        f"公共测试项目创建失败: {create_resp.text}"
    )

    created_project_id = create_resp.json()["id"]
    yield created_project_id

    if created_project_id in cleanup_state.retained_projects:
        cleanup_state.retained_teams.add(team_id)
        _cleanup_log.warning("压测清理未确认，保留测试项目 id=%s 和团队 id=%s",
                             created_project_id, team_id)
        return
    try:
        reply = auth_client.delete(f"/projects/{created_project_id}")
        if reply.status_code not in {200, 404}:
            raise AssertionError(f"HTTP {reply.status_code}")
    except Exception as exc:
        cleanup_state.retained_projects.add(created_project_id)
        cleanup_state.retained_teams.add(team_id)
        raise AssertionError(f"项目清理未确认，保留项目 id={created_project_id} 和团队 id={team_id}；"
                             f"错误类型：{type(exc).__name__}") from None


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
def api_cleanup(project_client, cleanup_state):
    """通用清理登记表：测试里 register("/interfaces/{id}") 登记创建出来的资源，
    用例结束后按后进先出统一删掉，保证黑盒测试可重复跑、不留垃圾数据。
    404 表示资源已删除。压测删除失败必须报告并保留父项目，不做级联兜底。
    """
    paths = []

    def register(delete_path):
        paths.append(delete_path)
        return delete_path

    yield register

    perf_errors = []
    for path in reversed(paths):
        try:
            reply = project_client.delete(path)
            if path.startswith("/perf/tasks/") and reply.status_code not in {200, 404}:
                perf_errors.append(f"{path}: HTTP {reply.status_code}")
        except Exception as exc:
            if path.startswith("/perf/tasks/"):
                perf_errors.append(f"{path}: {type(exc).__name__}")
    if perf_errors:
        retained_project_id = int(project_client.headers["X-Project-Id"])
        cleanup_state.retained_projects.add(retained_project_id)
        raise AssertionError(f"压测清理失败，保留项目 id={retained_project_id}：" + "; ".join(perf_errors))


@pytest.fixture
def seed_interface(project_client, unique_name, api_cleanup):
    """造一个接口并登记清理，返回其 id。给 case / scenario 等依赖接口的用例做前置。"""
    def _make():
        resp = project_client.post("/interfaces", json={
            "name": unique_name("auto_if_"),
            "method": "GET",
            "url": "/health/live",
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
    """造一个"能真正跑通"的用例:接口 url 用路径(/health/live),配合 runner_env 的
    base_url 拼成完整地址,expected_status=200 → 执行必 passed。返回 case id。
    """
    def _make(path="/health/live", expected_status=200):
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
        "url": "/health/live",
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
