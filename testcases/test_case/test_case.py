import pytest
import allure

from common.yaml_util import load_yaml
from common.assert_util import assert_response, assert_values, skip_if_pending

_d = load_yaml("data/case.yaml")
create_success = _d["create_success"]
create_fail = _d["create_fail"]
create_no_token = _d["create_no_token"]
list_success = _d["list_success"]
detail_success = _d["detail_success"]
detail_fail = _d["detail_fail"]
update_success = _d["update_success"]
update_fail = _d["update_fail"]
delete_success = _d["delete_success"]
run_success = _d["run_success"]
chain_success = _d["chain_success"]


def _ids(cases):
    return [c["case_id"] for c in cases]


@allure.feature("用例管理")
@allure.story("创建用例")
class TestCreateCase:

    @pytest.mark.parametrize("case", create_success, ids=_ids(create_success))
    def test_create_success(self, case, project_client, seed_interface, unique_name, api_cleanup):
        skip_if_pending(case)
        req = case["request"]
        name = unique_name(req["name_prefix"])
        iid = seed_interface()
        resp = project_client.post("/cases", json={
            "name": name,
            "interface_id": iid,
            "expected_status": req["expected_status"],
        })
        assert_response(resp, case["expected"])
        assert_values(resp, {"name": name, "interface_id": iid, "expected_status": req["expected_status"]})
        api_cleanup(f"/cases/{resp.json()['id']}")

    @pytest.mark.parametrize("case", create_fail, ids=_ids(create_fail))
    def test_create_wrong_type(self, case, project_client, seed_interface):
        """interface_id 传字符串 → 422 类型校验失败。"""
        skip_if_pending(case)
        req = case["request"]
        resp = project_client.post("/cases", json={
            "name": req["name_prefix"],
            "interface_id": req["interface_id"],
            "expected_status": req["expected_status"],
        })
        assert_response(resp, case["expected"])

    @pytest.mark.parametrize("case", create_no_token, ids=_ids(create_no_token))
    def test_create_without_token(self, case, project_only_client, project_client,
                                  seed_interface, unique_name, api_cleanup):
        """不带 token 创建 case → 401 Not authenticated。"""
        skip_if_pending(case)
        resp = project_only_client.post("/cases", json={
            "name": unique_name(case["request"]["name_prefix"]),
            "interface_id": seed_interface(),
            "expected_status": case["request"]["expected_status"],
        })
        assert_response(resp, case["expected"])
        if resp.status_code < 300:
            api_cleanup(f"/cases/{resp.json()['id']}")


@allure.feature("用例管理")
@allure.story("用例列表")
class TestListCase:

    @pytest.mark.parametrize("case", list_success, ids=_ids(list_success))
    def test_list_success(self, case, project_client):
        skip_if_pending(case)
        resp = project_client.get("/cases")
        assert_response(resp, case["expected"])


@allure.feature("用例管理")
@allure.story("用例详情")
class TestGetCaseDetail:

    @pytest.mark.parametrize("case", detail_success, ids=_ids(detail_success))
    def test_detail_success(self, case, project_client, seed_case):
        skip_if_pending(case)
        resp = project_client.get(f"/cases/{seed_case()}")
        assert_response(resp, case["expected"])

    @pytest.mark.parametrize("case", detail_fail, ids=_ids(detail_fail))
    def test_detail_fail(self, case, project_client):
        skip_if_pending(case)
        resp = project_client.get(f"/cases/{case['request']['case_id']}")
        assert_response(resp, case["expected"])


@allure.feature("用例管理")
@allure.story("修改用例")
class TestUpdateCase:

    @pytest.mark.parametrize("case", update_success, ids=_ids(update_success))
    def test_update_success(
        self,
        case,
        project_client,
        seed_case,
        seed_interface,
        unique_name,
    ):
        case_id = seed_case()
        interface_id = seed_interface()
        request = case["request"]
        body = {
            "name": unique_name(request["name_prefix"]),
            "interface_id": interface_id,
            "expected_status": request["expected_status"],
            "retries": request["retries"],
            "tags": request["tags"],
            "extract_rules": request["extract_rules"],
            "assertions": request["assertions"],
        }

        response = project_client.put(f"/cases/{case_id}", json=body)
        assert_response(response, case["expected"])
        assert_values(response, body)

        detail = project_client.get(f"/cases/{case_id}")
        assert detail.status_code == 200
        assert_values(detail, body)

    def test_update_not_exist(self, project_client, seed_interface, unique_name):
        case = next(item for item in update_fail if item["case_id"] == "update_case_not_exist")
        request = case["request"]
        response = project_client.put(
            f"/cases/{request['case_id']}",
            json={
                "name": unique_name("auto_case_missing_"),
                "interface_id": seed_interface(),
                "expected_status": request["expected_status"],
            },
        )
        assert_response(response, case["expected"])

    def test_update_interface_not_exist(self, project_client, seed_case, unique_name):
        case = next(
            item for item in update_fail
            if item["case_id"] == "update_case_interface_not_exist"
        )
        request = case["request"]
        response = project_client.put(
            f"/cases/{seed_case()}",
            json={
                "name": unique_name("auto_case_bad_interface_"),
                "interface_id": request["interface_id"],
                "expected_status": request["expected_status"],
            },
        )
        assert_response(response, case["expected"])

    def test_update_wrong_type(self, project_client, seed_case, unique_name):
        case = next(item for item in update_fail if item["case_id"] == "update_case_wrong_type")
        request = case["request"]
        response = project_client.put(
            f"/cases/{seed_case()}",
            json={
                "name": unique_name("auto_case_bad_type_update_"),
                "interface_id": request["interface_id"],
                "expected_status": request["expected_status"],
            },
        )
        assert_response(response, case["expected"])

    def test_update_without_token(
        self,
        project_only_client,
        seed_case,
        seed_interface,
        unique_name,
    ):
        case = next(item for item in update_fail if item["case_id"] == "update_case_without_token")
        response = project_only_client.put(
            f"/cases/{seed_case()}",
            json={
                "name": unique_name("auto_case_no_token_update_"),
                "interface_id": seed_interface(),
                "expected_status": case["request"]["expected_status"],
            },
        )
        assert_response(response, case["expected"])


@allure.feature("用例管理")
@allure.story("删除用例")
class TestDeleteCase:

    @pytest.mark.parametrize("case", delete_success, ids=_ids(delete_success))
    def test_delete_success(self, case, project_client, seed_case):
        skip_if_pending(case)
        cid = seed_case()
        resp = project_client.delete(f"/cases/{cid}")
        assert_response(resp, case["expected"])
        again = project_client.get(f"/cases/{cid}")
        assert again.status_code == 404, f"删除后再查应 404: {again.text}"


@allure.feature("用例管理")
@allure.story("执行用例")
class TestRunCase:

    @pytest.mark.smoke
    @pytest.mark.parametrize("case", run_success, ids=_ids(run_success))
    def test_run_success(self, case, project_client, seed_runnable_case, runner_env):
        """执行用例(带 env_id,url 用路径拼 base_url)→ 同步返回,且真正 passed。
        断言到值:passed=True 且 actual_status==expected_status,证明真跑通而非只回结构。"""
        skip_if_pending(case)
        resp = project_client.post(f"/cases/{seed_runnable_case()}/run", params={"env_id": runner_env})
        assert_response(resp, case["expected"])
        assert_values(resp, {"passed": True, "expected_status": 200, "actual_status": 200})

    @pytest.mark.parametrize("case", chain_success, ids=_ids(chain_success))
    def test_run_chain_success(self, case, project_client, seed_runnable_case, runner_env):
        """串联执行:传一组 case_id,返回等长结果列表,且每条都 passed。"""
        skip_if_pending(case)
        cids = [seed_runnable_case(), seed_runnable_case()]
        resp = project_client.post("/cases/chain", params={"env_id": runner_env}, json=cids)
        assert_response(resp, case["expected"])
        results = resp.json()
        assert len(results) == len(cids), f"结果数应与传入 case 数一致: {resp.text}"
        assert all(r["passed"] for r in results), f"串联每条都应 passed: {resp.text}"
