"""Offline regression for team/project fixtures. Run explicitly: pytest tests/.

Uses the sibling backend's actual routes with an isolated SQLite database;
does not contact Docker, Redis or the configured WHALE_BASE_URL.
"""
from pathlib import Path
from types import SimpleNamespace
import sys
import os
import importlib.util

import pytest


def _fixture_module():
    # Pytest loads three different conftest.py files; importing bare `conftest`
    # can accidentally select the subtree module instead of the shared fixtures.
    path = Path(__file__).resolve().parents[1] / "conftest.py"
    spec = importlib.util.spec_from_file_location("isolated_shared_fixtures", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def offline_api(monkeypatch):
    backend = Path(os.environ.get("WHALE_BACKEND_PATH", Path(__file__).resolve().parents[2] / "WhaleTestPro")).resolve()
    if not (backend / "app").is_dir():
        pytest.fail("离线跨仓契约验证需要 WhaleTestPro 源码；可设置 WHALE_BACKEND_PATH")
    monkeypatch.syspath_prepend(str(backend))
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("SHADOW_DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("SECRET_KEY", "isolated-fixture-test-key")
    from fastapi import FastAPI, Request
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool
    from app.core.celery_app import celery_app
    from app.database import Base, get_db
    from app.models.user import User
    from app.routers import team, project, environment, schedule, suite
    from app.core.exception_handlers import http_exception_handler, validation_exception_handler
    from fastapi import HTTPException
    from fastapi.exceptions import RequestValidationError
    from app.services import schedule as schedule_service
    from app.services import perf as perf_service
    monkeypatch.setattr(perf_service.redis, "from_url", lambda _: SimpleNamespace(get=lambda _key: None))
    from common.request_util import RequestUtil, ResponseView
    import httpx

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    database = Session(engine)
    database.add_all([User(id=i, username=f"fixture-user-{i}", hashed_password="fake") for i in range(1, 5)])
    database.commit()
    application = FastAPI()
    application.include_router(team.router)
    application.include_router(project.router)
    application.include_router(environment.router)
    application.include_router(schedule.router)
    application.include_router(suite.router)
    application.add_exception_handler(HTTPException, http_exception_handler)
    application.add_exception_handler(RequestValidationError, validation_exception_handler)
    monkeypatch.setattr(schedule_service.scheduler, "sync_schedule", lambda _: None)
    monkeypatch.setattr(schedule_service.scheduler, "remove_schedule", lambda _: None)
    application.dependency_overrides[get_db] = lambda: database
    def actor(request: Request):
        user_id = int(request.headers.get("Authorization", "Bearer 1").split()[-1])
        return database.get(User, user_id)
    application.dependency_overrides[team.get_current_user] = actor
    with TestClient(application) as local:
        def transport(method, url, **kwargs):
            # Route all RequestUtil calls to the isolated app, never the network.
            from urllib.parse import urlsplit
            kwargs.pop("timeout", None)
            return local.request(method, urlsplit(url).path, **kwargs)
        monkeypatch.setattr(httpx, "request", transport)
        owner = RequestUtil("http://isolated.invalid", headers={"Authorization": "Bearer 1"})
        yield owner, RequestUtil, database
    database.close()
    engine.dispose()


def test_shared_project_fixture_creates_explicit_team_and_cleans_up(offline_api):
    fixtures = _fixture_module()
    from app.models.project import Project
    from app.models.team import Team
    owner, _, db = offline_api
    state = fixtures.ResourceCleanupState()
    teams = fixtures.team_factory.__wrapped__(owner, state)
    make_team = next(teams)
    team_id = make_team()
    projects = fixtures.project_id.__wrapped__(owner, team_id, state)
    project_id = next(projects)
    assert db.get(Project, project_id).team_id == team_id
    with pytest.raises(StopIteration):
        next(projects)
    with pytest.raises(StopIteration):
        next(teams)
    assert db.query(Project).count() == db.query(Team).count() == 0


@pytest.mark.parametrize("failure", [409, 503, OSError("synthetic-project-delete-error")])
def test_project_fixture_retains_project_and_team_when_delete_is_unconfirmed(failure):
    fixtures = _fixture_module()
    state = fixtures.ResourceCleanupState()
    deleted_paths = []

    def post(path, **_kwargs):
        resource_id = 77 if path == "/teams" else 88
        return SimpleNamespace(status_code=201, text="synthetic", json=lambda: {"id": resource_id})

    def delete(path):
        deleted_paths.append(path)
        if isinstance(failure, Exception):
            raise failure
        return SimpleNamespace(status_code=failure, text="synthetic")

    owner = SimpleNamespace(post=post, delete=delete)
    teams = fixtures.team_factory.__wrapped__(owner, state)
    team_id = next(teams)()
    projects = fixtures.project_id.__wrapped__(owner, team_id, state)
    assert next(projects) == 88

    with pytest.raises(AssertionError, match="项目清理未确认"):
        next(projects)
    with pytest.raises(StopIteration):
        next(teams)

    assert deleted_paths == ["/projects/88"], "项目删除未确认时不能级联删除父团队"
    assert state.retained_projects == {88} and state.retained_teams == {77}


@pytest.mark.parametrize("actor, expected_status", [("owner", 201), ("admin", 201), ("member", 403), ("outsider", 403)])
def test_project_creation_role_matrix_against_actual_routes(offline_api, actor, expected_status):
    fixtures = _fixture_module()
    from testcases.test_project.test_project import TestCreateProject
    owner, request_util, _ = offline_api
    teams = fixtures.team_factory.__wrapped__(owner, fixtures.ResourceCleanupState())
    make_team = next(teams)
    users = {role: {"id": user_id, "client": request_util("http://isolated.invalid", headers={"Authorization": f"Bearer {user_id}"})}
             for role, user_id in (("admin", 2), ("member", 3), ("outsider", 4))}
    counter = iter(range(100))
    unique = lambda prefix: prefix + str(next(counter))
    contexts = fixtures.team_member_context.__wrapped__(owner, users, unique, make_team)
    context = next(contexts)
    try:
        TestCreateProject().test_explicit_team_creation_role_matrix(actor, expected_status, context, unique)
    finally:
        with pytest.raises(StopIteration):
            next(contexts)
        with pytest.raises(StopIteration):
            next(teams)


@pytest.mark.parametrize("env_id, expected_status", [(None, 422), (0, 422), (999999999, 404)])
def test_schedule_environment_contract_against_actual_routes(offline_api, env_id, expected_status):
    from testcases.test_schedule.test_schedule import TestCreateSchedule
    owner, request_util, _ = offline_api
    team = owner.post("/teams", json={"name": "environment-contract-team"}).json()["id"]
    project = owner.post("/projects", json={"name": "environment-contract-project", "team_id": team}).json()["id"]
    scoped = request_util("http://isolated.invalid", headers={**owner.headers, "X-Project-Id": str(project)})
    TestCreateSchedule().test_create_rejects_invalid_environment(env_id, expected_status, scoped, lambda prefix: prefix + "unique")


def test_schedule_toggle_preserves_bindings_against_actual_routes(offline_api):
    from testcases.test_schedule.test_schedule import TestUpdateSchedule
    owner, request_util, _ = offline_api
    team = owner.post("/teams", json={"name": "toggle-contract-team"}).json()["id"]
    project = owner.post("/projects", json={"name": "toggle-contract-project", "team_id": team}).json()["id"]
    scoped = request_util("http://isolated.invalid", headers={**owner.headers, "X-Project-Id": str(project)})
    environment = scoped.post("/environments", json={"name": "local", "base_url": "http://isolated.invalid"}).json()["id"]
    cleanups = []
    try:
        TestUpdateSchedule().test_toggle_preserves_suite_and_environment(scoped, lambda prefix: prefix + "unique", cleanups.append, environment)
    finally:
        for path in reversed(cleanups):
            assert scoped.delete(path).status_code == 200


def test_cross_project_schedule_environment_is_rejected_by_actual_routes(offline_api):
    from testcases.test_schedule.test_schedule import TestCreateSchedule
    owner, request_util, _ = offline_api
    team = owner.post("/teams", json={"name": "cross-env-team"}).json()["id"]
    projects = [owner.post("/projects", json={"name": f"cross-env-project-{i}", "team_id": team}).json()["id"] for i in range(2)]
    scoped = request_util("http://isolated.invalid", headers={**owner.headers, "X-Project-Id": str(projects[0])})
    context = {"clients": {"owner": owner}, "project_id": projects[1]}
    TestCreateSchedule().test_environment_from_other_project_is_rejected(scoped, context, lambda prefix: prefix + "unique")


def test_member_context_creates_both_explicit_teams(offline_api):
    fixtures = _fixture_module()
    from app.models.project import Project
    from app.models.team import Team
    owner, request_util, db = offline_api
    teams = fixtures.team_factory.__wrapped__(owner, fixtures.ResourceCleanupState())
    make_team = next(teams)
    users = {role: {"id": user_id, "client": request_util("http://isolated.invalid", headers={"Authorization": f"Bearer {user_id}"})}
             for role, user_id in (("admin", 2), ("member", 3), ("outsider", 4))}
    counter = iter(range(100))
    context = fixtures.team_member_context.__wrapped__(owner, users, lambda prefix: prefix + str(next(counter)), make_team)
    data = next(context)
    other = data["make_other_team"]()
    assert db.get(Project, data["project_id"]).team_id == data["team_id"]
    assert db.get(Project, other["project_id"]).team_id == other["team_id"]
    assert other["team_id"] != data["team_id"]
    with pytest.raises(StopIteration):
        next(context)
    with pytest.raises(StopIteration):
        next(teams)
    assert db.query(Project).count() == db.query(Team).count() == 0


def test_schedule_not_found_with_valid_environment_reaches_actual_handler(offline_api):
    from testcases.test_contract.test_negative_contract import TestNegativeContract, resources
    owner, request_util, _ = offline_api
    team_id = owner.post("/teams", json={"name": "schedule-not-found-team"}).json()["id"]
    project_id = owner.post("/projects", json={"name": "schedule-not-found-project", "team_id": team_id}).json()["id"]
    client = request_util("http://isolated.invalid", headers={**owner.headers, "X-Project-Id": str(project_id)})
    env_id = client.post("/environments", json={"name": "local", "base_url": "http://isolated.invalid"}).json()["id"]
    schedule = next(row for row in resources if row["name"] == "schedule")
    TestNegativeContract().test_update_not_found(schedule, client, env_id)


@pytest.mark.parametrize("field", ["name", "type"])
def test_suite_null_update_returns_422_and_preserves_actual_row(offline_api, field):
    owner, request_util, _ = offline_api
    team_id = owner.post("/teams", json={"name": "suite-null-team"}).json()["id"]
    project_id = owner.post("/projects", json={"name": "suite-null-project", "team_id": team_id}).json()["id"]
    client = request_util("http://isolated.invalid", headers={**owner.headers, "X-Project-Id": str(project_id)})
    suite_id = client.post("/suites", json={"name": "safe-suite", "type": "case"}).json()["id"]
    assert client.put(f"/suites/{suite_id}", json={field: None}).status_code == 422
    row = client.get(f"/suites/{suite_id}").json()
    assert row["name"] == "safe-suite" and row["type"] == "case"


def test_executed_suite_deletion_preserves_report_through_actual_routes(offline_api):
    from sqlalchemy import text
    from app.models.report import TestReport as Report
    owner, request_util, db = offline_api
    db.execute(text("PRAGMA foreign_keys=ON"))
    assert db.execute(text("PRAGMA foreign_keys")).scalar() == 1
    team_id = owner.post("/teams", json={"name": "suite-report-team"}).json()["id"]
    project_id = owner.post("/projects", json={"name": "suite-report-project", "team_id": team_id}).json()["id"]
    client = request_util("http://isolated.invalid", headers={**owner.headers, "X-Project-Id": str(project_id)})
    suite_id = client.post("/suites", json={"name": "historical-suite", "type": "case"}).json()["id"]
    assert client.post(f"/suites/{suite_id}/run").status_code == 200
    report_id = db.query(Report).filter_by(suite_id=suite_id).one().id
    assert client.delete(f"/suites/{suite_id}").status_code == 200
    assert client.get(f"/suites/{suite_id}").status_code == 404
    db.expire_all()
    report = db.get(Report, report_id)
    assert report.suite_id is None and report.suite_name == "historical-suite"


@pytest.mark.parametrize("environment_kind", ["missing", "foreign"])
def test_empty_suite_rejects_invalid_environment_through_actual_routes(offline_api, environment_kind):
    from app.models.report import TestReport as Report
    owner, request_util, db = offline_api
    team_id = owner.post("/teams", json={"name": "suite-env-team"}).json()["id"]
    projects = [owner.post("/projects", json={"name": f"suite-env-project-{index}", "team_id": team_id}).json()["id"] for index in range(2)]
    clients = [request_util("http://isolated.invalid", headers={**owner.headers, "X-Project-Id": str(project)}) for project in projects]
    foreign_env = clients[1].post("/environments", json={"name": "foreign", "base_url": "http://isolated.invalid"}).json()["id"]
    suite_id = clients[0].post("/suites", json={"name": "empty-suite", "type": "case"}).json()["id"]
    env_id = foreign_env if environment_kind == "foreign" else 999999
    assert clients[0].post(f"/suites/{suite_id}/run", params={"env_id": env_id}).status_code == 404
    assert db.query(Report).count() == 0
