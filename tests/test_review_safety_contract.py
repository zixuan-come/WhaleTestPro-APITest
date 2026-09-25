"""Safety regressions using synthetic .env and fixture transports only."""
import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest
from packaging.requirements import Requirement

import config
from tests.test_fixture_contract import _fixture_module
from tests.test_perf_core_contract import isolated_perf_api, _task
from common.core_flow import business


def test_offline_guard_redis_dependency_is_declared():
    # Marker selection still imports tests/conftest.py during collection.
    root = Path(__file__).resolve().parents[1]
    lines = (root / "requirements.txt").read_text(encoding="utf-8").splitlines()
    names = {Requirement(line.split("#", 1)[0].strip()).name.lower()
             for line in lines if line.split("#", 1)[0].strip()}
    assert "redis" in names, "Redis I/O guard must not rely on backend-only dependencies"


def test_runtime_target_priority_is_documented():
    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    assert "进程环境变量优先" in readme
    assert "它会覆盖同名环境变量" not in readme


def test_perf_owner_fixture_generates_valid_registration_credentials(monkeypatch):
    from testcases.test_perf_core import conftest as fixtures
    monkeypatch.setenv("WHALE_PERF_CORE_ALLOW_WRITES", "1")
    registrations = []

    class SyntheticClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def post(self, path, json):
            if path == "/auth/register":
                registrations.append(json.copy())
                assert 4 <= len(json["username"]) <= 20
                assert 4 <= len(json["password"]) <= 20
                data, status = {"id": 1}, 201
            else:
                assert path == "/auth/login" and json == registrations[0]
                data, status = {"access_token": "synthetic-owner-token"}, 200
            return SimpleNamespace(status_code=status, envelope_json=lambda: {
                "code": 0, "message": "synthetic-success", "data": data})

    monkeypatch.setattr(fixtures, "RequestUtil", SyntheticClient)
    assert fixtures.perf_owner.__wrapped__()["id"] == 1
    assert len(registrations) == 1


@pytest.mark.parametrize("key,value", [
    ("WHALE_PERF_ALLOW_LOAD", "0"), ("WHALE_PERF_CORE_ALLOW_WRITES", "0"),
    ("WHALE_CORE_ALLOW_WRITES", "0"),
    ("WHALE_BASE_URL", "http://isolated.invalid"),
    ("WHALE_PERF_BASE_URL", "http://fixture.invalid"),
    ("WHALE_RUNNER_BASE_URL", "http://runner.invalid"),
    ("WHALE_PERF_FIXTURE_BASE_URL", "http://fixture.invalid"),
])
def test_process_environment_wins_over_env_file(monkeypatch, tmp_path, key, value):
    monkeypatch.setenv(key, value)
    env = tmp_path / "synthetic.env"
    env.write_text(f"{key}=1\n", encoding="utf-8")
    config.load_env_file(env)
    assert config.os.environ[key] == value


def test_env_file_still_supplies_unset_defaults(monkeypatch, tmp_path):
    monkeypatch.delenv("WHALE_REVIEW_SYNTHETIC", raising=False)
    env = tmp_path / "synthetic.env"
    env.write_text("WHALE_REVIEW_SYNTHETIC='default'\n", encoding="utf-8")
    config.load_env_file(env)
    assert config.os.environ["WHALE_REVIEW_SYNTHETIC"] == "default"
    monkeypatch.delenv("WHALE_REVIEW_SYNTHETIC")


def _invoke(fixtures, name, args, state):
    function = getattr(fixtures, name).__wrapped__
    kwargs = {"cleanup_state": state} if "cleanup_state" in inspect.signature(function).parameters else {}
    return function(*args, **kwargs)


@pytest.mark.parametrize("failure", [409, 503, OSError("synthetic-offline-error")])
def test_failed_perf_cleanup_is_reported_and_retains_project_and_team(failure, caplog):
    fixtures = _fixture_module()
    state = SimpleNamespace(retained_projects=set(), retained_teams=set())
    calls = []
    def post(path, **_kwargs):
        return SimpleNamespace(status_code=201, text="synthetic", json=lambda: {"id": 77 if path == "/teams" else 88})
    def owner_delete(path):
        calls.append(path)
        return SimpleNamespace(status_code=200, text="synthetic")
    owner = SimpleNamespace(post=post, delete=owner_delete)
    teams = _invoke(fixtures, "team_factory", (owner,), state)
    make_team = next(teams)
    team_id = make_team()
    projects = _invoke(fixtures, "project_id", (owner, team_id), state)
    project_id = next(projects)
    def unsafe_delete(path):
        calls.append(path)
        if isinstance(failure, Exception):
            raise failure
        return SimpleNamespace(status_code=failure)
    client = SimpleNamespace(headers={"X-Project-Id": str(project_id)}, delete=unsafe_delete)
    cleanup = _invoke(fixtures, "api_cleanup", (client,), state)
    next(cleanup)("/perf/tasks/5")
    with pytest.raises(AssertionError, match="压测清理失败"):
        next(cleanup)
    with pytest.raises(StopIteration):
        next(projects)
    with pytest.raises(StopIteration):
        next(teams)
    assert calls == ["/perf/tasks/5"]
    assert state.retained_projects == {88} and state.retained_teams == {77}
    assert "88" in caplog.text and "77" in caplog.text


@pytest.mark.parametrize("status", [200, 404])
def test_verified_perf_cleanup_allows_normal_parent_cleanup(status):
    fixtures = _fixture_module()
    state = SimpleNamespace(retained_projects=set(), retained_teams=set())
    client = SimpleNamespace(headers={"X-Project-Id": "88"},
                             delete=lambda _: SimpleNamespace(status_code=status))
    cleanup = _invoke(fixtures, "api_cleanup", (client,), state)
    next(cleanup)("/perf/tasks/5")
    with pytest.raises(StopIteration):
        next(cleanup)
    assert not state.retained_projects and not state.retained_teams


@pytest.mark.parametrize("status", ["queued", "running", "done", "failed", "cancelled"])
def test_project_delete_http_contract_preserves_active_or_uncleared_perf(isolated_perf_api, status):
    from app.services import perf
    from app.models.project import Project
    api = isolated_perf_api
    task = _task(api, status)
    api.cache.values[perf.RUN_LOCK_KEY] = f"{api.project_id}:{task.id}:synthetic-message"
    before = dict(api.cache.values)
    business(api.client.delete(f"/projects/{api.project_id}"), 409)
    assert api.database.get(Project, api.project_id)
    assert api.cache.values == before


def test_project_delete_http_contract_fails_closed_on_redis_outage(isolated_perf_api, monkeypatch):
    from app.models.project import Project
    import redis
    api = isolated_perf_api
    def unavailable(_key):
        raise redis.ConnectionError("synthetic-private-redis-location")
    monkeypatch.setattr(api.cache, "get", unavailable)
    reply = api.client.delete(f"/projects/{api.project_id}")
    business(reply, 503)
    assert "synthetic-private" not in reply.text
    assert api.database.get(Project, api.project_id)
