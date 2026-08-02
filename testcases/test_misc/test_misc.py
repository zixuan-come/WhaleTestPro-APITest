import uuid

import pytest
import allure

from common.yaml_util import load_yaml
from common.assert_util import assert_response, skip_if_pending

_d = load_yaml("data/misc.yaml")
report_list = _d["report_list"]
report_detail_fail = _d["report_detail_fail"]
regression_run = _d["regression_run"]
demo_order_create = _d["demo_order_create"]
demo_order_list = _d["demo_order_list"]
traffic_record_list = _d["traffic_record_list"]
traffic_record_detail_fail = _d["traffic_record_detail_fail"]
traffic_replay = _d["traffic_replay"]
register_success = _d["register_success"]
register_fail = _d["register_fail"]


def _ids(cases):
    return [c["case_id"] for c in cases]


@allure.feature("测试报告")
@allure.story("报告列表 / 详情")
class TestReport:

    @pytest.mark.parametrize("case", report_list, ids=_ids(report_list))
    def test_list_success(self, case, project_client):
        skip_if_pending(case)
        resp = project_client.get("/reports")
        assert_response(resp, case["expected"])

    @pytest.mark.parametrize("case", report_detail_fail, ids=_ids(report_detail_fail))
    def test_detail_fail(self, case, project_client):
        skip_if_pending(case)
        resp = project_client.get(f"/reports/{case['request']['report_id']}")
        assert_response(resp, case["expected"])


@allure.feature("回归测试")
@allure.story("触发回归")
class TestRegression:

    @pytest.mark.parametrize("case", regression_run, ids=_ids(regression_run))
    def test_run_success(self, case, project_client, seed_case):
        """跑项目下全部用例的回归,返回汇总。先造一条用例保证有可跑内容。"""
        skip_if_pending(case)
        seed_case()
        resp = project_client.post("/regression", json=None)
        assert_response(resp, case["expected"])


@allure.feature("Demo 业务")
@allure.story("订单")
class TestDemoOrder:

    @pytest.mark.parametrize("case", demo_order_create, ids=_ids(demo_order_create))
    def test_create_success(self, case, project_client):
        skip_if_pending(case)
        resp = project_client.post("/demo/orders", json={"item": case["request"]["item"]})
        assert_response(resp, case["expected"])

    @pytest.mark.parametrize("case", demo_order_list, ids=_ids(demo_order_list))
    def test_list_success(self, case, project_client):
        skip_if_pending(case)
        resp = project_client.get("/demo/orders")
        assert_response(resp, case["expected"])


@allure.feature("流量录制")
@allure.story("记录与回放")
class TestTraffic:

    @pytest.mark.parametrize("case", traffic_record_list, ids=_ids(traffic_record_list))
    def test_list_success(self, case, project_client):
        skip_if_pending(case)
        resp = project_client.get("/traffic/records")
        assert_response(resp, case["expected"])

    @pytest.mark.parametrize("case", traffic_record_detail_fail, ids=_ids(traffic_record_detail_fail))
    def test_detail_fail(self, case, project_client):
        skip_if_pending(case)
        resp = project_client.get(f"/traffic/records/{case['request']['record_id']}")
        assert_response(resp, case["expected"])

    @pytest.mark.parametrize("case", traffic_replay, ids=_ids(traffic_replay))
    def test_replay(self, case, project_client):
        skip_if_pending(case)  # 需先有录制的流量记录,当前套件内不自造,标记 pending
        resp = project_client.post(f"/traffic/replay/{case['request']['record_id']}", json=None)
        assert_response(resp, case["expected"])


@allure.feature("用户认证")
@allure.story("注册")
class TestRegister:

    @pytest.mark.parametrize("case", register_success, ids=_ids(register_success))
    def test_register_success(self, case, client):
        skip_if_pending(case)
        req = case["request"]
        username = f"{req['username_prefix']}{uuid.uuid4().hex[:8]}"
        resp = client.post("/auth/register", json={"username": username, "password": req["password"]})
        assert_response(resp, case["expected"])

    @pytest.mark.parametrize("case", register_fail, ids=_ids(register_fail))
    def test_register_duplicate(self, case, client):
        """同名二次注册 → 400 用户已存在。先注册占名,再注册同名。"""
        skip_if_pending(case)
        req = case["request"]
        username = f"{req['username_prefix']}{uuid.uuid4().hex[:8]}"
        first = client.post("/auth/register", json={"username": username, "password": req["password"]})
        assert first.status_code == 200, f"前置注册应成功: {first.text}"
        resp = client.post("/auth/register", json={"username": username, "password": req["password"]})
        assert_response(resp, case["expected"])
