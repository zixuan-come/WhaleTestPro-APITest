import pytest
import allure

from common.yaml_util import load_yaml
from common.assert_util import assert_response, assert_values, skip_if_pending

# ---- 数据外置：按操作分文件，每文件内再分 success / fail 组 ----
create_success = load_yaml("data/project/create_project.yaml")["create_project_success"]
create_fail = load_yaml("data/project/create_project.yaml")["create_project_fail"]
list_success = load_yaml("data/project/list_project.yaml")["list_project_success"]
list_fail = load_yaml("data/project/list_project.yaml")["list_project_fail"]
detail_success = load_yaml("data/project/get_project_detail.yaml")["get_project_detail_success"]
detail_fail = load_yaml("data/project/get_project_detail.yaml")["get_project_detail_fail"]
update_success = load_yaml("data/project/update_project.yaml")["update_project_success"]
update_fail = load_yaml("data/project/update_project.yaml")["update_project_fail"]
update_role_access = load_yaml("data/project/update_project.yaml")["update_project_role_access"]
delete_success = load_yaml("data/project/delete_project.yaml")["delete_project_success"]
delete_fail = load_yaml("data/project/delete_project.yaml")["delete_project_fail"]


def _ids(cases):
    return [c["case_id"] for c in cases]


def _pick_client(case, auth_client, client):
    # request 里显式写了 headers: {} 表示"不带 token",用无鉴权 client;否则用带 token 的
    if "headers" in case.get("request", {}):
        return client
    return auth_client


@allure.feature("项目管理")
@allure.story("创建项目")
class TestCreateProject:

    @pytest.mark.parametrize("actor, expected_status", [("owner", 201), ("admin", 201), ("member", 403), ("outsider", 403)])
    def test_explicit_team_creation_role_matrix(self, actor, expected_status, team_member_context, unique_name):
        context = team_member_context
        response = context["clients"][actor].post("/projects", json={
            "name": unique_name("auto_project_role_"), "team_id": context["team_id"],
        })
        try:
            assert_response(response, {"status_code": expected_status})
            if expected_status == 201:
                assert_values(response, {"team_id": context["team_id"]})
        finally:
            if response.status_code == 201:
                context["clients"]["owner"].delete(f"/projects/{response.json()['id']}")

    def test_create_requires_explicit_team(self, auth_client, unique_name):
        response = auth_client.post("/projects", json={"name": unique_name("auto_no_team_")})
        assert response.status_code == 422, response.text
        errors = response.envelope_json()["data"]["errors"]
        assert any(error["field"] == "team_id" for error in errors)

    @pytest.mark.smoke
    @pytest.mark.parametrize("case", create_success, ids=_ids(create_success))
    def test_create_success(self, case, auth_client, unique_name, project_cleanup, team_id):
        skip_if_pending(case)
        req = case["request"]
        body = {
            "name": unique_name(req["name_prefix"]),
            "description": req["description"],
            "team_id": team_id,
        }
        resp = auth_client.post("/projects", json=body)
        assert_response(resp, case["expected"])
        assert_values(resp, {"name": body["name"], "description": body["description"]})
        # 登记以便测试结束后清理
        project_cleanup(resp.json()["id"])

    def test_create_duplicate_name(self, auth_client, unique_name, project_cleanup, team_id):
        """重名冲突 → 409。先建一个占名,再用同名建第二个。"""
        case = next(c for c in create_fail if c["case_id"] == "duplicate_project_name")
        skip_if_pending(case)
        name = unique_name(case["request"]["name_prefix"])
        desc = case["request"]["description"]

        first = auth_client.post("/projects", json={"name": name, "description": desc, "team_id": team_id})
        assert first.status_code == 201, f"前置建项目应成功: {first.text}"
        project_cleanup(first.json()["id"])

        resp = auth_client.post("/projects", json={"name": name, "description": desc, "team_id": team_id})
        assert_response(resp, case["expected"])

    def test_create_missing_name(self, auth_client, team_id):
        """缺 name 字段 → 422 (Pydantic 校验失败)。"""
        case = next(c for c in create_fail if c["case_id"] == "missing_project_name")
        skip_if_pending(case)
        resp = auth_client.post("/projects", json={"description": case["request"]["description"], "team_id": team_id})
        assert_response(resp, case["expected"])

    def test_create_without_token(self, client, unique_name, team_id):
        """不带 token → 401 Not authenticated。"""
        case = next(c for c in create_fail if c["case_id"] == "create_project_without_token")
        skip_if_pending(case)
        req = case["request"]
        body = {"name": unique_name(req["name_prefix"]), "description": req["description"], "team_id": team_id}
        resp = client.post("/projects", json=body)
        assert_response(resp, case["expected"])


@allure.feature("项目管理")
@allure.story("项目列表")
class TestListProject:

    @pytest.mark.parametrize("case", list_success, ids=_ids(list_success))
    def test_list_success(self, case, auth_client):
        skip_if_pending(case)
        resp = auth_client.get("/projects")
        assert_response(resp, case["expected"])

    @pytest.mark.parametrize("case", list_fail, ids=_ids(list_fail))
    def test_list_fail(self, case, client):
        skip_if_pending(case)
        resp = client.get("/projects")
        assert_response(resp, case["expected"])


@allure.feature("项目管理")
@allure.story("项目详情")
class TestGetProjectDetail:

    @pytest.mark.parametrize("case", detail_success, ids=_ids(detail_success))
    def test_detail_success(self, case, auth_client, unique_name, project_cleanup, team_id):
        skip_if_pending(case)
        req = case["request"]
        name = unique_name(req["name_prefix"])
        created = auth_client.post("/projects", json={"name": name, "description": req["description"], "team_id": team_id})
        assert created.status_code == 201, f"前置建项目应成功: {created.text}"
        pid = project_cleanup(created.json()["id"])

        resp = auth_client.get(f"/projects/{pid}")
        assert_response(resp, case["expected"])

    @pytest.mark.parametrize("case", detail_fail, ids=_ids(detail_fail))
    def test_detail_fail(self, case, auth_client, client):
        skip_if_pending(case)
        target = _pick_client(case, auth_client, client)
        resp = target.get(f"/projects/{case['request']['project_id']}")
        assert_response(resp, case["expected"])


@allure.feature("项目管理")
@allure.story("修改项目")
class TestUpdateProject:

    @pytest.mark.parametrize("case", update_success, ids=_ids(update_success))
    def test_update_success(self, case, auth_client, unique_name, project_cleanup, team_id):
        original_name = unique_name("auto_project_before_update_")
        created = auth_client.post(
            "/projects",
            json={"name": original_name, "description": "before update", "team_id": team_id},
        )
        assert created.status_code == 201, f"前置建项目应成功: {created.text}"
        project_id = project_cleanup(created.json()["id"])

        body = {
            "name": unique_name(case["request"]["name_prefix"]),
            "description": case["request"]["description"],
        }
        response = auth_client.put(f"/projects/{project_id}", json=body)
        assert_response(response, case["expected"])
        assert_values(response, body)

        detail = auth_client.get(f"/projects/{project_id}")
        assert detail.status_code == 200
        assert_values(detail, body)

    def test_update_duplicate_name(self, auth_client, unique_name, project_cleanup, team_id):
        case = next(
            item for item in update_fail
            if item["case_id"] == "update_project_duplicate_name"
        )
        occupied_name = unique_name(case["request"]["name_prefix"])
        first = auth_client.post(
            "/projects",
            json={"name": unique_name("auto_project_update_target_"), "description": None, "team_id": team_id},
        )
        second = auth_client.post(
            "/projects",
            json={"name": occupied_name, "description": None, "team_id": team_id},
        )
        assert first.status_code == second.status_code == 201
        project_cleanup(first.json()["id"])
        project_cleanup(second.json()["id"])

        response = auth_client.put(
            f"/projects/{first.json()['id']}",
            json={"name": occupied_name, "description": case["request"]["description"]},
        )
        assert_response(response, case["expected"])

    @pytest.mark.parametrize(
        "case",
        [
            item for item in update_fail
            if item["case_id"] in {
                "update_project_not_exist",
                "update_project_without_token",
            }
        ],
        ids=lambda case: case["case_id"],
    )
    def test_update_access_fail(self, case, auth_client, client):
        target = client if case["actor"] == "anonymous" else auth_client
        request = case["request"]
        response = target.put(
            f"/projects/{request['project_id']}",
            json={"name": request["name"], "description": request["description"]},
        )
        assert_response(response, case["expected"])

    @pytest.mark.parametrize(
        "case",
        update_role_access,
        ids=lambda case: case["case_id"],
    )
    def test_update_role_access(self, case, team_member_context, unique_name):
        context = team_member_context
        response = context["clients"][case["actor"]].put(
            f"/projects/{context['project_id']}",
            json={
                "name": unique_name(case["request"]["name_prefix"]),
                "description": case["request"]["description"],
            },
        )
        assert_response(response, case["expected"])


@allure.feature("项目管理")
@allure.story("删除项目")
class TestDeleteProject:

    @pytest.mark.parametrize("case", delete_success, ids=_ids(delete_success))
    def test_delete_success(self, case, auth_client, unique_name, team_id, project_cleanup):
        skip_if_pending(case)
        req = case["request"]
        name = unique_name(req["name_prefix"])
        created = auth_client.post("/projects", json={"name": name, "description": req["description"], "team_id": team_id})
        assert created.status_code == 201, f"前置建项目应成功: {created.text}"
        pid = created.json()["id"]
        project_cleanup(pid)

        project_headers = {"X-Project-Id": str(pid)}
        interface = auth_client.post(
            "/interfaces",
            headers=project_headers,
            json={
                "name": unique_name("auto_delete_interface_"),
                "method": "GET",
                "url": "/health/live",
            },
        )
        assert interface.status_code == 201, f"前置建接口应成功: {interface.text}"
        test_case = auth_client.post(
            "/cases",
            headers=project_headers,
            json={
                "name": unique_name("auto_delete_case_"),
                "interface_id": interface.json()["id"],
                "expected_status": 200,
            },
        )
        assert test_case.status_code == 201, f"前置建用例应成功: {test_case.text}"

        environment = auth_client.post("/environments", headers=project_headers,
                                       json={"name": unique_name("auto_delete_env_"), "base_url": "http://app:8000"})
        assert environment.status_code == 201, environment.text
        schedule = auth_client.post("/schedules", headers=project_headers,
                                    json={"name": unique_name("auto_delete_schedule_"), "cron": "0 0 * * *",
                                          "env_id": environment.json()["id"], "enabled": False})
        assert schedule.status_code == 201, schedule.text

        resp = auth_client.delete(f"/projects/{pid}")
        assert_response(resp, case["expected"])
        # 已删除,无需登记清理;确认再查 404
        again = auth_client.get(f"/projects/{pid}")
        assert again.status_code == 404, f"删除后再查应 404: {again.text}"

    @pytest.mark.parametrize("case", delete_fail, ids=_ids(delete_fail))
    def test_delete_fail(self, case, auth_client, client):
        skip_if_pending(case)
        target = _pick_client(case, auth_client, client)
        resp = target.delete(f"/projects/{case['request']['project_id']}")
        assert_response(resp, case["expected"])
