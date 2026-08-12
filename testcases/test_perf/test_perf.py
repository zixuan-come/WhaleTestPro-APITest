import pytest
import allure

from common.yaml_util import load_yaml
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


def _payload(unique_name, req):
    return {
        "name": unique_name(req["name_prefix"]),
        "target_host": req["target_host"],
        "target_path": req["target_path"],
        "users": req["users"],
        "spawn_rate": req["spawn_rate"],
        "duration": req["duration"],
    }


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

    @pytest.mark.parametrize("case", run_success, ids=_ids(run_success))
    def test_run_success(self, case, project_client, unique_name, api_cleanup):
        """触发压测(异步,locust 后台跑)。只校验接受触发并回任务(status),不等跑完。"""
        skip_if_pending(case)
        tid = _create(project_client, unique_name, create_success[0]["request"])
        api_cleanup(f"/perf/tasks/{tid}")
        resp = project_client.post(f"/perf/tasks/{tid}/run")
        assert_response(resp, case["expected"])
