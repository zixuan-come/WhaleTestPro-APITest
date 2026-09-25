import pytest
import allure
import time
from config import PERF_BASE_URL

from common.yaml_util import load_yaml
# Compatibility exports for existing lifecycle contract tests.
from common.perf_flow import task_payload as _payload, stop_and_delete as _stop_and_delete
from common.assert_util import assert_response, skip_if_pending

_d = load_yaml("data/perf.yaml")
create_success = _d["create_success"]
list_success = _d["list_success"]
detail_success = _d["detail_success"]
detail_fail = _d["detail_fail"]
delete_success = _d["delete_success"]
run_success = _d["run_success"]
create_fail = _d["create_fail"]
create_no_token = _d["create_no_token"]


def _ids(cases):
    return [c["case_id"] for c in cases]


def _create(project_client, unique_name, req):
    resp = project_client.post("/perf/tasks", json=_payload(unique_name, req))
    assert resp.status_code == 201, f"前置建压测任务应成功: {resp.text}"
    return resp.json()["id"]


@allure.feature("性能压测")
@allure.story("创建压测任务")
class TestCreatePerfTask:

    @pytest.mark.parametrize("case", create_success, ids=_ids(create_success))
    def test_create_success(self, case, project_client, unique_name, api_cleanup):
        skip_if_pending(case)
        resp = project_client.post("/perf/tasks", json=_payload(unique_name, case["request"]))
        assert_response(resp, case["expected"])
        api_cleanup(f"/perf/tasks/{resp.json()['id']}")

    @pytest.mark.parametrize("case", create_fail, ids=_ids(create_fail))
    def test_create_wrong_type(self, case, project_client, unique_name):
        """users 传字符串 → 422 类型校验失败。"""
        skip_if_pending(case)
        resp = project_client.post("/perf/tasks", json=_payload(unique_name, case["request"]))
        assert_response(resp, case["expected"])

    @pytest.mark.parametrize("case", create_no_token, ids=_ids(create_no_token))
    def test_create_without_token(self, case, project_only_client, unique_name, api_cleanup):
        """不带 token 创建 perf task → 401 Not authenticated。"""
        skip_if_pending(case)
        resp = project_only_client.post("/perf/tasks", json=_payload(unique_name, case["request"]))
        assert_response(resp, case["expected"])
        if resp.status_code < 300:
            api_cleanup(f"/perf/tasks/{resp.json()['id']}")


@allure.feature("性能压测")
@allure.story("压测任务列表")
class TestListPerfTask:

    @pytest.mark.parametrize("case", list_success, ids=_ids(list_success))
    def test_list_success(self, case, project_client):
        skip_if_pending(case)
        resp = project_client.get("/perf/tasks")
        assert_response(resp, case["expected"])


@allure.feature("性能压测")
@allure.story("压测任务详情")
class TestGetPerfTaskDetail:

    @pytest.mark.parametrize("case", detail_success, ids=_ids(detail_success))
    def test_detail_success(self, case, project_client, unique_name, api_cleanup):
        skip_if_pending(case)
        tid = _create(project_client, unique_name, create_success[0]["request"])
        api_cleanup(f"/perf/tasks/{tid}")
        resp = project_client.get(f"/perf/tasks/{tid}")
        assert_response(resp, case["expected"])

    @pytest.mark.parametrize("case", detail_fail, ids=_ids(detail_fail))
    def test_detail_fail(self, case, project_client):
        skip_if_pending(case)
        resp = project_client.get(f"/perf/tasks/{case['request']['task_id']}")
        assert_response(resp, case["expected"])


@allure.feature("性能压测")
@allure.story("删除压测任务")
class TestDeletePerfTask:

    @pytest.mark.parametrize("case", delete_success, ids=_ids(delete_success))
    def test_delete_success(self, case, project_client, unique_name):
        skip_if_pending(case)
        tid = _create(project_client, unique_name, create_success[0]["request"])
        resp = project_client.delete(f"/perf/tasks/{tid}")
        assert_response(resp, case["expected"])
        again = project_client.get(f"/perf/tasks/{tid}")
        assert again.status_code == 404, f"删除后再查应 404: {again.text}"


@allure.feature("性能压测")
@allure.story("执行压测任务")
class TestRunPerfTask:

    @pytest.mark.async_e2e
    @pytest.mark.parametrize("case", run_success, ids=_ids(run_success))
    def test_run_success(self, case, project_client, unique_name, api_cleanup):
        """实际等待 Worker/Locust 执行完成并检查请求统计，不能只验证入队。"""
        skip_if_pending(case)
        req = {**create_success[0]["request"], "target_host": PERF_BASE_URL, "duration": 6}
        tid = _create(project_client, unique_name, req)
        api_cleanup(f"/perf/tasks/{tid}")
        try:
            resp = project_client.post(f"/perf/tasks/{tid}/run")
            assert_response(resp, case["expected"])
            queued = resp.json()
            assert queued["status"] == "queued"
            assert queued["celery_task_id"], "缺少 Celery 与业务任务的关联 ID"
            deadline = time.monotonic() + 90
            result = queued
            while time.monotonic() < deadline:
                response = project_client.get(f"/perf/tasks/{tid}")
                assert_response(response, {"status_code": 200})
                result = response.json()
                if result["status"] in {"done", "failed", "cancelled"}:
                    break
                time.sleep(1)
            assert result["status"] == "done", f"压测未正常结束: {result}"
            assert result["celery_task_id"] == queued["celery_task_id"]
            assert result["started_at"] and result["finished_at"]
            rows = result.get("request_stats") or []
            assert sum(row.get("num_requests", 0) for row in rows) > 0, "未产生真实请求统计"
            assert sum(row.get("num_failures", 0) for row in rows) == 0, f"目标健康接口请求失败: {rows}"
            assert result.get("history_samples"), "缺少压测过程采样"
        finally:
            # A missing Worker must fail the test, but not leave a queued task
            # holding the singleton Locust lease for the rest of the suite.
            _stop_and_delete(project_client, tid)
