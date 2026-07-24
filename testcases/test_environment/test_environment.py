import pytest
import allure

from common.yaml_util import load_yaml
from common.assert_util import assert_response, assert_values, skip_if_pending

_d = load_yaml("data/environment.yaml")
create_success = _d["create_success"]
list_success = _d["list_success"]
detail_success = _d["detail_success"]
detail_fail = _d["detail_fail"]
update_success = _d["update_success"]
delete_success = _d["delete_success"]
create_no_token = _d["create_no_token"]


def _ids(cases):
    return [c["case_id"] for c in cases]


def _create(project_client, unique_name, prefix, base_url):
    resp = project_client.post("/environments", json={
        "name": unique_name(prefix), "base_url": base_url,
    })
    assert resp.status_code == 201, f"前置建环境应成功: {resp.text}"
    return resp.json()["id"]


@allure.feature("环境管理")
@allure.story("创建环境")
class TestCreateEnvironment:

    @pytest.mark.parametrize("case", create_success, ids=_ids(create_success))
    def test_create_success(self, case, project_client, unique_name, api_cleanup):
        skip_if_pending(case)
        req = case["request"]
        name = unique_name(req["name_prefix"])
        resp = project_client.post("/environments", json={
            "name": name, "base_url": req["base_url"],
        })
        assert_response(resp, case["expected"])
        assert_values(resp, {"name": name, "base_url": req["base_url"]})
        api_cleanup(f"/environments/{resp.json()['id']}")

    @pytest.mark.parametrize("case", create_no_token, ids=_ids(create_no_token))
    def test_create_without_token(self, case, project_only_client, unique_name, api_cleanup):
        """特征化：environment 创建无鉴权，不带 token 也能建(201)——被测系统鉴权缺口。"""
        skip_if_pending(case)
        req = case["request"]
        resp = project_only_client.post("/environments", json={
            "name": unique_name(req["name_prefix"]), "base_url": req["base_url"],
        })
        assert_response(resp, case["expected"])
        if resp.status_code < 300:
            api_cleanup(f"/environments/{resp.json()['id']}")


@allure.feature("环境管理")
@allure.story("环境列表")
class TestListEnvironment:

    @pytest.mark.parametrize("case", list_success, ids=_ids(list_success))
    def test_list_success(self, case, project_client):
        skip_if_pending(case)
        resp = project_client.get("/environments")
        assert_response(resp, case["expected"])


@allure.feature("环境管理")
@allure.story("环境详情")
class TestGetEnvironmentDetail:

    @pytest.mark.parametrize("case", detail_success, ids=_ids(detail_success))
    def test_detail_success(self, case, project_client, unique_name, api_cleanup):
        skip_if_pending(case)
        eid = _create(project_client, unique_name, "auto_env_get_", "http://localhost:8001")
        api_cleanup(f"/environments/{eid}")
        resp = project_client.get(f"/environments/{eid}")
        assert_response(resp, case["expected"])

    @pytest.mark.parametrize("case", detail_fail, ids=_ids(detail_fail))
    def test_detail_fail(self, case, project_client):
        skip_if_pending(case)
        resp = project_client.get(f"/environments/{case['request']['env_id']}")
        assert_response(resp, case["expected"])


@allure.feature("环境管理")
@allure.story("更新环境")
class TestUpdateEnvironment:

    @pytest.mark.parametrize("case", update_success, ids=_ids(update_success))
    def test_update_success(self, case, project_client, unique_name, api_cleanup):
        skip_if_pending(case)
        eid = _create(project_client, unique_name, "auto_env_pre_", "http://localhost:8001")
        api_cleanup(f"/environments/{eid}")
        req = case["request"]
        name = unique_name(req["name_prefix"])
        resp = project_client.put(f"/environments/{eid}", json={
            "name": name, "base_url": req["base_url"],
        })
        assert_response(resp, case["expected"])
        assert_values(resp, {"name": name, "base_url": req["base_url"]})
        again = project_client.get(f"/environments/{eid}")
        assert_values(again, {"name": name, "base_url": req["base_url"]})


@allure.feature("环境管理")
@allure.story("删除环境")
class TestDeleteEnvironment:

    @pytest.mark.parametrize("case", delete_success, ids=_ids(delete_success))
    def test_delete_success(self, case, project_client, unique_name):
        skip_if_pending(case)
        eid = _create(project_client, unique_name, "auto_env_del_", "http://localhost:8001")
        resp = project_client.delete(f"/environments/{eid}")
        assert_response(resp, case["expected"])
        again = project_client.get(f"/environments/{eid}")
        assert again.status_code == 404, f"删除后再查应 404: {again.text}"
