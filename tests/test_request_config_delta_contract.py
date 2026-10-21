"""Run only the 10/17 HTTP scripts through real routes and isolated SQLite."""
import pytest

from common.core_flow import CoreWorkspace, business
from tests.test_core_flow_contract import isolated_core_api  # noqa: F401; shared isolated fixture
from testcases.test_core import test_request_config_delta as delta


CHECKS = [
    ("test_path_defaults_roundtrip", {}, 0),
    *[("test_debug_configuration_is_temporary", {"mode": mode}, 1)
      for mode in ("no_body", "null_body", "temporary", "legacy_path")],
    *[("test_invalid_path_value_returns_failed_debug", {"value": value}, 0)
      for value in (None, "", "..")],
    *[("test_invalid_request_configuration_is_rejected", {"target": target, "payload": payload}, 0)
      for target, payload in (
          ("interface", {"path_params": {"endpoint": []}}),
          ("debug", {"request_overrides": {"url": "/other"}}),
          ("case", {"request_overrides": {"method": "POST"}}),
          ("case", {"request_overrides": {"path_params": {"endpoint": {"nested": 1}}}}),
      )],
    ("test_case_overrides_roundtrip_and_reset", {}, 0),
    ("test_case_filter_preserves_project_isolation", {}, 0),
    ("test_scenario_uses_independent_requests_and_inherited_defaults", {}, 3),
    ("test_invitation_returns_current_team_name", {}, 0),
]


@pytest.mark.parametrize("name,parameters,expected_calls", CHECKS,
                         ids=[f"{index + 1:02d}_{name.removeprefix('test_')}"
                              for index, (name, _, _) in enumerate(CHECKS)])
def test_delta_script_against_actual_routes(isolated_core_api, monkeypatch, name, parameters, expected_calls):
    actors, calls, database = isolated_core_api
    from app.services import execution
    downstream = execution.requests.request
    observed = []

    def capture(method, url, **kwargs):
        observed.append({"method": method, "url": url, "headers": kwargs.get("headers"),
                         "params": kwargs.get("params"), "body": kwargs.get("json")})
        return downstream(method, url, **kwargs)

    monkeypatch.setattr(execution.requests, "request", capture)
    workspace = CoreWorkspace(actors, "http://isolated.invalid", "http://runner.invalid")
    try:
        workspace.initialize()
        getattr(delta, name)(workspace, **parameters)
        assert len(calls) == expected_calls
        if name == "test_scenario_uses_independent_requests_and_inherited_defaults":
            report_id = workspace.reports(scenario=True)["items"][0]["id"]
            report = business(workspace.client.get(f"/reports/scenarios/{report_id}"))
            assert [step["request_detail"] for step in report["steps"]] == observed
    finally:
        workspace.close()
    from app.models.project import Project
    from app.models.team import Team
    from app.models.report import TestReport as Report
    from app.models.scenario_report import ScenarioReport
    assert all(database.query(model).count() == 0 for model in (Team, Project, Report, ScenarioReport))
