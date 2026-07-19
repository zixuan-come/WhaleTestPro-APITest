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

    @pytest.mark.smoke
    @pytest.mark.parametrize("case", create_success, ids=_ids(create_success))
    def test_create_success(self, case, auth_client, unique_name, project_cleanup):
        skip_if_pending(case)
        req = case["request"]
        body = {
            "name": unique_name(req["name_prefix"]),
            "description": req["description"],
        }
        resp = auth_client.post("/projects", json=body)
        assert_response(resp, case["expected"])
        assert_values(resp, {"name": body["name"], "description": body["description"]})
        # 登记以便测试结束后清理
        project_cleanup(resp.json()["id"])

    def test_create_duplicate_name(self, auth_client, unique_name, project_cleanup):
        """重名冲突 → 409。先建一个占名,再用同名建第二个。"""
        case = next(c for c in create_fail if c["case_id"] == "duplicate_project_name")
        skip_if_pending(case)
        name = unique_name(case["request"]["name_prefix"])
        desc = case["request"]["description"]

        first = auth_client.post("/projects", json={"name": name, "description": desc})
        assert first.status_code == 201, f"前置建项目应成功: {first.text}"
        project_cleanup(first.json()["id"])

        resp = auth_client.post("/projects", json={"name": name, "description": desc})
        assert_response(resp, case["expected"])

    def test_create_missing_name(self, auth_client):
        """缺 name 字段 → 422 (Pydantic 校验失败)。"""
        case = next(c for c in create_fail if c["case_id"] == "missing_project_name")
        skip_if_pending(case)
        resp = auth_client.post("/projects", json={"description": case["request"]["description"]})
        assert_response(resp, case["expected"])

    def test_create_without_token(self, client, unique_name):
        """不带 token → 401 Not authenticated。"""
        case = next(c for c in create_fail if c["case_id"] == "create_project_without_token")
        skip_if_pending(case)
        req = case["request"]
        body = {"name": unique_name(req["name_prefix"]), "description": req["description"]}
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
    def test_detail_success(self, case, auth_client, unique_name, project_cleanup):
        skip_if_pending(case)
        req = case["request"]
        name = unique_name(req["name_prefix"])
        created = auth_client.post("/projects", json={"name": name, "description": req["description"]})
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
@allure.story("删除项目")
class TestDeleteProject:

    @pytest.mark.parametrize("case", delete_success, ids=_ids(delete_success))
    def test_delete_success(self, case, auth_client, unique_name):
        skip_if_pending(case)
        req = case["request"]
        name = unique_name(req["name_prefix"])
        created = auth_client.post("/projects", json={"name": name, "description": req["description"]})
        assert created.status_code == 201, f"前置建项目应成功: {created.text}"
        pid = created.json()["id"]

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
