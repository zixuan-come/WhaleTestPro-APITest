"""HTTP contracts added on 2026-10-17; reuse the isolated core write gate."""
from urllib.parse import urlsplit

import allure
import pytest

from common.core_flow import business

pytestmark = [pytest.mark.core_flow, allure.feature("10月17日请求配置增量")]


def configured_interface(w):
    return w.create("/interfaces", {
        "name": w.name("delta_if_"), "method": "GET", "url": "/health/{endpoint}",
        "path_params": {"endpoint": "live"}, "headers": {"X-Config": "base"},
        "params": {"marker": "base"}, "body": {"label": "base"},
    })


def test_path_defaults_roundtrip(core_workspace):
    w = core_workspace
    interface = configured_interface(w)
    assert business(w.client.get(f"/interfaces/{interface['id']}")) == interface
    values = {"endpoint": "live", "zero": 0, "enabled": False}
    updated = business(w.client.put(f"/interfaces/{interface['id']}", json={
        **interface, "path_params": values,
    }))
    assert updated["path_params"] == values
    listed = business(w.client.get("/interfaces"))
    assert next(row for row in listed if row["id"] == interface["id"])["path_params"] == values


@pytest.mark.parametrize("mode", ["no_body", "null_body", "temporary", "legacy_path"])
def test_debug_configuration_is_temporary(core_workspace, mode):
    w = core_workspace
    interface, env = configured_interface(w), w.environment()
    payload = {
        "temporary": {"request_overrides": {
            "path_params": {"endpoint": "live"}, "headers": {},
            "params": {"marker": "trial"}, "body": None,
        }},
        "legacy_path": {"path_params": {"endpoint": "${marker}"}},
    }.get(mode)
    if mode == "legacy_path":
        # The environment fallback renders a Path value before URL encoding.
        env = business(w.client.put(f"/environments/{env['id']}", json={
            "name": env["name"], "base_url": w.runner_url, "variables": {"marker": "live"},
        }))
    options = {} if mode == "no_body" else {"content": "null", "headers": {"Content-Type": "application/json"}}
    if payload is not None:
        options = {"json": payload}
    result = business(w.client.post(f"/interfaces/{interface['id']}/run",
                                    params={"env_id": env["id"]}, **options))
    assert result["passed"] is True and result["response"]["status_code"] == 200
    request = result["request"]
    assert urlsplit(request["url"]).path == "/health/live"
    assert request["headers"] == ({} if mode == "temporary" else interface["headers"])
    assert request["params"] == ({"marker": "trial"} if mode == "temporary" else interface["params"])
    assert request["body"] == (None if mode == "temporary" else interface["body"])
    assert business(w.client.get(f"/interfaces/{interface['id']}")) == interface
    assert business(w.client.get("/cases")) == []
    assert w.reports()["total"] == w.reports(scenario=True)["total"] == 0


@pytest.mark.parametrize("value", [None, "", ".."])
def test_invalid_path_value_returns_failed_debug(core_workspace, value):
    w = core_workspace
    interface, env = configured_interface(w), w.environment()
    result = business(w.client.post(f"/interfaces/{interface['id']}/run",
                                    params={"env_id": env["id"]},
                                    json={"path_params": {"endpoint": value}}))
    assert result["passed"] is False and result["error"]
    assert result["request"] is None and result["response"] is None
    assert business(w.client.get(f"/interfaces/{interface['id']}")) == interface
    assert w.reports()["total"] == 0


@pytest.mark.parametrize("target,payload", [
    ("interface", {"path_params": {"endpoint": []}}),
    ("debug", {"request_overrides": {"url": "/other"}}),
    ("case", {"request_overrides": {"method": "POST"}}),
    ("case", {"request_overrides": {"path_params": {"endpoint": {"nested": 1}}}}),
])
def test_invalid_request_configuration_is_rejected(core_workspace, target, payload):
    w = core_workspace
    interface = configured_interface(w)
    if target == "interface":
        response = w.client.post("/interfaces", json={**interface, "name": w.name(), **payload})
    elif target == "debug":
        response = w.client.post(f"/interfaces/{interface['id']}/run", json=payload)
    else:
        response = w.client.post("/cases", json={
            "name": w.name(), "interface_id": interface["id"], "expected_status": 200, **payload,
        })
    business(response, 422)
    assert business(w.client.get("/cases")) == [] and w.reports()["total"] == 0


def test_case_overrides_roundtrip_and_reset(core_workspace):
    w = core_workspace
    interface = configured_interface(w)
    overrides = {"params": {}, "body": None}
    case = w.case(interface=interface, request_overrides=overrides)
    assert case["request_overrides"] == overrides
    assert business(w.client.get(f"/cases/{case['id']}"))["request_overrides"] == overrides
    listed = business(w.client.get("/cases", params={"interface_id": interface["id"]}))
    assert len(listed) == 1 and listed[0]["request_overrides"] == overrides
    reset = business(w.client.put(f"/cases/{case['id']}", json={
        "name": case["name"], "interface_id": interface["id"], "expected_status": 200,
        "request_overrides": None,
    }))
    assert reset["request_overrides"] is None
    assert business(w.client.get(f"/interfaces/{interface['id']}")) == interface


def test_case_filter_preserves_project_isolation(core_workspace):
    w = core_workspace
    first = w.case()
    second = w.case()
    foreign = w.foreign()
    foreign_case = w.case(client=foreign)
    assert {row["id"] for row in business(w.client.get("/cases"))} == {first["id"], second["id"]}
    rows = business(w.client.get("/cases", params={"interface_id": first["interface_id"]}))
    assert [row["id"] for row in rows] == [first["id"]]
    assert business(w.client.get("/cases", params={"interface_id": foreign_case["interface_id"]})) == []
    for invalid, status in ((0, 400), (-1, 400), ("invalid", 422)):
        business(w.client.get("/cases", params={"interface_id": invalid}), status)


def test_scenario_uses_independent_requests_and_inherited_defaults(core_workspace):
    w = core_workspace
    interface, env = configured_interface(w), w.environment()
    legacy = w.case(interface=interface)
    independent = w.case(interface=interface, request_overrides={
        "path_params": {"endpoint": "live"}, "headers": {"X-Config": "case"},
        "params": {"marker": "${marker}"}, "body": None,
    })
    partial = w.case(interface=interface, request_overrides={"params": {}})
    cases = [legacy, independent, partial]
    scenario = w.scenario([case["id"] for case in cases])
    result = business(w.client.post(f"/scenarios/{scenario['id']}/run", params={"env_id": env["id"]}))
    assert [row["case_id"] for row in result] == [case["id"] for case in cases]
    assert [row["case_name"] for row in result] == [case["name"] for case in cases]
    assert all(row["passed"] is True for row in result)
    page = w.reports(scenario=True)
    assert page["total"] == 1 and w.reports()["total"] == 0
    report = business(w.client.get(f"/reports/scenarios/{page['items'][0]['id']}"))
    steps = report["steps"]
    assert [row["case_id"] for row in steps] == [case["id"] for case in cases]
    expected = [
        (interface["headers"], interface["params"], interface["body"]),
        ({"X-Config": "case"}, {"marker": "from_env"}, None),
        (interface["headers"], {}, interface["body"]),
    ]
    for step, (headers, params, body) in zip(steps, expected):
        request = step["request_detail"]
        assert urlsplit(request["url"]).path == "/health/live"
        assert (request["headers"], request["params"], request["body"]) == (headers, params, body)
    assert business(w.client.get(f"/interfaces/{interface['id']}")) == interface


def test_invitation_returns_current_team_name(core_workspace):
    w = core_workspace
    outsider = w.actors["outsider"]
    path = f"/teams/{w.team_id}"
    team_name = "WhaleShop团队_" + w.name()
    business(w.owner.patch(path, json={"name": team_name}))
    invitation = business(w.owner.post(path + "/invitations", json={
        "user_id": outsider["id"], "role": "member",
    }), 201)
    assert invitation["team_id"] == w.team_id and invitation["team_name"] == team_name
    page = business(outsider["client"].get("/teams/invitations", params={"status": "pending"}))
    assert page["total"] == 1 and len(page["items"]) == 1
    assert page["items"][0]["team_name"] == team_name
    renamed = team_name + "_新名称"
    business(w.owner.patch(path, json={"name": renamed}))
    page = business(outsider["client"].get("/teams/invitations", params={"status": "pending"}))
    assert page["total"] == 1 and page["items"][0]["team_name"] == renamed
    response = business(outsider["client"].post(
        f"/teams/invitations/{invitation['id']}/respond", params={"accept": False},
    ))
    assert response["team_name"] == renamed and response["status"] == "rejected"
