import uuid

import allure
import pytest

from common.request_util import RequestUtil
from common.yaml_util import load_yaml
from config import BASE_URL, RUNNER_BASE_URL


_matrix = load_yaml("data/permission_matrix.yaml")
WRITE_RESOURCES = _matrix["write_resources"]
EXECUTE_RESOURCES = _matrix["execute_resources"]


def _ids(cases):
    return [case["case_id"] for case in cases]


def _name(prefix):
    return f"{prefix}{uuid.uuid4().hex[:8]}"


def _envelope(response):
    return response.envelope_json()


def _assert_status(response, expected_status):
    assert response.status_code == expected_status, (
        f"状态码不符合预期: expected={expected_status}, "
        f"actual={response.status_code}, response={response.text}"
    )
    body = _envelope(response)
    if isinstance(body, dict) and "code" in body:
        expected_code = 0 if expected_status < 400 else expected_status
        assert body["code"] == expected_code, (
            f"业务码不符合预期: expected={expected_code}, "
            f"actual={body.get('code')}, response={response.text}"
        )


def _project_client(base_client, project_id):
    headers = dict(base_client.headers)
    headers["X-Project-Id"] = str(project_id)
    return RequestUtil(BASE_URL, headers=headers)


def _must_create(client, path, payload):
    response = client.post(path, json=payload)
    assert response.status_code == 201, f"权限矩阵前置数据创建失败: {response.text}"
    return response.json()


@pytest.fixture(scope="module")
def permission_context(auth_client, member_users, client):
    """仅通过 HTTP 创建角色、团队、项目和执行前置数据。"""
    primary = _must_create(
        auth_client,
        "/projects",
        {
            "name": _name("auto_permission_project_"),
            "description": "HTTP 黑盒权限矩阵主项目",
        },
    )
    project_id = primary["id"]
    team_id = primary["team_id"]

    for role in ("admin", "member"):
        response = auth_client.post(
            f"/teams/{team_id}/members",
            json={"user_id": member_users[role]["id"], "role": role},
        )
        assert response.status_code == 201, (
            f"权限矩阵添加 {role} 失败: {response.text}"
        )

    outsider_project = _must_create(
        member_users["outsider"]["client"],
        "/projects",
        {
            "name": _name("auto_permission_other_"),
            "description": "HTTP 黑盒权限矩阵跨项目",
        },
    )
    other_project_id = outsider_project["id"]
    other_team_id = outsider_project["team_id"]

    clients = {
        "owner": _project_client(auth_client, project_id),
        "admin": _project_client(member_users["admin"]["client"], project_id),
        "member": _project_client(member_users["member"]["client"], project_id),
        "outsider": _project_client(member_users["outsider"]["client"], project_id),
        "outsider_other": _project_client(
            member_users["outsider"]["client"], other_project_id
        ),
        "member_other": _project_client(
            member_users["member"]["client"], other_project_id
        ),
        "anonymous": RequestUtil(
            BASE_URL, headers={"X-Project-Id": str(project_id)}
        ),
    }

    owner = clients["owner"]
    seed_interface = _must_create(
        owner,
        "/interfaces",
        {"name": _name("auto_permission_if_"), "method": "GET", "url": "/health/live"},
    )
    runner_env = _must_create(
        owner,
        "/environments",
        {"name": _name("auto_permission_env_"), "base_url": RUNNER_BASE_URL},
    )
    seed_case = _must_create(
        owner,
        "/cases",
        {
            "name": _name("auto_permission_case_"),
            "interface_id": seed_interface["id"],
            "expected_status": 200,
        },
    )
    seed_scenario = _must_create(
        owner,
        "/scenarios",
        {
            "name": _name("auto_permission_scenario_"),
            "description": "权限执行矩阵",
            "case_ids": [seed_case["id"]],
        },
    )
    seed_suite = _must_create(
        owner,
        "/suites",
        {
            "name": _name("auto_permission_suite_"),
            "description": "权限执行矩阵",
            "type": "case",
            "case_ids": [seed_case["id"]],
        },
    )

    def set_permission(permission, enabled):
        response = auth_client.put(
            f"/teams/{team_id}/permissions",
            json={
                "role": "member",
                "permission": permission,
                "enabled": enabled,
            },
        )
        assert response.status_code == 200, (
            f"设置权限 {permission}={enabled} 失败: {response.text}"
        )

    for case in WRITE_RESOURCES:
        set_permission(case["permission"], False)

    context = {
        "project_id": project_id,
        "team_id": team_id,
        "other_project_id": other_project_id,
        "other_team_id": other_team_id,
        "clients": clients,
        "base_clients": {
            "owner": auth_client,
            "admin": member_users["admin"]["client"],
            "member": member_users["member"]["client"],
            "outsider": member_users["outsider"]["client"],
            "anonymous": client,
        },
        "users": member_users,
        "set_permission": set_permission,
        "interface_id": seed_interface["id"],
        "env_id": runner_env["id"],
        "case_id": seed_case["id"],
        "scenario_id": seed_scenario["id"],
        "suite_id": seed_suite["id"],
    }

    try:
        yield context
    finally:
        try:
            auth_client.delete(f"/projects/{project_id}")
        except Exception:
            pass
        try:
            auth_client.delete(f"/teams/{team_id}")
        except Exception:
            pass
        try:
            member_users["outsider"]["client"].delete(
                f"/projects/{other_project_id}"
            )
        except Exception:
            pass
        try:
            member_users["outsider"]["client"].delete(f"/teams/{other_team_id}")
        except Exception:
            pass


def _resource_payload(resource, context):
    payloads = {
        "interface": {
            "name": _name("auto_matrix_if_"),
            "method": "GET",
            "url": "/health/live",
        },
        "case": {
            "name": _name("auto_matrix_case_"),
            "interface_id": context["interface_id"],
            "expected_status": 200,
        },
        "environment": {
            "name": _name("auto_matrix_env_"),
            "base_url": "http://localhost:8000",
        },
        "mock": {
            "name": _name("auto_matrix_mock_"),
            "path": f"/matrix/{uuid.uuid4().hex[:8]}",
            "method": "GET",
            "status": 200,
            "body": {"permission": "ok"},
        },
        "schedule": {
            "name": _name("auto_matrix_schedule_"),
            "cron": "0 0 * * *",
        },
        "perf": {
            "name": _name("auto_matrix_perf_"),
            "target_host": "http://localhost:8000",
            "target_path": "/health/live",
            "users": 1,
            "spawn_rate": 1,
            "duration": 1,
        },
        "scenario": {
            "name": _name("auto_matrix_scenario_"),
            "description": "write permission matrix",
            "case_ids": [],
        },
        "suite": {
            "name": _name("auto_matrix_suite_"),
            "description": "write permission matrix",
            "type": "case",
            "case_ids": [],
        },
    }
    return payloads[resource]


def _create_resource(case, actor_client, context):
    return actor_client.post(
        case["collection"],
        json=_resource_payload(case["resource"], context),
    )


def _delete_created_resource(case, response, context):
    if response.status_code >= 300:
        return
    resource_id = response.json()["id"]
    cleanup = context["clients"]["owner"].delete(
        case["delete_path"].format(id=resource_id)
    )
    assert cleanup.status_code == 200, f"权限矩阵资源清理失败: {cleanup.text}"


@allure.feature("HTTP 黑盒权限矩阵")
@allure.story("八类资源写权限")
@pytest.mark.parametrize("case", WRITE_RESOURCES, ids=_ids(WRITE_RESOURCES))
def test_write_permission_matrix(case, permission_context):
    """同一写操作覆盖 Owner/Admin/Member 开关/未入组用户五种身份。"""
    context = permission_context
    clients = context["clients"]

    context["set_permission"](case["permission"], False)
    for actor, expected_status in (
        ("owner", 201),
        ("admin", 201),
        ("member", 403),
        ("outsider", 404),
    ):
        response = _create_resource(case, clients[actor], context)
        _assert_status(response, expected_status)
        _delete_created_resource(case, response, context)

    context["set_permission"](case["permission"], True)
    response = _create_resource(case, clients["member"], context)
    _assert_status(response, 201)
    _delete_created_resource(case, response, context)


@allure.feature("HTTP 黑盒权限矩阵")
@allure.story("读取权限和项目访问边界")
@pytest.mark.parametrize("case", WRITE_RESOURCES, ids=_ids(WRITE_RESOURCES))
def test_read_permission_matrix(case, permission_context):
    member_response = permission_context["clients"]["member"].get(case["collection"])
    _assert_status(member_response, 200)

    outsider_response = permission_context["clients"]["outsider"].get(
        case["collection"]
    )
    _assert_status(outsider_response, 404)


def _execute(case, actor_client, context):
    path = case["path"].format(**context)
    kwargs = {}
    if case["resource"] in {"interface", "case", "scenario", "suite", "regression"}:
        kwargs["params"] = {"env_id": context["env_id"]}
    if case["resource"] == "regression":
        kwargs["json"] = [context["case_id"]]
    if case["resource"] == "traffic":
        kwargs["json"] = {}
    return actor_client.post(path, **kwargs)


@allure.feature("HTTP 黑盒权限矩阵")
@allure.story("执行权限与写权限相互独立")
@pytest.mark.parametrize(
    "case", EXECUTE_RESOURCES, ids=_ids(EXECUTE_RESOURCES)
)
def test_execute_permission_matrix(case, permission_context):
    context = permission_context
    if case.get("write_permission"):
        context["set_permission"](case["write_permission"], False)

    member_response = _execute(case, context["clients"]["member"], context)
    _assert_status(member_response, case["expected_status"])
    if case.get("expected_message"):
        assert _envelope(member_response)["message"] == case["expected_message"]

    outsider_response = _execute(case, context["clients"]["outsider"], context)
    _assert_status(outsider_response, 404)
    assert "不存在或无权访问" in _envelope(outsider_response)["message"]


@allure.feature("HTTP 黑盒权限矩阵")
@allure.story("团队管理权限")
def test_manage_permission_matrix(permission_context):
    context = permission_context
    team_id = context["team_id"]
    clients = context["base_clients"]

    for actor, expected_status in (
        ("owner", 200),
        ("admin", 200),
        ("member", 200),
        ("outsider", 404),
    ):
        response = clients[actor].get(f"/teams/{team_id}/permissions")
        _assert_status(response, expected_status)

    payload = {
        "role": "member",
        "permission": "suite.write",
        "enabled": False,
    }
    for actor, expected_status in (
        ("owner", 200),
        ("admin", 200),
        ("member", 403),
        ("outsider", 404),
    ):
        response = clients[actor].put(
            f"/teams/{team_id}/permissions", json=payload
        )
        _assert_status(response, expected_status)

    keyword = context["users"]["outsider"]["username"]
    for actor, expected_status in (
        ("owner", 200),
        ("admin", 200),
        ("member", 403),
        ("outsider", 404),
    ):
        response = clients[actor].get(
            f"/teams/{team_id}/member-candidates",
            params={"keyword": keyword},
        )
        _assert_status(response, expected_status)


@allure.feature("HTTP 黑盒权限矩阵")
@allure.story("Owner 专属项目操作")
def test_project_delete_is_owner_only(permission_context):
    context = permission_context
    project = _must_create(
        context["base_clients"]["owner"],
        "/projects",
        {
            "name": _name("auto_owner_delete_"),
            "description": "owner delete permission",
            "team_id": context["team_id"],
        },
    )
    path = f"/projects/{project['id']}"

    for actor, expected_status in (
        ("admin", 403),
        ("member", 403),
        ("outsider", 404),
    ):
        response = context["base_clients"][actor].delete(path)
        _assert_status(response, expected_status)

    owner_response = context["base_clients"]["owner"].delete(path)
    _assert_status(owner_response, 200)


@allure.feature("HTTP 黑盒权限矩阵")
@allure.story("Owner 专属项目迁移")
def test_project_move_team_is_owner_only(permission_context):
    context = permission_context
    owner = context["base_clients"]["owner"]
    destination = _must_create(
        owner,
        "/teams",
        {"name": _name("auto_move_target_"), "description": "迁移目标团队"},
    )
    project = _must_create(
        owner,
        "/projects",
        {
            "name": _name("auto_owner_move_"),
            "description": "owner move permission",
            "team_id": context["team_id"],
        },
    )
    path = f"/projects/{project['id']}/move-team"
    payload = {"team_id": destination["id"]}

    try:
        for actor, expected_status in (
            ("admin", 403),
            ("member", 403),
            ("outsider", 404),
        ):
            response = context["base_clients"][actor].post(path, json=payload)
            _assert_status(response, expected_status)

        owner_response = owner.post(path, json=payload)
        _assert_status(owner_response, 200)
        assert owner_response.json()["team_id"] == destination["id"]
    finally:
        owner.delete(f"/projects/{project['id']}")
        owner.delete(f"/teams/{destination['id']}")


@allure.feature("HTTP 黑盒权限矩阵")
@allure.story("团队成员移除后立即失去项目访问权")
def test_removed_team_member_immediately_loses_project_access(permission_context):
    context = permission_context
    owner = context["base_clients"]["owner"]
    outsider_id = context["users"]["outsider"]["id"]
    created = owner.post(
        f"/teams/{context['team_id']}/members",
        json={"user_id": outsider_id, "role": "member"},
    )
    _assert_status(created, 201)
    member_id = created.json()["id"]

    try:
        before = context["clients"]["outsider"].get("/suites")
        _assert_status(before, 200)
    finally:
        removed = owner.delete(
            f"/teams/{context['team_id']}/members/{member_id}"
        )
        _assert_status(removed, 200)

    after = context["clients"]["outsider"].get("/suites")
    _assert_status(after, 404)


@allure.feature("HTTP 黑盒权限矩阵")
@allure.story("跨项目资源 ID 隔离")
def test_cross_project_resource_id_is_not_visible(permission_context):
    context = permission_context
    response = context["clients"]["outsider_other"].get(
        f"/interfaces/{context['interface_id']}"
    )
    _assert_status(response, 404)
    assert "接口 id=" in _envelope(response)["message"]

    non_member = context["clients"]["member_other"].get("/interfaces")
    _assert_status(non_member, 404)
    assert "不存在或无权访问" in _envelope(non_member)["message"]


@allure.feature("HTTP 黑盒权限矩阵")
@allure.story("认证和项目头边界")
def test_authentication_and_project_header_boundaries(permission_context):
    anonymous = permission_context["clients"]["anonymous"].get("/suites")
    _assert_status(anonymous, 401)

    no_project_header = permission_context["base_clients"]["member"].get("/suites")
    _assert_status(no_project_header, 422)


@allure.feature("HTTP 黑盒权限矩阵")
@allure.story("公共 Mock 命中入口")
def test_public_mock_hit_does_not_require_login(permission_context):
    context = permission_context
    mock_path = f"/permission-public/{uuid.uuid4().hex[:8]}"
    created = context["clients"]["owner"].post(
        "/mocks",
        json={
            "name": _name("auto_public_mock_"),
            "path": mock_path,
            "method": "GET",
            "status": 202,
            "body": {"public": True},
        },
    )
    _assert_status(created, 201)

    try:
        hit = context["base_clients"]["anonymous"].get(
            f"/mock/{context['project_id']}{mock_path}"
        )
        assert hit.status_code == 202, hit.text
        assert hit.json() == {"public": True}
    finally:
        cleanup = context["clients"]["owner"].delete(
            f"/mocks/{created.json()['id']}"
        )
        _assert_status(cleanup, 200)
