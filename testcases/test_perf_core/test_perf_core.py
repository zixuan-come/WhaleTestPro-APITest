"""Public HTTP contracts; no imports from the backend in black-box tests."""
from copy import deepcopy
import time

import allure
import pytest

from common.core_flow import business
from common.perf_cases import config_cases, request_for, single_plan, chain_plan
from common.perf_flow import task_payload as _payload

pytestmark = [pytest.mark.perf_core, allure.feature("HTTP 与链路压测核心回归")]
CONFIG_CASES = config_cases()


def _subset(actual, expected):
    if isinstance(expected, dict):
        assert isinstance(actual, dict)
        for key, value in expected.items():
            assert key in actual, f"配置缺少字段 {key}"
            _subset(actual[key], value)
    elif isinstance(expected, list):
        assert isinstance(actual, list) and len(actual) == len(expected)
        for item, value in zip(actual, expected):
            _subset(item, value)
    else:
        assert type(actual) is type(expected) and actual == expected


@pytest.mark.parametrize("case", CONFIG_CASES, ids=[row["case_id"] for row in CONFIG_CASES])
@allure.title("{case[title]}")
def test_load_config_create_and_read_contract(case, perf_api):
    client = perf_api.client
    before = {row["id"] for row in business(client.get("/perf/tasks"))}
    payload = _payload(perf_api.name, case["request"])
    sent = deepcopy(payload)
    response = client.post("/perf/tasks", json=payload)
    if response.status_code == 201:
        perf_api.tasks.append(response.json()["id"])
    result = business(response, case["status"])
    assert payload == sent, "请求配置不应被测试辅助代码修改"
    if case["status"] == 422:
        assert result["errors"] and all(row["field"] and row["message"] for row in result["errors"])
        assert {row["id"] for row in business(client.get("/perf/tasks"))} == before
        return
    assert result["status"] == "pending" and result["iteration_stats"] is None
    _subset(result["load_config"], payload["load_config"])
    detail = business(client.get(f"/perf/tasks/{result['id']}"))
    listed = next(row for row in business(client.get("/perf/tasks")) if row["id"] == result["id"])
    assert detail["load_config"] == listed["load_config"] == result["load_config"]


def run_plan(perf_api, plan, target):
    req = {**request_for(plan), "target_host": target}
    task = business(perf_api.client.post("/perf/tasks", json=_payload(perf_api.name, req)), 201)
    perf_api.tasks.append(task["id"])
    queued = business(perf_api.client.post(f"/perf/tasks/{task['id']}/run"))
    assert queued["status"] == "queued" and queued["celery_task_id"]
    deadline = time.monotonic() + 90
    while True:
        result = business(perf_api.client.get(f"/perf/tasks/{task['id']}"))
        if result["status"] in {"done", "failed", "cancelled"}:
            break
        assert time.monotonic() < deadline, "Worker/Locust 未在期限内结束"
        time.sleep(0.5)
    assert result["status"] == "done", "压测未正常完成，不能将仅入队当作成功"
    assert result["celery_task_id"] == queued["celery_task_id"]
    assert result["started_at"] and result["finished_at"] and result["history_samples"]
    summary = result["iteration_stats"]
    assert isinstance(summary, dict) and summary["lease"]
    assert type(summary["iterations"]) is int and summary["iterations"] > 0
    assert type(summary["failures"]) is int and 0 <= summary["failures"] <= summary["iterations"]
    assert summary["configuration_failures"] == 0
    assert summary["elapsed_seconds"] > 0 and summary["avg_duration_ms"] >= 0
    assert summary["iteration_rps"] == pytest.approx(summary["iterations"] / summary["elapsed_seconds"])
    assert summary["fail_ratio"] == pytest.approx(summary["failures"] / summary["iterations"])
    rows = {row["name"]: row for row in result["request_stats"] or [] if row["name"] != "Aggregated"}
    assert rows and all(row["name"].startswith("step_") for row in rows.values())
    return result, rows


@pytest.mark.async_e2e
@pytest.mark.parametrize("body_type", ["json", "form", "raw"])
def test_single_post_sends_configured_body(perf_api, perf_load_target, body_type):
    plan = single_plan(body_type)
    step = plan["steps"][0]
    step["assertions"] = [{"type": "json_eq", "path": "$." + key, "expected": value}
                          for key, value in {"fixture": "whale-perf-core", "method": "POST",
                                             "header": "perf-core", "query": "apitest",
                                             "body": step["body"]}.items()]
    result, rows = run_plan(perf_api, plan, perf_load_target)
    assert set(rows) == {"step_01"} and rows["step_01"]["method"] == "POST"
    assert rows["step_01"]["num_requests"] > 0 and rows["step_01"]["num_failures"] == 0
    assert result["iteration_stats"]["failures"] == 0


@pytest.mark.async_e2e
def test_chain_passes_token_order_id_and_typed_variables(perf_api, perf_load_target):
    result, rows = run_plan(perf_api, chain_plan(), perf_load_target)
    assert set(rows) == {"step_01", "step_02", "step_03"}
    assert [rows[name]["method"] for name in sorted(rows)] == ["POST", "POST", "GET"]
    assert all(row["num_requests"] > 0 and row["num_failures"] == 0 for row in rows.values())
    assert result["iteration_stats"]["failures"] == 0


@pytest.mark.async_e2e
@pytest.mark.parametrize("failure", ["business_assertion", "missing_extraction"])
def test_failed_first_step_stops_dependent_requests(perf_api, perf_load_target, failure):
    plan = chain_plan()
    if failure == "business_assertion":
        plan["steps"][0]["assertions"] = [{"type": "json_eq", "path": "$.fixture", "expected": "deliberate-mismatch"}]
    else:
        plan["steps"][0]["extract_rules"] = {"token": "$.missing_token"}
    # Omit stop_on_failure to verify the documented default, not just explicit true.
    result, rows = run_plan(perf_api, plan, perf_load_target)
    assert set(rows) == {"step_01"}, "失败后仍发送了后续依赖请求"
    assert rows["step_01"]["num_requests"] > 0
    assert rows["step_01"]["num_failures"] == rows["step_01"]["num_requests"]
    summary = result["iteration_stats"]
    assert summary["failures"] == summary["iterations"] and summary["fail_ratio"] == 1


@pytest.mark.async_e2e
def test_deleting_queued_or_running_task_is_conflict(perf_api, perf_load_target):
    req = {**request_for(single_plan()), "target_host": perf_load_target, "duration": 20}
    task = business(perf_api.client.post("/perf/tasks", json=_payload(perf_api.name, req)), 201)
    perf_api.tasks.append(task["id"])
    queued = business(perf_api.client.post(f"/perf/tasks/{task['id']}/run"))
    assert queued["status"] == "queued"
    business(perf_api.client.delete(f"/perf/tasks/{task['id']}"), 409)
    current = business(perf_api.client.get(f"/perf/tasks/{task['id']}"))
    assert current["status"] in {"queued", "running"}
    assert current["celery_task_id"] == queued["celery_task_id"]
    # The fixture stops and verifies deletion even when the assertion fails.
