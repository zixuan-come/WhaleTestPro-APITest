import pytest
import allure

from common.yaml_util import load_yaml
from common.assert_util import assert_response, assert_values, skip_if_pending

_d = load_yaml("data/interface.yaml")
create_success = _d["create_success"]
create_fail = _d["create_fail"]
list_success = _d["list_success"]
detail_success = _d["detail_success"]
detail_fail = _d["detail_fail"]
update_success = _d["update_success"]
delete_success = _d["delete_success"]
category_rename = _d["category_rename"]
category_delete = _d["category_delete"]


def _ids(cases):
    return [c["case_id"] for c in cases]


@allure.feature("接口管理")
@allure.story("创建接口")
class TestCreateInterface:

    @pytest.mark.parametrize("case", create_success, ids=_ids(create_success))
    def test_create_success(self, case, project_client, unique_name, api_cleanup):
        skip_if_pending(case)
        req = case["request"]
        name = unique_name(req["name_prefix"])
        resp = project_client.post("/interfaces", json={
            "name": name,
            "method": req["method"],
            "url": req["url"],
        })
        assert_response(resp, case["expected"])
        assert_values(resp, {"name": name, "method": req["method"], "url": req["url"]})
        api_cleanup(f"/interfaces/{resp.json()['id']}")

    def test_create_without_token(self, client, unique_name):
        """不带 token → 401 Not authenticated。"""
        case = next(c for c in create_fail if c["case_id"] == "create_interface_without_token")
        skip_if_pending(case)
        req = case["request"]
        resp = client.post("/interfaces", json={
            "name": unique_name(req["name_prefix"]), "method": req["method"], "url": req["url"],
        })
        assert_response(resp, case["expected"])

    def test_create_without_project(self, auth_client, unique_name):
        """带 token 但缺 X-Project-Id 头 → 422(缺必填 header)。"""
        case = next(c for c in create_fail if c["case_id"] == "create_interface_without_project")
        skip_if_pending(case)
        req = case["request"]
        resp = auth_client.post("/interfaces", json={
            "name": unique_name(req["name_prefix"]), "method": req["method"], "url": req["url"],
        })
        assert_response(resp, case["expected"])


@allure.feature("接口管理")
@allure.story("接口列表")
class TestListInterface:

    @pytest.mark.parametrize("case", list_success, ids=_ids(list_success))
    def test_list_success(self, case, project_client):
        skip_if_pending(case)
        resp = project_client.get("/interfaces")
        assert_response(resp, case["expected"])


@allure.feature("接口管理")
@allure.story("接口详情")
class TestGetInterfaceDetail:

    @pytest.mark.parametrize("case", detail_success, ids=_ids(detail_success))
    def test_detail_success(self, case, project_client, seed_interface):
        skip_if_pending(case)
        iid = seed_interface()
        resp = project_client.get(f"/interfaces/{iid}")
        assert_response(resp, case["expected"])

    @pytest.mark.parametrize("case", detail_fail, ids=_ids(detail_fail))
    def test_detail_fail(self, case, project_client):
        skip_if_pending(case)
        resp = project_client.get(f"/interfaces/{case['request']['interface_id']}")
        assert_response(resp, case["expected"])


@allure.feature("接口管理")
@allure.story("更新接口")
class TestUpdateInterface:

    @pytest.mark.parametrize("case", update_success, ids=_ids(update_success))
    def test_update_success(self, case, project_client, seed_interface, unique_name):
        skip_if_pending(case)
        iid = seed_interface()
        req = case["request"]
        name = unique_name(req["name_prefix"])
        resp = project_client.put(f"/interfaces/{iid}", json={
            "name": name,
            "method": req["method"],
            "url": req["url"],
        })
        assert_response(resp, case["expected"])
        assert_values(resp, {"name": name, "method": req["method"], "url": req["url"]})
        again = project_client.get(f"/interfaces/{iid}")
        assert_values(again, {"name": name, "method": req["method"], "url": req["url"]})


@allure.feature("接口管理")
@allure.story("删除接口")
class TestDeleteInterface:

    @pytest.mark.parametrize("case", delete_success, ids=_ids(delete_success))
    def test_delete_success(self, case, project_client, unique_name):
        skip_if_pending(case)
        created = project_client.post("/interfaces", json={
            "name": unique_name("auto_if_del_"), "method": "GET", "url": "http://localhost:8001/health",
        })
        assert created.status_code == 201, f"前置建接口应成功: {created.text}"
        iid = created.json()["id"]
        resp = project_client.delete(f"/interfaces/{iid}")
        assert_response(resp, case["expected"])
        again = project_client.get(f"/interfaces/{iid}")
        assert again.status_code == 404, f"删除后再查应 404: {again.text}"


@allure.feature("接口管理")
@allure.story("接口分类")
class TestInterfaceCategory:

    @pytest.mark.parametrize("case", category_rename, ids=_ids(category_rename))
    def test_rename_category_success(self, case, project_client, unique_name, api_cleanup):
        """建带 category 的接口，改名分类 → 200。"""
        skip_if_pending(case)
        old_cat = unique_name("auto_cat_old_")
        created = project_client.post("/interfaces", json={
            "name": unique_name("auto_if_cat_"), "method": "GET",
            "url": "http://localhost:8001/health", "category": old_cat,
        })
        assert created.status_code == 201, f"前置建接口应成功: {created.text}"
        api_cleanup(f"/interfaces/{created.json()['id']}")
        new_cat = unique_name(case["request"]["new_name_prefix"])
        resp = project_client.patch("/interfaces/categories/rename",
                                    json={"old_name": old_cat, "new_name": new_cat})
        assert_response(resp, case["expected"])

    @pytest.mark.parametrize("case", category_delete, ids=_ids(category_delete))
    def test_delete_category_success(self, case, project_client, unique_name, api_cleanup):
        """建带 category 的接口，删该分类 → 200。"""
        skip_if_pending(case)
        cat = unique_name("auto_cat_del_")
        created = project_client.post("/interfaces", json={
            "name": unique_name("auto_if_cat_"), "method": "GET",
            "url": "http://localhost:8001/health", "category": cat,
        })
        assert created.status_code == 201, f"前置建接口应成功: {created.text}"
        api_cleanup(f"/interfaces/{created.json()['id']}")
        resp = project_client.delete(f"/interfaces/categories/{cat}")
        assert_response(resp, case["expected"])
