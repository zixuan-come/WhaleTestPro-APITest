"""Core-flow helpers: HTTP only, explicit envelopes and owned-resource cleanup."""
from uuid import uuid4

import allure
import pytest

from common.request_util import RequestUtil


def design_cases(*case_ids):
    """Related design IDs, not a claim that every assertion in Excel is automated."""
    def decorate(function):
        function = pytest.mark.design_case(*case_ids)(function)
        for case_id in case_ids:
            function = allure.label("design_case", case_id)(function)
        return function
    return decorate


def business(response, status=200):
    # Do not print response bodies: login responses can contain real tokens.
    assert response.status_code == status, (
        f"预期 HTTP {status}，实际 {response.status_code}"
    )
    body = response.envelope_json()
    assert isinstance(body, dict) and {"code", "message", "data"} <= body.keys()
    assert body["code"] == (0 if status < 400 else status)
    assert isinstance(body["message"], str) and body["message"]
    return body["data"]


def run_selected_cases(client, ids, env_id=None, notify=False):
    selection = {"mode": "case", "ids": ids, "env_id": env_id}
    plan = business(client.post('/regression/preview', json=selection))
    return client.post('/regression/run', json={**selection, 'preview_key': plan['preview_key'], 'notify': notify})


def bootstrap_core_actors(base_url):
    """Three fresh identities; never clear Redis or reuse existing credentials."""
    public = RequestUtil(base_url, timeout=30)
    actors = {}
    for role in ("owner", "member", "outsider"):
        username = f"core_{role[0]}_{uuid4().hex[:12]}"
        password = f"Core_{uuid4().hex[:12]}"
        user = business(public.post("/auth/register", json={
            "username": username, "password": password,
        }), 201)
        assert user["username"] == username and type(user["id"]) is int
        assert not {"password", "hashed_password"} & user.keys()
        login_response = public.post("/auth/login", json={
            "username": username, "password": password,
        })
        assert login_response.status_code != 429, (
            "核心测试登录遇到 5 次/60 秒限流；请使用独立环境/IP 或等待窗口到期，"
            "本测试不会清理共享 Redis 限流键"
        )
        login = business(login_response)
        assert login["token_type"] == "bearer" and login["access_token"]
        client = RequestUtil(base_url, headers={
            "Authorization": f"Bearer {login['access_token']}",
        }, timeout=30)
        assert business(client.get("/teams")) == []
        actors[role] = {"id": user["id"], "client": client}
    return actors


class CoreWorkspace:
    def __init__(self, actors, base_url, runner_url):
        self.actors = actors
        self.base_url = base_url
        self.runner_url = runner_url
        self.owner = actors["owner"]["client"]
        self.projects = []
        self.teams = []
        self._foreign = None

    @staticmethod
    def name(prefix="core_"):
        return prefix + uuid4().hex[:12]

    def scoped(self, project_id, role="owner"):
        return RequestUtil(self.base_url, headers={
            **self.actors[role]["client"].headers,
            "X-Project-Id": str(project_id),
        }, timeout=30)

    def new_project(self, add_member=False):
        team = business(self.owner.post("/teams", json={"name": self.name("core_team_")}), 201)
        self.teams.append(team["id"])
        project = business(self.owner.post("/projects", json={
            "name": self.name("core_project_"), "team_id": team["id"],
        }), 201)
        self.projects.append(project["id"])
        assert project["team_id"] == team["id"]
        assert business(self.owner.get(f"/projects/{project['id']}"))["id"] == project["id"]
        if add_member:
            row = business(self.owner.post(f"/teams/{team['id']}/members", json={
                "user_id": self.actors["member"]["id"], "role": "member",
            }), 201)
            assert row["user_id"] == self.actors["member"]["id"] and row["role"] == "member"
        return team["id"], project["id"], self.scoped(project["id"])

    def initialize(self):
        self.team_id, self.project_id, self.client = self.new_project(add_member=True)
        return self

    def foreign(self):
        if self._foreign is None:
            self._foreign = self.new_project()
        return self._foreign[2]

    def create(self, path, payload, client=None):
        row = business((client or self.client).post(path, json=payload), 201)
        assert type(row["id"]) is int and row["id"] > 0
        return row

    def environment(self, client=None):
        return self.create("/environments", {
            "name": self.name("core_env_"), "base_url": self.runner_url,
            "variables": {"marker": "from_env"},
        }, client)

    def interface(self, path="/health/live", client=None):
        return self.create("/interfaces", {
            "name": self.name("core_if_"), "method": "GET", "url": path,
        }, client)

    def case(self, interface=None, client=None, **values):
        interface = interface or self.interface(client=client)
        return self.create("/cases", {
            "name": self.name("core_case_"), "interface_id": interface["id"],
            "expected_status": 200, **values,
        }, client)

    def scenario(self, case_ids, client=None):
        return self.create("/scenarios", {
            "name": self.name("core_scenario_"), "case_ids": case_ids,
        }, client)

    def suite(self, client=None, **values):
        return self.create("/suites", {
            "name": self.name("core_suite_"), "type": "case", **values,
        }, client)

    def reports(self, scenario=False, client=None):
        return business((client or self.client).get(
            "/reports/scenarios" if scenario else "/reports",
            params={"page": 1, "page_size": 100},
        ))

    def close(self):
        # Projects delete their own dependent reports/assets transactionally.
        # Only IDs created and registered by this workspace may be deleted.
        errors = []
        for kind, ids in (("projects", self.projects), ("teams", self.teams)):
            for resource_id in reversed(ids):
                try:
                    response = self.owner.delete(f"/{kind}/{resource_id}")
                    if response.status_code not in {200, 404}:
                        errors.append(f"/{kind}/{resource_id}: HTTP {response.status_code}")
                except Exception as exc:
                    errors.append(f"/{kind}/{resource_id}: {type(exc).__name__}")
        assert not errors, "本轮资产清理失败，未删除任何未登记资产：" + "; ".join(errors)
