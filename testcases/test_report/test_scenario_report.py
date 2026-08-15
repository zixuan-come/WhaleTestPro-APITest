import allure
import pytest

from common.assert_util import assert_response, skip_if_pending
from common.yaml_util import load_yaml


_data = load_yaml("data/scenario_report.yaml")
list_success = _data["list_success"]
detail_success = _data["detail_success"]
detail_fail = _data["detail_fail"]


def _ids(cases):
    return [case["case_id"] for case in cases]


@pytest.fixture
def executed_scenario(project_client, seed_runnable_case, runner_env, unique_name, api_cleanup):
    """通过公开 HTTP 接口执行两步场景，并返回本次执行对应的报告。"""
    case_ids = [seed_runnable_case(), seed_runnable_case()]
    scenario_name = unique_name("auto_scenario_report_")
    created = project_client.post("/scenarios", json={
        "name": scenario_name,
        "description": "scenario report verification",
        "case_ids": case_ids,
    })
    assert created.status_code == 201, f"前置创建场景失败: {created.text}"
    scenario_id = created.json()["id"]
    api_cleanup(f"/scenarios/{scenario_id}")

    executed = project_client.post(
        f"/scenarios/{scenario_id}/run",
        params={"env_id": runner_env},
    )
    assert executed.status_code == 200, f"前置执行场景失败: {executed.text}"
    assert len(executed.json()) == 2, f"两步场景应返回两条执行结果: {executed.text}"

    reports = project_client.get("/reports/scenarios", params={"page": 1, "page_size": 100})
    assert reports.status_code == 200, f"前置查询场景报告失败: {reports.text}"
    matched = [item for item in reports.json()["items"] if item["scenario_id"] == scenario_id]
    assert len(matched) == 1, f"一次场景执行应只生成一份父报告: {reports.text}"

    return {
        "report": matched[0],
        "scenario_id": scenario_id,
        "scenario_name": scenario_name,
        "case_ids": case_ids,
    }


@allure.feature("场景报告")
@allure.story("场景报告列表")
class TestListScenarioReport:

    @pytest.mark.parametrize("case", list_success, ids=_ids(list_success))
    def test_list_success(self, case, project_client, executed_scenario):
        skip_if_pending(case)
        response = project_client.get("/reports/scenarios")
        assert_response(response, case["expected"])
        report = executed_scenario["report"]
        assert report["scenario_name"] == executed_scenario["scenario_name"]
        assert report["passed"] is True
        assert report["total_steps"] == 2
        assert report["passed_steps"] == 2
        assert report["failed_steps"] == 0


@allure.feature("场景报告")
@allure.story("场景报告详情")
class TestGetScenarioReport:

    @pytest.mark.parametrize("case", detail_success, ids=_ids(detail_success))
    def test_detail_success(self, case, project_client, executed_scenario):
        skip_if_pending(case)
        report_id = executed_scenario["report"]["id"]
        response = project_client.get(f"/reports/scenarios/{report_id}")
        assert_response(response, case["expected"])

        body = response.json()
        assert body["scenario_id"] == executed_scenario["scenario_id"]
        assert body["scenario_name"] == executed_scenario["scenario_name"]
        assert len(body["steps"]) == 2
        assert [step["sequence"] for step in body["steps"]] == [1, 2]
        assert [step["case_id"] for step in body["steps"]] == executed_scenario["case_ids"]

        for step in body["steps"]:
            assert step["passed"] is True
            assert step["case_name"]
            assert step["request_detail"]["method"] == "GET"
            assert step["request_detail"]["url"].endswith("/health")
            assert step["response_detail"]["status_code"] == 200
            assert step["assertions"][0] == {
                "type": "status_code",
                "passed": True,
                "expected": 200,
                "actual": 200,
            }
            assert step["duration_ms"] >= 0

    @pytest.mark.parametrize("case", detail_fail, ids=_ids(detail_fail))
    def test_detail_fail(self, case, project_client):
        skip_if_pending(case)
        report_id = case["request"]["report_id"]
        response = project_client.get(f"/reports/scenarios/{report_id}")
        assert_response(response, case["expected"])
