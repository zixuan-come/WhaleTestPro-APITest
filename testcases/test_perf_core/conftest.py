"""Opt-in, fresh project; never reset shared Redis or send load by default."""
import os
from types import SimpleNamespace

import pytest

from common.core_flow import CoreWorkspace, business
from common.request_util import RequestUtil
from config import BASE_URL
from common.perf_flow import stop_and_delete as _stop_and_delete


@pytest.fixture(scope="session", autouse=True)
def integration_bootstrap():
    return None


@pytest.fixture(scope="session")
def perf_owner():
    if os.getenv("WHALE_PERF_CORE_ALLOW_WRITES") != "1":
        pytest.skip("压测核心回归创建资产；仅隔离环境启用 WHALE_PERF_CORE_ALLOW_WRITES=1")
    public = RequestUtil(BASE_URL)
    credentials = {"username": CoreWorkspace.name("perf_c_"), "password": CoreWorkspace.name("Perf_")}
    user = business(public.post("/auth/register", json=credentials), 201)
    login = business(public.post("/auth/login", json=credentials))
    return {"id": user["id"], "client": RequestUtil(BASE_URL, headers={
        "Authorization": "Bearer " + login["access_token"]})}


@pytest.fixture
def perf_load_target():
    target = os.getenv("WHALE_PERF_FIXTURE_BASE_URL", "").rstrip("/")
    if os.getenv("WHALE_PERF_ALLOW_LOAD") != "1" or not target:
        pytest.skip("真实压测必须显式启用 WHALE_PERF_ALLOW_LOAD=1 并提供专用夹具 URL")
    from urllib.parse import urlsplit
    parsed = urlsplit(target)
    assert parsed.scheme == "http" and parsed.hostname and not (
        parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path
    ), "夹具必须是纯 HTTP Host；请勿使用真实业务服务"
    return target


@pytest.fixture
def perf_api(perf_owner):
    workspace = CoreWorkspace({"owner": perf_owner}, BASE_URL, "unused")
    tasks = []
    try:
        _, _, client = workspace.new_project()
        yield SimpleNamespace(client=client, tasks=tasks, name=CoreWorkspace.name)
    finally:
        errors = []
        for task_id in reversed(tasks):
            try:
                current = client.get(f"/perf/tasks/{task_id}")
                if current.status_code == 404:
                    continue
                task = business(current)
                if task["status"] == "pending":
                    business(client.delete(f"/perf/tasks/{task_id}"))
                    assert client.get(f"/perf/tasks/{task_id}").status_code == 404
                else:
                    _stop_and_delete(client, task_id)
            except Exception as exc:
                errors.append(f"task {task_id}: {type(exc).__name__}")
        # Never cascade-delete a project while its load task/lease may still live.
        assert not errors, "压测资产清理失败，保留项目供检查：" + "; ".join(errors)
        workspace.close()
