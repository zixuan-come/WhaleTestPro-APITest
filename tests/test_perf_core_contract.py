"""Actual HTTP routes + SQLite; synthetic identity, broker, Redis and target.

The runtime adapter executes the real iteration engine against the pure fixture
handler, NOT a deployed Celery/Locust/network stack. CI supplies that final layer.
"""
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timedelta
import os
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit, urlencode
import json

import pytest

from common.core_flow import business
from common.perf_cases import single_plan
from common.request_util import RequestUtil
from scripts.perf_fixture_server import response_for
from common.perf_flow import task_payload as _payload
from testcases.test_perf_core import test_perf_core as core


class MemoryCache:
    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, nx=False, **_kwargs):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    def expire(self, *_args):
        return True

    def delete(self, *keys):
        for key in keys:
            self.values.pop(key, None)

    def eval(self, _script, count, *args):
        keys, values = args[:count], args[count:]
        if self.get(keys[0]) != values[0]:
            return 0
        if count == 1:
            self.values.pop(keys[0], None)
        else:
            if self.get(keys[1]) == values[1]:
                self.values.pop(keys[1], None)
            self.values.pop(keys[2], None)
            self.values.pop(keys[0], None)
        return 1


@pytest.fixture
def isolated_perf_api(monkeypatch):
    backend = Path(os.getenv("WHALE_BACKEND_PATH", Path(__file__).resolve().parents[2] / "WhaleTestPro")).resolve()
    assert (backend / "app").is_dir(), "需要 WhaleTestPro 源码或 WHALE_BACKEND_PATH"
    monkeypatch.syspath_prepend(str(backend))
    for key, value in {"DATABASE_URL": "sqlite:///:memory:", "SHADOW_DATABASE_URL": "sqlite:///:memory:",
                       "SECRET_KEY": "isolated-perf-contract-only", "LOCUST_SKIP_MONKEY_PATCH": "1"}.items():
        monkeypatch.setenv(key, value)
    from fastapi import FastAPI, HTTPException
    from fastapi.exceptions import RequestValidationError
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool
    from app.database import Base, get_db
    from app.core.authentication import get_current_user
    from app.core.exception_handlers import http_exception_handler, validation_exception_handler
    from app.models.user import User
    import app.models.suite  # Register foreign-key destinations, also for standalone runs.
    from app.routers import team, project, perf
    from app.services import perf as service
    import httpx

    cache = MemoryCache()
    monkeypatch.setattr(service.redis, "from_url", lambda *_a, **_k: cache)
    monkeypatch.setattr(service.settings, "LOCUST_CONTROL_TOKEN", "synthetic-perf-control-only")
    publications = []
    monkeypatch.setattr(perf.run_perf_task, "apply_async", lambda **kwargs: publications.append(kwargs))
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    database = Session(engine)
    Base.metadata.create_all(engine)
    database.execute(text("PRAGMA foreign_keys=ON"))
    user = User(username="isolated-perf-owner", hashed_password="unused")
    database.add(user)
    database.commit()
    application = FastAPI()
    for module in (team, project, perf):
        application.include_router(module.router)
    application.add_exception_handler(HTTPException, http_exception_handler)
    application.add_exception_handler(RequestValidationError, validation_exception_handler)
    application.dependency_overrides[get_db] = lambda: database
    application.dependency_overrides[get_current_user] = lambda: user
    try:
        with TestClient(application) as local:
            def transport(method, url, **kwargs):
                assert urlsplit(url).netloc == "isolated.invalid"
                kwargs.pop("timeout", None)
                return local.request(method, urlsplit(url).path, **kwargs)
            monkeypatch.setattr(httpx, "request", transport)
            owner = RequestUtil("http://isolated.invalid")
            team_id = business(owner.post("/teams", json={"name": "isolated-perf-team"}), 201)["id"]
            project_id = business(owner.post("/projects", json={"name": "isolated-perf-project", "team_id": team_id}), 201)["id"]
            names = iter(range(1000))
            api = SimpleNamespace(client=RequestUtil("http://isolated.invalid", headers={"X-Project-Id": str(project_id)}),
                                  tasks=[], name=lambda prefix: prefix + str(next(names)),
                                  database=database, cache=cache, project_id=project_id, publications=publications)
            yield api
    finally:
        database.close()
        engine.dispose()


@pytest.mark.parametrize("case", core.CONFIG_CASES, ids=[row["case_id"] for row in core.CONFIG_CASES])
def test_configuration_script_against_actual_routes(isolated_perf_api, case):
    core.test_load_config_create_and_read_contract(case, isolated_perf_api)


def test_legacy_payload_omits_plan_and_preserves_null_fields(isolated_perf_api):
    req = {"name_prefix": "legacy_", "target_host": "http://fixture.invalid", "target_path": "/health",
           "users": 1, "spawn_rate": 1, "duration": 2}
    original = deepcopy(req)
    payload = _payload(isolated_perf_api.name, req)
    assert "load_config" not in payload and req == original
    task = business(isolated_perf_api.client.post("/perf/tasks", json=payload), 201)
    assert task["load_config"] is task["iteration_stats"] is None
    assert business(isolated_perf_api.client.get(f"/perf/tasks/{task['id']}"))["target_path"] == "/health"
    payload = _payload(lambda value: value, {**req, "load_config": None})
    assert "load_config" in payload and payload["load_config"] is None


def test_payload_deep_copies_plan_instead_of_mutating_case_data():
    req = {"name_prefix": "core_", "target_host": "http://fixture.invalid", "target_path": "/health",
           "users": 1, "spawn_rate": 1, "duration": 2, "load_config": single_plan()}
    original = deepcopy(req)
    payload = _payload(lambda value: value, req)
    payload["load_config"]["steps"][0]["headers"]["X-Fixture"] = "changed"
    assert req == original


def _task(api, status="pending"):
    from app.models.perf import PerfTask
    row = business(api.client.post("/perf/tasks", json={"name": api.name("delete_"),
                   "target_host": "http://fixture.invalid", "target_path": "/health",
                   "users": 1, "spawn_rate": 1, "duration": 6}), 201)
    task = api.database.get(PerfTask, row["id"])
    task.status = status
    task.queued_at = task.started_at = task.heartbeat_at = datetime.utcnow()
    api.database.commit()
    return task


@pytest.mark.parametrize("status", ["queued", "running"])
def test_delete_active_returns_409_and_preserves_task_and_lease(isolated_perf_api, status):
    from app.services import perf
    api = isolated_perf_api
    task = _task(api, status)
    api.cache.values[perf.RUN_LOCK_KEY] = f"{api.project_id}:{task.id}:synthetic-message"
    before = dict(api.cache.values)
    business(api.client.delete(f"/perf/tasks/{task.id}"), 409)
    assert business(api.client.get(f"/perf/tasks/{task.id}"))["status"] == status
    assert api.cache.values == before


@pytest.mark.parametrize("status", ["done", "failed", "cancelled"])
def test_control_outage_returns_503_preserves_owned_state_then_recovers(isolated_perf_api, monkeypatch, status):
    from app.services import perf
    import requests
    api = isolated_perf_api
    task = _task(api, status)
    task_id = task.id
    run_id = f"{api.project_id}:{task_id}"
    api.cache.values.update({perf.RUN_LOCK_KEY: run_id + ":synthetic-message", perf.ACTIVE_RUN_KEY: run_id})
    before = dict(api.cache.values)
    def outage(*_args, **_kwargs):
        raise requests.ConnectionError("synthetic-private-control-location")
    monkeypatch.setattr(perf.requests, "get", outage)
    reply = api.client.delete(f"/perf/tasks/{task_id}")
    business(reply, 503)
    assert "synthetic-private" not in reply.text
    assert business(api.client.get(f"/perf/tasks/{task_id}"))["status"] == status
    assert api.cache.values == before
    monkeypatch.setattr(perf.requests, "get", lambda *_a, **_k: SimpleNamespace(raise_for_status=lambda: None))
    business(api.client.delete(f"/perf/tasks/{task_id}"))
    business(api.client.get(f"/perf/tasks/{task_id}"), 404)
    assert not api.cache.values


def test_pending_deletion_succeeds_and_task_disappears(isolated_perf_api):
    api = isolated_perf_api
    task_id = _task(api).id
    business(api.client.delete(f"/perf/tasks/{task_id}"))
    business(api.client.get(f"/perf/tasks/{task_id}"), 404)
    assert not api.cache.values


def test_missing_task_deletion_returns_404_without_state_changes(isolated_perf_api):
    api = isolated_perf_api
    business(api.client.delete("/perf/tasks/999999"), 404)
    assert business(api.client.get("/perf/tasks")) == []
    assert not api.cache.values


class SyntheticLocustClient:
    def __init__(self):
        self.cookies = {}
        self.rows = defaultdict(lambda: {"num_requests": 0, "num_failures": 0})
        self.request_event = SimpleNamespace(fire=self.event)

    def event(self, request_type, name, exception=None, **_kwargs):
        row = self.rows[name]
        row.update(name=name, method=request_type)
        row["num_requests"] += 1
        row["num_failures"] += int(exception is not None)

    def request(self, method, url, **kwargs):
        parsed = urlsplit(url)
        assert parsed.netloc == "fixture.invalid", "纯夹具适配器不允许外部 Host"
        headers = dict(kwargs["headers"])
        if "json" in kwargs:
            data = json.dumps(kwargs["json"]).encode()
            headers["Content-Type"] = "application/json"
        elif isinstance(kwargs.get("data"), dict):
            data = urlencode(kwargs["data"]).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            data = kwargs.get("data", b"")
        path = parsed.path + ("?" + urlencode(kwargs["params"]) if kwargs["params"] else "")
        status, body = response_for(method, path, headers, data)
        client, name = self, kwargs["name"]
        class Sample:
            status_code = status
            elapsed = timedelta(milliseconds=1)
            headers = {"Content-Type": "application/json"}
            failed = False
            def json(self): return body
            def success(self): self.failed = False
            def failure(self, _reason): self.failed = True
            def __enter__(self): return self
            def __exit__(self, *_args):
                client.event(method, name, exception=RuntimeError("synthetic failure") if self.failed else None)
        return Sample()


@pytest.fixture
def synthetic_worker_api(isolated_perf_api):
    from app.core.perf_plan import execute_iteration
    from app.models.perf import PerfTask
    from app.schemas.perf_plan import PerfLoadConfig
    from app.services import perf
    api = isolated_perf_api
    route_client = api.client
    class Adapter:
        def post(self, *args, **kwargs): return route_client.post(*args, **kwargs)
        def get(self, path, **kwargs):
            if path.startswith("/perf/tasks/"):
                task = api.database.get(PerfTask, int(path.rsplit("/", 1)[1]))
                if task and task.status == "queued":
                    sample_client = SyntheticLocustClient()
                    plan = PerfLoadConfig.model_validate(task.load_config)
                    runs = [execute_iteration(sample_client, task.target_host, plan, "isolated-vu", i) for i in (1, 2)]
                    failures = sum(not row["passed"] for row in runs)
                    task.status = "done"
                    task.started_at = task.finished_at = datetime.utcnow()
                    task.request_stats = list(sample_client.rows.values())
                    task.history_samples = [{"elapsed_s": 2, "rps": 1}]
                    task.iteration_stats = {"lease": api.cache.get(perf.RUN_LOCK_KEY), "iterations": 2,
                        "failures": failures, "configuration_failures": 0, "fail_ratio": failures / 2,
                        "avg_duration_ms": sum(row["duration_ms"] for row in runs) / 2,
                        "iteration_rps": 1, "elapsed_seconds": 2}
                    api.database.flush()
                    from app.repositories.perf import _sync_run
                    _sync_run(api.database, task.id, api.project_id)
                    api.database.commit()
                    api.cache.values.clear()  # This fixture's in-memory lease only.
            return route_client.get(path, **kwargs)
    api.client = Adapter()
    return api


@pytest.mark.parametrize("body_type", ["json", "form", "raw"])
def test_single_post_script_and_real_iteration_engine(synthetic_worker_api, body_type):
    core.test_single_post_sends_configured_body(synthetic_worker_api, "http://fixture.invalid", body_type)
    assert len(synthetic_worker_api.publications) == 1


def test_chain_script_and_real_iteration_engine(synthetic_worker_api):
    core.test_chain_passes_token_order_id_and_typed_variables(synthetic_worker_api, "http://fixture.invalid")


@pytest.mark.parametrize("failure", ["business_assertion", "missing_extraction"])
def test_failed_chain_script_and_real_iteration_engine(synthetic_worker_api, failure):
    core.test_failed_first_step_stops_dependent_requests(synthetic_worker_api, "http://fixture.invalid", failure)


def test_active_delete_http_script_against_actual_routes(isolated_perf_api):
    core.test_deleting_queued_or_running_task_is_conflict(isolated_perf_api, "http://fixture.invalid")


@pytest.mark.parametrize("defect", ["zero_iterations", "no_request_stats", "wrong_method", "missing_chain_step", "continued_after_failure"])
def test_runtime_assertions_reject_false_success(synthetic_worker_api, defect):
    from common.request_util import ResponseView
    from httpx import Response
    api = synthetic_worker_api
    good = api.client
    class Corrupt:
        def post(self, *args, **kwargs): return good.post(*args, **kwargs)
        def get(self, path, **kwargs):
            reply = good.get(path, **kwargs)
            body = deepcopy(reply.envelope_json())
            if isinstance(body["data"], dict) and body["data"].get("status") == "done":
                data = body["data"]
                if defect == "zero_iterations": data["iteration_stats"]["iterations"] = 0
                if defect == "no_request_stats": data["request_stats"] = []
                if defect == "wrong_method": data["request_stats"][0]["method"] = "GET"
                if defect == "missing_chain_step": data["request_stats"] = data["request_stats"][:-1]
                if defect == "continued_after_failure": data["request_stats"].append({"name": "step_02", "method": "POST", "num_requests": 1, "num_failures": 0})
            return ResponseView(Response(reply.status_code, json=body))
    api.client = Corrupt()
    with pytest.raises(AssertionError):
        if defect == "missing_chain_step":
            core.test_chain_passes_token_order_id_and_typed_variables(api, "http://fixture.invalid")
        elif defect == "continued_after_failure":
            core.test_failed_first_step_stops_dependent_requests(api, "http://fixture.invalid", "business_assertion")
        else:
            core.test_single_post_sends_configured_body(api, "http://fixture.invalid", "json")


def test_disabled_perf_fixtures_do_not_bootstrap_accounts_or_load(monkeypatch):
    import importlib.util
    path = Path(core.__file__).with_name("conftest.py")
    spec = importlib.util.spec_from_file_location("isolated_perf_fixtures", path)
    fixtures = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixtures)
    monkeypatch.delenv("WHALE_PERF_CORE_ALLOW_WRITES", raising=False)
    monkeypatch.delenv("WHALE_PERF_ALLOW_LOAD", raising=False)
    monkeypatch.delenv("WHALE_PERF_FIXTURE_BASE_URL", raising=False)
    with pytest.raises(pytest.skip.Exception):
        fixtures.perf_owner.__wrapped__()
    with pytest.raises(pytest.skip.Exception):
        fixtures.perf_load_target.__wrapped__()


@pytest.mark.parametrize("target", [
    "https://fixture.invalid",
    "http://synthetic:synthetic@fixture.invalid",
    "http://fixture.invalid?source=apitest",
    "http://fixture.invalid#synthetic",
    "http://fixture.invalid/echo",
])
def test_enabled_perf_load_target_rejects_non_host_urls(monkeypatch, target):
    import importlib.util
    path = Path(core.__file__).with_name("conftest.py")
    spec = importlib.util.spec_from_file_location("isolated_perf_target_fixtures", path)
    fixtures = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixtures)
    monkeypatch.setenv("WHALE_PERF_ALLOW_LOAD", "1")
    monkeypatch.setenv("WHALE_PERF_FIXTURE_BASE_URL", target)
    with pytest.raises(AssertionError, match="夹具必须是纯 HTTP Host"):
        fixtures.perf_load_target.__wrapped__()


def test_failed_task_cleanup_does_not_cascade_delete_project(monkeypatch):
    import importlib.util
    path = Path(core.__file__).with_name("conftest.py")
    spec = importlib.util.spec_from_file_location("isolated_cleanup_fixtures", path)
    fixtures = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixtures)
    closed = []
    class Workspace:
        def __init__(self, *_args): pass
        def new_project(self):
            reply = SimpleNamespace(status_code=200, envelope_json=lambda: {
                "code": 0, "message": "ok", "data": {"status": "queued"}})
            return 1, 2, SimpleNamespace(get=lambda *_args: reply)
        def close(self): closed.append(True)
        @staticmethod
        def name(prefix): return prefix + "isolated"
    monkeypatch.setattr(fixtures, "CoreWorkspace", Workspace)
    def fail_cleanup(*_args): raise AssertionError("synthetic unavailable control")
    monkeypatch.setattr(fixtures, "_stop_and_delete", fail_cleanup)
    generator = fixtures.perf_api.__wrapped__({"client": object()})
    api = next(generator)
    api.tasks.append(7)
    with pytest.raises(AssertionError, match="保留项目"):
        next(generator)
    assert closed == []


def test_ci_has_single_opt_in_perf_gate_and_fixture_cleanup():
    import yaml
    pipeline = yaml.load((Path(__file__).resolve().parents[1] / ".github/workflows/ci.yml").read_text(encoding="utf-8"),
                         Loader=yaml.BaseLoader)
    assert pipeline["jobs"]["api-test"]["needs"] == "offline-contract"
    steps = pipeline["jobs"]["api-test"]["steps"]
    gates = [step for step in steps if "pytest testcases/test_perf_core" in step.get("run", "")]
    assert len(gates) == 1 and "--reruns 0" in gates[0]["run"]
    assert gates[0]["env"]["WHALE_PERF_CORE_ALLOW_WRITES"] == "1"
    assert gates[0]["env"]["WHALE_PERF_ALLOW_LOAD"] == "1"
    assert gates[0]["env"]["WHALE_PERF_FIXTURE_BASE_URL"] == "http://whaletestpro-perf-fixture:8090"
    assert all("not perf_core" in step["run"] for step in steps if "pytest -m 'integration" in step.get("run", ""))
    cleanup = next(step for step in steps if "docker rm -f whaletestpro-perf-fixture" in step.get("run", ""))
    assert cleanup["if"] == "always()"


@pytest.mark.parametrize("method,path,body,expected", [
    ("GET", "/health", b"", 200),
    ("POST", "/login", b"", 400),
    ("POST", "/login", b"{", 400),
])
def test_fixture_handles_empty_get_and_rejects_invalid_json_login(method, path, body, expected):
    status, value = response_for(method, path, {"Content-Type": "application/json"}, body)
    assert status == expected and value["fixture"] == "whale-perf-core"


def test_catalog_has_independent_complete_design_fields():
    rows = core.CONFIG_CASES
    keys = {"module", "point", "case_id", "title", "priority", "source", "preconditions", "steps", "expected"}
    assert len({row["case_id"] for row in rows}) == len(rows)
    assert all(keys <= row.keys() and all(row[key] for key in keys) for row in rows)
    assert all("同上" not in str(row) for row in rows)
    assert {row["case_id"].split("-")[-1][0] for row in rows} == {"P", "B", "N"}
