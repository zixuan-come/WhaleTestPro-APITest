"""Deterministic regressions for payload and cleanup, no live platform."""
from types import SimpleNamespace

import pytest


class Reply:
    def __init__(self, status, data=None):
        self.status_code, self.data = status, data
        self.text = "isolated response"
    def json(self):
        return self.data


def test_schedule_not_found_payload_contains_current_environment():
    from testcases.test_contract.test_negative_contract import TestNegativeContract, resources
    schedule = next(row for row in resources if row["name"] == "schedule")
    calls = []
    def put(url, json):
        calls.append(json)
        return Reply(404 if json.get("env_id") == 123 else 422)
    TestNegativeContract().test_update_not_found(schedule, SimpleNamespace(put=put), 123)
    assert calls[0]["env_id"] == 123
    assert "env_id" not in schedule["update_body"], "不要原地污染参数化用例数据"


def test_perf_failure_stops_task_using_real_backend_route(monkeypatch):
    from testcases.test_perf.test_perf import TestRunPerfTask, run_success
    stops = []
    state = {"deleted": False}
    def post(path, **kwargs):
        if path == "/perf/tasks":
            return Reply(201, {"id": 7})
        if path.endswith("/run"):
            raise AssertionError("synthetic execution failure")
        if path == "/perf/tasks/7/stop":
            stops.append(path)
            return Reply(200, {"id": 7, "status": "cancelled"})
        return Reply(404)
    def delete(*_):
        state["deleted"] = True
        return Reply(200)
    client = SimpleNamespace(post=post, delete=delete, get=lambda *_: Reply(404) if state["deleted"] else Reply(200, {"id": 7, "status": "cancelled"}))
    with pytest.raises(AssertionError, match="synthetic execution failure"):
        TestRunPerfTask().test_run_success(run_success[0], client, lambda prefix: prefix + "unique", lambda _: None)
    assert stops == ["/perf/tasks/7/stop"]
    assert state["deleted"] is True


def test_perf_not_enqueued_pending_task_is_also_deleted(monkeypatch):
    from testcases.test_perf import test_perf
    state = {"deleted": False}
    monkeypatch.setattr(test_perf.time, "sleep", lambda _: None)
    ticks = iter([0, 31])
    monkeypatch.setattr(test_perf.time, "monotonic", lambda: next(ticks))
    client = SimpleNamespace(
        post=lambda *_: Reply(200, {"id": 7, "status": "pending"}),
        get=lambda *_: Reply(404) if state["deleted"] else Reply(200, {"id": 7, "status": "pending"}),
        delete=lambda *_: state.update(deleted=True) or Reply(200),
    )
    test_perf._stop_and_delete(client, 7)
    assert state["deleted"] is True


@pytest.mark.parametrize("status", [409, 503])
def test_perf_cleanup_retries_conflict_or_control_outage_then_verifies_delete(monkeypatch, status):
    from testcases.test_perf import test_perf
    monkeypatch.setattr(test_perf.time, "sleep", lambda _: None)
    monkeypatch.setattr(test_perf.time, "monotonic", lambda: 0)
    state = {"attempts": 0, "deleted": False}
    def delete(*_):
        state["attempts"] += 1
        if state["attempts"] == 1:
            return Reply(status)
        state["deleted"] = True
        return Reply(200)
    client = SimpleNamespace(post=lambda *_: Reply(200), delete=delete,
                             get=lambda *_: Reply(404) if state["deleted"]
                             else Reply(200, {"status": "cancelled"}))
    test_perf._stop_and_delete(client, 7)
    assert state == {"attempts": 2, "deleted": True}


def test_perf_cleanup_does_not_turn_persistent_control_failure_into_success(monkeypatch):
    from testcases.test_perf import test_perf
    monkeypatch.setattr(test_perf.time, "sleep", lambda _: None)
    ticks = iter([0, 31])
    monkeypatch.setattr(test_perf.time, "monotonic", lambda: next(ticks))
    client = SimpleNamespace(post=lambda *_: Reply(200), delete=lambda *_: Reply(503),
                             get=lambda *_: Reply(200, {"status": "cancelled"}))
    with pytest.raises(AssertionError, match="压测清理未完成"):
        test_perf._stop_and_delete(client, 7)


def test_perf_cleanup_rejects_successful_delete_when_task_still_exists():
    from testcases.test_perf import test_perf
    paths = []

    def get(path):
        paths.append(("GET", path))
        return Reply(200, {"status": "cancelled"})

    def delete(path):
        paths.append(("DELETE", path))
        return Reply(200)

    client = SimpleNamespace(post=lambda *_: Reply(200), get=get, delete=delete)
    with pytest.raises(AssertionError):
        test_perf._stop_and_delete(client, 7)
    assert paths == [("GET", "/perf/tasks/7"), ("DELETE", "/perf/tasks/7"),
                     ("GET", "/perf/tasks/7")]


def test_perf_cleanup_retries_legacy_404_and_verifies_later_deletion(monkeypatch):
    from testcases.test_perf import test_perf
    monkeypatch.setattr(test_perf.time, "sleep", lambda _: None)
    ticks = iter([0, 1, 31])
    monkeypatch.setattr(test_perf.time, "monotonic", lambda: next(ticks))
    state = {"attempts": 0, "deleted": False, "gets": 0}

    def get(_path):
        state["gets"] += 1
        return Reply(404) if state["deleted"] else Reply(200, {"status": "cancelled"})

    def delete(_path):
        state["attempts"] += 1
        if state["attempts"] == 1:
            return Reply(404)
        state["deleted"] = True
        return Reply(200)

    client = SimpleNamespace(post=lambda *_: Reply(200), get=get, delete=delete)
    test_perf._stop_and_delete(client, 7)
    assert state == {"attempts": 2, "deleted": True, "gets": 3}
