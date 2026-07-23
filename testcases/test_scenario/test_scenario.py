import pytest
import allure

from common.yaml_util import load_yaml
from common.assert_util import assert_response, assert_values, skip_if_pending

_d = load_yaml("data/scenario.yaml")
create_success = _d["create_success"]
list_success = _d["list_success"]
detail_success = _d["detail_success"]
detail_fail = _d["detail_fail"]
update_success = _d["update_success"]
delete_success = _d["delete_success"]
run_success = _d["run_success"]
create_no_token = _d["create_no_token"]


def _ids(cases):
    return [c["case_id"] for c in cases]


def _create(project_client, seed_case, unique_name, prefix, description):
    cid = seed_case()
    resp = project_client.post("/scenarios", json={
        "name": unique_name(prefix),
        "description": description,
        "case_ids": [cid],
    })
    assert resp.status_code == 201, f"前置建场景应成功: {resp.text}"
    return resp.json()["id"]


@allure.feature("场景管理")
@allure.story("创建场景")
class TestCreateScenario:

    @pytest.mark.parametrize("case", create_success, ids=_ids(create_success))
    def test_create_success(self, case, project_client, seed_case, unique_name, api_cleanup):
        skip_if_pending(case)
        req = case["request"]
        name = unique_name(req["name_prefix"])
        cid = seed_case()
        resp = project_client.post("/scenarios", json={
            "name": name,
            "description": req["description"],
            "case_ids": [cid],
        })
        assert_response(resp, case["expected"])
        assert_values(resp, {"name": name, "case_ids": [cid]})
        api_cleanup(f"/scenarios/{resp.json()['id']}")

    @pytest.mark.parametrize("case", create_no_token, ids=_ids(create_no_token))
    def test_create_without_token(self, case, project_only_client, seed_case, unique_name):
        """scenario 创建有鉴权：不带 token → 401(与 interface 一致,区别于其它无鉴权资源)。
        传合法 body(含真实 case_id),确保唯一失败原因是缺 token。"""
        skip_if_pending(case)
        resp = project_only_client.post("/scenarios", json={
            "name": unique_name(case["request"]["name_prefix"]),
            "case_ids": [seed_case()],
        })
        assert_response(resp, case["expected"])


@allure.feature("场景管理")
@allure.story("场景列表")
class TestListScenario:

    @pytest.mark.parametrize("case", list_success, ids=_ids(list_success))
    def test_list_success(self, case, project_client):
        skip_if_pending(case)
        resp = project_client.get("/scenarios")
        assert_response(resp, case["expected"])


@allure.feature("场景管理")
@allure.story("场景详情")
class TestGetScenarioDetail:

    @pytest.mark.parametrize("case", detail_success, ids=_ids(detail_success))
    def test_detail_success(self, case, project_client, seed_case, unique_name, api_cleanup):
        skip_if_pending(case)
        sid = _create(project_client, seed_case, unique_name, "auto_scn_get_", "detail")
        api_cleanup(f"/scenarios/{sid}")
        resp = project_client.get(f"/scenarios/{sid}")
        assert_response(resp, case["expected"])

    @pytest.mark.parametrize("case", detail_fail, ids=_ids(detail_fail))
    def test_detail_fail(self, case, project_client):
        skip_if_pending(case)
        resp = project_client.get(f"/scenarios/{case['request']['scenario_id']}")
        assert_response(resp, case["expected"])


@allure.feature("场景管理")
@allure.story("更新场景")
class TestUpdateScenario:

    @pytest.mark.parametrize("case", update_success, ids=_ids(update_success))
    def test_update_success(self, case, project_client, seed_case, unique_name, api_cleanup):
        skip_if_pending(case)
        sid = _create(project_client, seed_case, unique_name, "auto_scn_pre_", "before")
        api_cleanup(f"/scenarios/{sid}")
        req = case["request"]
        resp = project_client.put(f"/scenarios/{sid}", json={
            "name": unique_name(req["name_prefix"]),
            "description": req["description"],
            "case_ids": [],
        })
        assert_response(resp, case["expected"])


@allure.feature("场景管理")
@allure.story("删除场景")
class TestDeleteScenario:

    @pytest.mark.parametrize("case", delete_success, ids=_ids(delete_success))
    def test_delete_success(self, case, project_client, seed_case, unique_name):
        skip_if_pending(case)
        sid = _create(project_client, seed_case, unique_name, "auto_scn_del_", "delete")
        resp = project_client.delete(f"/scenarios/{sid}")
        assert_response(resp, case["expected"])
        again = project_client.get(f"/scenarios/{sid}")
        assert again.status_code == 404, f"删除后再查应 404: {again.text}"


@allure.feature("场景管理")
@allure.story("执行场景")
class TestRunScenario:

    @pytest.mark.parametrize("case", run_success, ids=_ids(run_success))
    def test_run_success(self, case, project_client, seed_runnable_case, runner_env, unique_name, api_cleanup):
        """执行场景按顺序跑各用例(带 env_id),返回等长结果列表且每条 passed。"""
        skip_if_pending(case)
        cid = seed_runnable_case()
        sid = project_client.post("/scenarios", json={
            "name": unique_name("auto_scn_run_"),
            "description": "run",
            "case_ids": [cid],
        }).json()["id"]
        api_cleanup(f"/scenarios/{sid}")
        resp = project_client.post(f"/scenarios/{sid}/run", params={"env_id": runner_env})
        assert_response(resp, case["expected"])
        results = resp.json()
        assert len(results) == 1, f"场景应跑出 1 条结果: {resp.text}"
        assert all(r["passed"] for r in results), f"场景内每条用例都应 passed: {resp.text}"
