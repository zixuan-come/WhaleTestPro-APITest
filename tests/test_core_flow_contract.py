"""Execute the HTTP test functions on real routes + isolated SQLite, no network.

Authentication identities and downstream health responses are controlled doubles.
This verifies test logic/backend contracts, not deployed JWT/Redis/network wiring.
"""
import ast
import importlib.util
import json
import os
import re
from collections import Counter
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from common.core_flow import CoreWorkspace, bootstrap_core_actors, business
from common.request_util import RequestUtil
from testcases.test_core import test_core_flows as core


CORE_CHECKS = [
    ("test_interface_trial_does_not_create_reports", {}, 1),
    ("test_case_execution_persists_matching_report", {}, 1),
    ("test_deleted_case_returns_business_error_without_report", {}, 0),
    ("test_missing_template_variable_persists_failed_report", {}, 0),
    ("test_case_rejects_foreign_environment_without_report", {}, 0),
    ("test_chain_shares_extracted_variable_in_order", {}, 2),
    ("test_empty_chain_creates_no_report", {}, 0),
    ("test_chain_rejects_wrapped_body_without_reports", {}, 0),
    ("test_chain_failure_does_not_block_later_case", {}, 2),
    ("test_scenario_report_preserves_order_and_evidence", {}, 2),
    ("test_empty_scenario_is_not_a_pass", {}, 0),
    ("test_scenario_rejects_foreign_environment_without_report", {}, 0),
    ("test_regression_reports_counts_and_ratio", {}, 2),
    ("test_explicit_empty_regression_does_not_select_all_cases", {}, 0),
    ("test_regression_rejects_non_integer_ids", {}, 0),
    ("test_regression_explicit_ids_take_precedence_over_tag", {}, 1),
    ("test_suite_partial_update_preserves_bindings", {}, 0),
    ("test_suite_null_update_is_rejected", {"field": "name"}, 0),
    ("test_suite_null_update_is_rejected", {"field": "type"}, 0),
    ("test_mixed_suite_deduplicates_scenario_case_and_tag_sources", {}, 2),
    ("test_empty_suite_summary_is_failed", {}, 0),
    ("test_suite_rejects_foreign_environment_before_execution", {}, 0),
    ("test_suite_foreign_children_fail_without_foreign_reports", {}, 1),
    ("test_suite_anonymous_and_outsider_are_rejected", {"actor": "anonymous", "status": 401}, 0),
    ("test_suite_anonymous_and_outsider_are_rejected", {"actor": "outsider", "status": 404}, 0),
    ("test_member_suite_write_toggle_does_not_disable_read_or_execute", {}, 2),
    ("test_suite_delete_preserves_execution_history", {}, 1),
    ("test_interface_reference_migration_preserves_cases_and_scenario", {}, 3),
    ("test_referenced_interface_delete_is_conflict_without_data_loss", {}, 0),
]


@pytest.fixture
def isolated_core_api(monkeypatch):
    backend = Path(os.environ.get("WHALE_BACKEND_PATH", Path(__file__).resolve().parents[2] / "WhaleTestPro")).resolve()
    assert (backend / "app").is_dir(), "需要相邻 WhaleTestPro 源码或 WHALE_BACKEND_PATH"
    monkeypatch.syspath_prepend(str(backend))
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("SHADOW_DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("SECRET_KEY", "isolated-core-contract-key-not-for-production-32bytes")
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.exceptions import RequestValidationError
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool
    from app.database import Base, get_db
    from app.core.authentication import get_current_user
    from app.core.exception_handlers import http_exception_handler, validation_exception_handler
    from app.core.security import decode_access_token
    from app.core import circuit_breaker
    from app.models.user import User
    from app.routers import user, team, project, environment, interface, case, scenario, report, regression, suite
    from app.services import execution
    from app.services import perf as perf_service
    from types import SimpleNamespace
    monkeypatch.setattr(perf_service.redis, "from_url", lambda _: SimpleNamespace(get=lambda _key: None))
    import httpx
    import requests

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    database = Session(engine)
    Base.metadata.create_all(engine)
    database.execute(text("PRAGMA foreign_keys=ON"))
    database.add_all([User(id=i, username=f"isolated_core_{i}", hashed_password="unused") for i in (1, 2, 3)])
    database.commit()
    application = FastAPI()
    for module in (user, team, project, environment, interface, case, scenario, report, regression, suite):
        application.include_router(module.router)
    application.add_exception_handler(HTTPException, http_exception_handler)
    application.add_exception_handler(RequestValidationError, validation_exception_handler)
    application.dependency_overrides[get_db] = lambda: database

    def actor(request: Request):
        value = request.headers.get("Authorization", "").removeprefix("Bearer ")
        user_id = int(value) if value in {"1", "2", "3"} else decode_access_token(value)
        result = database.get(User, user_id) if user_id is not None else None
        if result is None:
            raise HTTPException(401, "isolated authentication rejected")
        return result

    application.dependency_overrides[get_current_user] = actor
    application.dependency_overrides[user.login_rate_limit] = lambda: None
    calls = []

    def downstream(method, url, **kwargs):
        # Nothing reaches requests.Session or a TCP socket.
        assert method == "GET" and urlsplit(url).netloc == "runner.invalid"
        assert urlsplit(url).path == "/health/live"
        calls.append((method, url))
        response = requests.Response()
        response.status_code = 200
        response.url = url
        response.headers["Content-Type"] = "application/json"
        response._content = b'{"code":0,"message":"alive","data":{"status":"alive"}}'
        response.elapsed = timedelta(milliseconds=1)
        return response

    monkeypatch.setattr(execution.requests, "request", downstream)
    monkeypatch.setattr(circuit_breaker, "_breakers", {})
    try:
        with TestClient(application) as local:
            def transport(method, url, **kwargs):
                assert urlsplit(url).netloc == "isolated.invalid"
                kwargs.pop("timeout", None)
                return local.request(method, urlsplit(url).path, **kwargs)
            monkeypatch.setattr(httpx, "request", transport)
            actors = {role: {"id": i, "client": RequestUtil("http://isolated.invalid", headers={"Authorization": f"Bearer {i}"})}
                      for role, i in (("owner", 1), ("member", 2), ("outsider", 3))}
            yield actors, calls, database
    finally:
        database.close()
        engine.dispose()


@pytest.mark.parametrize("name,parameters,expected_calls", CORE_CHECKS,
                         ids=[name.removeprefix("test_") + ("_" + "_".join(str(v) for v in args.values()) if args else "") for name, args, _ in CORE_CHECKS])
def test_core_script_against_actual_routes(isolated_core_api, name, parameters, expected_calls):
    actors, calls, database = isolated_core_api
    workspace = CoreWorkspace(actors, "http://isolated.invalid", "http://runner.invalid")
    try:
        workspace.initialize()
        getattr(core, name)(workspace, **parameters)
        assert len(calls) == expected_calls, "下游调用数量偏离核心链路预期"
    finally:
        workspace.close()
    from app.models.team import Team
    from app.models.project import Project
    from app.models.report import TestReport as Report
    from app.models.scenario_report import ScenarioReport
    assert all(database.query(model).count() == 0 for model in (Team, Project, Report, ScenarioReport))


def test_bootstrap_uses_fresh_accounts_and_valid_tokens_without_docker(isolated_core_api):
    _, calls, database = isolated_core_api
    actors = bootstrap_core_actors("http://isolated.invalid")
    assert set(actors) == {"owner", "member", "outsider"}
    assert len({actor["id"] for actor in actors.values()}) == 3
    assert all(business(actor["client"].get("/teams")) == [] for actor in actors.values())
    assert calls == []
    from app.models.user import User
    assert database.query(User).count() == 6


def test_design_ids_and_offline_checks_remain_traceable():
    backend = Path(os.environ.get("WHALE_BACKEND_PATH", Path(__file__).resolve().parents[2] / "WhaleTestPro"))
    catalog_path = backend / "docs/testing/testcases/api-testcases.json"
    assert catalog_path.is_file(), "完整设计台账是编号核验的基线，不能缺失后静默跳过"
    catalog = {case["id"]: case for case in json.loads(catalog_path.read_text(encoding="utf-8"))["cases"]}
    functions = {name: func for name, func in vars(core).items() if name.startswith("test_") and callable(func)}
    assert set(functions) == {name for name, _, _ in CORE_CHECKS}
    mapping = Path(__file__).resolve().parents[1] / "docs/核心链路自动化映射.md"
    rows = {}
    for line in mapping.read_text(encoding="utf-8").splitlines():
        if line.startswith("| `"):
            _, short_name, variants, linked_ids, _assertions, _ = line.split("|")
            rows["test_" + short_name.strip().strip("`")] = (
                int(variants), set(re.findall(r"WTP-API-\d{3}-[PBNX]\d{3}", linked_ids)),
            )
    assert set(rows) == set(functions), "映射文档与测试函数不一致"
    offline_counts = Counter(name for name, _, _ in CORE_CHECKS)
    for name, func in functions.items():
        ids = [case_id for mark in func.pytestmark if mark.name == "design_case" for case_id in mark.args]
        assert ids and all(case_id in catalog for case_id in ids), name
        labels = {case_id for mark in func.pytestmark if mark.name == "allure_label"
                  and mark.kwargs.get("label_type") == "design_case" for case_id in mark.args}
        assert labels == set(ids), "Allure 缺少设计编号标签"
        variants = 1
        for mark in func.pytestmark:
            if mark.name == "parametrize":
                variants *= len(mark.args[1])
        assert rows[name] == (variants, set(ids))
        assert offline_counts[name] == variants, "参数化场景未完整加入离线验证"
    fixture_path = Path(core.__file__).with_name("conftest.py")
    tree = ast.parse(fixture_path.read_text(encoding="utf-8"))
    bootstrap = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "integration_bootstrap")
    assert not bootstrap.args.args
    assert not any(isinstance(node, ast.Call) for statement in bootstrap.body for node in ast.walk(statement))


def test_cleanup_reports_failures_and_only_visits_registered_ids():
    from types import SimpleNamespace
    paths = []
    def delete(path):
        paths.append(path)
        return SimpleNamespace(status_code=503)
    workspace = CoreWorkspace({"owner": {"client": SimpleNamespace(delete=delete)}}, "unused", "unused")
    workspace.projects = [11, 12]
    workspace.teams = [21]
    with pytest.raises(AssertionError, match="本轮资产清理失败"):
        workspace.close()
    assert paths == ["/projects/12", "/projects/11", "/teams/21"]


def test_disabled_core_fixture_never_contacts_http(monkeypatch):
    path = Path(core.__file__).with_name("conftest.py")
    spec = importlib.util.spec_from_file_location("isolated_core_fixtures", path)
    fixtures = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixtures)
    monkeypatch.delenv("WHALE_CORE_ALLOW_WRITES", raising=False)
    with pytest.raises(pytest.skip.Exception, match="隔离环境"):
        fixtures.core_actors.__wrapped__()
