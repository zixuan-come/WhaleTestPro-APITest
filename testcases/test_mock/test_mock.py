import pytest
import allure

from common.yaml_util import load_yaml
from common.assert_util import assert_response, assert_values, skip_if_pending

_d = load_yaml("data/mock.yaml")
create_success = _d["create_success"]
list_success = _d["list_success"]
detail_success = _d["detail_success"]
detail_fail = _d["detail_fail"]
update_success = _d["update_success"]
delete_success = _d["delete_success"]
hit_success = _d["hit_success"]
hit_fail = _d["hit_fail"]
hit_methods = _d["hit_methods"]
create_no_token = _d["create_no_token"]
hit_not_matched = [c for c in hit_fail if c["case_id"] == "hit_mock_not_matched"]
hit_wrong_method = [c for c in hit_fail if c["case_id"] == "hit_mock_wrong_method"]


def _ids(cases):
    return [c["case_id"] for c in cases]


def _create(project_client, unique_name, name_prefix, path_prefix, method="GET", status=200, body=None):
    payload = {
        "name": unique_name(name_prefix),
        "path": unique_name(path_prefix),
        "method": method,
        "status": status,
    }
    if body is not None:
        payload["body"] = body
    resp = project_client.post("/mocks", json=payload)
    assert resp.status_code == 201, f"前置建 mock 应成功: {resp.text}"
    return resp.json()


@allure.feature("Mock 管理")
@allure.story("创建 Mock")
class TestCreateMock:

    @pytest.mark.parametrize("case", create_success, ids=_ids(create_success))
    def test_create_success(self, case, project_client, unique_name, api_cleanup):
        skip_if_pending(case)
        req = case["request"]
        name = unique_name(req["name_prefix"])
        path = unique_name(req["path_prefix"])
        resp = project_client.post("/mocks", json={
            "name": name,
            "path": path,
            "method": req["method"],
            "status": req["status"],
        })
        assert_response(resp, case["expected"])
        assert_values(resp, {"name": name, "path": path, "method": req["method"], "status": req["status"]})
        api_cleanup(f"/mocks/{resp.json()['id']}")

    @pytest.mark.parametrize("case", create_no_token, ids=_ids(create_no_token))
    def test_create_without_token(self, case, project_only_client, unique_name, api_cleanup):
        """特征化：mock 创建无鉴权，不带 token 也能建(201)——被测系统鉴权缺口。"""
        skip_if_pending(case)
        req = case["request"]
        resp = project_only_client.post("/mocks", json={
            "name": unique_name(req["name_prefix"]),
            "path": unique_name(req["path_prefix"]),
            "method": req["method"],
            "status": req["status"],
        })
        assert_response(resp, case["expected"])
        if resp.status_code < 300:
            api_cleanup(f"/mocks/{resp.json()['id']}")


@allure.feature("Mock 管理")
@allure.story("Mock 列表")
class TestListMock:

    @pytest.mark.parametrize("case", list_success, ids=_ids(list_success))
    def test_list_success(self, case, project_client):
        skip_if_pending(case)
        resp = project_client.get("/mocks")
        assert_response(resp, case["expected"])


@allure.feature("Mock 管理")
@allure.story("Mock 详情")
class TestGetMockDetail:

    @pytest.mark.parametrize("case", detail_success, ids=_ids(detail_success))
    def test_detail_success(self, case, project_client, unique_name, api_cleanup):
        skip_if_pending(case)
        mock = _create(project_client, unique_name, "auto_mock_get_", "/auto_mock_get_")
        api_cleanup(f"/mocks/{mock['id']}")
        resp = project_client.get(f"/mocks/{mock['id']}")
        assert_response(resp, case["expected"])

    @pytest.mark.parametrize("case", detail_fail, ids=_ids(detail_fail))
    def test_detail_fail(self, case, project_client):
        skip_if_pending(case)
        resp = project_client.get(f"/mocks/{case['request']['mock_id']}")
        assert_response(resp, case["expected"])


@allure.feature("Mock 管理")
@allure.story("更新 Mock")
class TestUpdateMock:

    @pytest.mark.parametrize("case", update_success, ids=_ids(update_success))
    def test_update_success(self, case, project_client, unique_name, api_cleanup):
        skip_if_pending(case)
        mock = _create(project_client, unique_name, "auto_mock_pre_", "/auto_mock_pre_")
        api_cleanup(f"/mocks/{mock['id']}")
        req = case["request"]
        name = unique_name(req["name_prefix"])
        path = unique_name(req["path_prefix"])
        resp = project_client.put(f"/mocks/{mock['id']}", json={
            "name": name,
            "path": path,
            "method": req["method"],
            "status": req["status"],
        })
        assert_response(resp, case["expected"])
        assert_values(resp, {"name": name, "path": path, "method": req["method"], "status": req["status"]})
        again = project_client.get(f"/mocks/{mock['id']}")
        assert_values(again, {"name": name, "path": path, "method": req["method"], "status": req["status"]})


@allure.feature("Mock 管理")
@allure.story("删除 Mock")
class TestDeleteMock:

    @pytest.mark.parametrize("case", delete_success, ids=_ids(delete_success))
    def test_delete_success(self, case, project_client, unique_name):
        skip_if_pending(case)
        mock = _create(project_client, unique_name, "auto_mock_del_", "/auto_mock_del_")
        resp = project_client.delete(f"/mocks/{mock['id']}")
        assert_response(resp, case["expected"])
        again = project_client.get(f"/mocks/{mock['id']}")
        assert again.status_code == 404, f"删除后再查应 404: {again.text}"


@allure.feature("Mock 管理")
@allure.story("命中 Mock")
class TestHitMock:

    @pytest.mark.parametrize("case", hit_success, ids=_ids(hit_success))
    def test_hit_success(self, case, project_client, client, project_id, unique_name, api_cleanup):
        """按 project_id + path 命中已注册的 mock 规则(命中接口本身不鉴权)。"""
        skip_if_pending(case)
        req = case["request"]
        mock = _create(project_client, unique_name, "auto_hit_", req["path_prefix"],
                       method=req["method"], status=req["status"], body=req["body"])
        api_cleanup(f"/mocks/{mock['id']}")
        full_path = mock["path"].lstrip("/")
        resp = client.get(f"/mock/{project_id}/{full_path}")
        assert_response(resp, case["expected"])

    @pytest.mark.parametrize("case", hit_methods, ids=_ids(hit_methods))
    def test_hit_each_method(self, case, project_client, client, project_id, unique_name, api_cleanup):
        """5 种方法各建一条同方法 mock 并命中 → 均 200。"""
        skip_if_pending(case)
        req = case["request"]
        mock = _create(project_client, unique_name, "auto_hitm_", req["path_prefix"],
                       method=req["method"], status=req["status"], body=req["body"])
        api_cleanup(f"/mocks/{mock['id']}")
        full_path = mock["path"].lstrip("/")
        resp = client.request(req["method"], f"/mock/{project_id}/{full_path}")
        assert_response(resp, case["expected"])

    @pytest.mark.parametrize("case", hit_wrong_method, ids=_ids(hit_wrong_method))
    def test_hit_wrong_method(self, case, project_client, client, project_id, unique_name, api_cleanup):
        """建 GET mock 但用 POST 命中 → 404 方法不匹配。"""
        skip_if_pending(case)
        req = case["request"]
        mock = _create(project_client, unique_name, "auto_hitwm_", req["path_prefix"],
                       method=req["created_method"], status=req["status"], body=req["body"])
        api_cleanup(f"/mocks/{mock['id']}")
        full_path = mock["path"].lstrip("/")
        resp = client.request(req["hit_method"], f"/mock/{project_id}/{full_path}")
        assert_response(resp, case["expected"])

    @pytest.mark.parametrize("case", hit_not_matched, ids=_ids(hit_not_matched))
    def test_hit_not_matched(self, case, client, project_id, unique_name):
        """命中不存在的路径 → 404 未匹配到 mock 规则。"""
        skip_if_pending(case)
        resp = client.get(f"/mock/{project_id}/{unique_name('auto_nomatch_')}")
        assert_response(resp, case["expected"])
