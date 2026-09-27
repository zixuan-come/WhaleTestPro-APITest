"""Core black-box regression against the 2026-10-10 implementation baseline."""
from urllib.parse import parse_qs, urlsplit

import allure
import pytest

from common.core_flow import business, design_cases, run_selected_cases
from common.request_util import RequestUtil

pytestmark = [pytest.mark.core_flow, allure.feature("核心链路回归")]


def run_case(w, case, env, client=None):
    return business((client or w.client).post(
        f"/cases/{case['id']}/run", params={"env_id": env["id"]},
    ))


def suite_report(w, suite_id):
    rows = [r for r in w.reports()["items"] if
            isinstance(r["detail"], dict) and r["detail"].get("suite_id") == suite_id]
    assert len(rows) == 1
    return business(w.client.get(f"/reports/{rows[0]['id']}"))


@pytest.mark.smoke
@design_cases("WTP-API-024-P001")
def test_interface_trial_does_not_create_reports(core_workspace):
    w = core_workspace
    interface, env = w.interface(), w.environment()
    result = business(w.client.post(
        f"/interfaces/{interface['id']}/run", params={"env_id": env["id"]},
    ))
    assert result["interface_id"] == interface["id"]
    assert result["passed"] is True and result["response"]["status_code"] == 200
    assert result["request"]["url"].endswith("/health/live")
    assert result["duration_ms"] >= 0 and w.reports()["total"] == 0


@pytest.mark.smoke
@design_cases("WTP-API-031-P001", "WTP-API-051-P001")
def test_case_execution_persists_matching_report(core_workspace):
    w = core_workspace
    case, env = w.case(), w.environment()
    result = run_case(w, case, env)
    assert result["passed"] is True and result["attempts"] == 1
    assert result["expected_status"] == result["actual_status"] == 200
    page = w.reports()
    assert page["total"] == page["passed_count"] == 1 and page["failed_count"] == 0
    report = business(w.scoped(w.project_id, "member").get(f"/reports/{page['items'][0]['id']}"))
    assert report["case_id"] == case["id"] and report["case_name"] == case["name"]
    assert report["passed"] is True and report["detail"] == result


@design_cases("WTP-API-031-B001")
def test_deleted_case_returns_business_error_without_report(core_workspace):
    w = core_workspace
    case, env = w.case(), w.environment()
    assert business(w.client.delete(f"/cases/{case['id']}")) is None
    assert run_case(w, case, env) == {"error": "用例不存在"}
    assert w.reports()["total"] == 0


@design_cases("WTP-API-031-N002")
def test_missing_template_variable_persists_failed_report(core_workspace):
    w = core_workspace
    case = w.case(interface=w.interface("/health/live?x=${missing_key}"))
    result = run_case(w, case, w.environment())
    assert result["passed"] is False and result["attempts"] == 1
    assert "missing_key" in result["error"]
    page = w.reports()
    assert page["total"] == page["failed_count"] == 1
    assert page["items"][0]["detail"] == result


@design_cases("WTP-API-031-N001")
def test_case_rejects_foreign_environment_without_report(core_workspace):
    w = core_workspace
    case, env = w.case(), w.environment(w.foreign())
    business(w.client.post(f"/cases/{case['id']}/run", params={"env_id": env["id"]}), 404)
    assert w.reports()["total"] == w.reports(client=w.foreign())["total"] == 0


@design_cases("WTP-API-027-P001")
def test_chain_shares_extracted_variable_in_order(core_workspace):
    w = core_workspace
    first = w.case(extract_rules={"marker": "$.data.status"})
    second = w.case(interface=w.interface("/health/live?marker=${marker}"))
    env = w.environment()
    result = business(w.client.post("/cases/chain", json=[first["id"], second["id"]],
                                    params={"env_id": env["id"]}))
    assert [row["case_id"] for row in result] == [first["id"], second["id"]]
    assert all(row["passed"] is True for row in result)
    reports = w.reports()
    assert reports["total"] == 2
    steps = {r["case_id"]: r["detail"]["step"] for r in reports["items"]}
    assert steps[first["id"]]["extracted_variables"] == {"marker": "alive"}
    assert parse_qs(urlsplit(steps[second["id"]]["request_detail"]["url"]).query)["marker"] == ["alive"]


@design_cases("WTP-API-027-B001")
def test_empty_chain_creates_no_report(core_workspace):
    w = core_workspace
    env = w.environment()
    assert business(w.client.post("/cases/chain", json=[], params={"env_id": env["id"]})) == []
    assert w.reports()["total"] == w.reports(scenario=True)["total"] == 0


@design_cases("WTP-API-027-N001")
def test_chain_rejects_wrapped_body_without_reports(core_workspace):
    w = core_workspace
    case, env = w.case(), w.environment()
    business(w.client.post("/cases/chain", json={"case_ids": [case["id"]]},
                           params={"env_id": env["id"]}), 422)
    assert w.reports()["total"] == 0


@design_cases("WTP-API-027-X004")
def test_chain_failure_does_not_block_later_case(core_workspace):
    w = core_workspace
    first, second = w.case(expected_status=201), w.case()
    env = w.environment()
    result = business(w.client.post("/cases/chain", json=[first["id"], second["id"]],
                                    params={"env_id": env["id"]}))
    assert [r["case_id"] for r in result] == [first["id"], second["id"]]
    assert [r["passed"] for r in result] == [False, True]
    page = w.reports()
    assert page["total"] == 2 and page["passed_count"] == page["failed_count"] == 1


@pytest.mark.smoke
@design_cases("WTP-API-037-P001", "WTP-API-050-P001")
def test_scenario_report_preserves_order_and_evidence(core_workspace):
    w = core_workspace
    cases = [w.case(), w.case()]
    ids = [c["id"] for c in cases]
    scenario, env = w.scenario(ids), w.environment()
    result = business(w.client.post(f"/scenarios/{scenario['id']}/run", params={"env_id": env["id"]}))
    assert [r["case_id"] for r in result] == ids and all(r["passed"] for r in result)
    page = w.reports(scenario=True)
    assert page["total"] == 1 and w.reports()["total"] == 0
    report = business(w.scoped(w.project_id, "member").get(f"/reports/scenarios/{page['items'][0]['id']}"))
    assert report["scenario_id"] == scenario["id"] and report["scenario_name"] == scenario["name"]
    assert report["passed"] is True and report["total_steps"] == report["passed_steps"] == 2
    assert report["failed_steps"] == 0
    assert [step["sequence"] for step in report["steps"]] == [1, 2]
    assert [step["case_id"] for step in report["steps"]] == ids
    for step in report["steps"]:
        assert step["passed"] is True and step["response_detail"]["status_code"] == 200
        assert step["request_detail"]["method"] == "GET" and step["duration_ms"] >= 0


@design_cases("WTP-API-037-B001")
def test_empty_scenario_is_not_a_pass(core_workspace):
    w = core_workspace
    scenario, env = w.scenario([]), w.environment()
    assert business(w.client.post(f"/scenarios/{scenario['id']}/run", params={"env_id": env["id"]})) == []
    page = w.reports(scenario=True)
    assert page["total"] == 1
    report = page["items"][0]
    assert report["passed"] is False and report["total_steps"] == report["passed_steps"] == 0


@design_cases("WTP-API-037-N001")
def test_scenario_rejects_foreign_environment_without_report(core_workspace):
    w = core_workspace
    scenario, env = w.scenario([w.case()["id"]]), w.environment(w.foreign())
    business(w.client.post(f"/scenarios/{scenario['id']}/run", params={"env_id": env["id"]}), 404)
    assert w.reports(scenario=True)["total"] == 0


@pytest.mark.smoke
@design_cases("WTP-API-052-P001")
def test_regression_reports_counts_and_ratio(core_workspace):
    w = core_workspace
    ids = [w.case()["id"], w.case()["id"]]
    env = w.environment()
    result = business(run_selected_cases(w.client, ids, env['id']))
    assert result["passed"] is True and result['report_id']
    assert result["total"] == result["passed_count"] == 2 and result["failed_count"] == 0
    assert result["pass_rate"] == result["interface_coverage"] == 1
    assert result["interface_total"] == result["interface_covered"] == 2
    assert [r["id"] for r in result["results"]] == ids
    assert w.reports()["total"] == 2


@design_cases("WTP-API-052-B001")
def test_explicit_empty_regression_does_not_select_all_cases(core_workspace):
    w = core_workspace
    w.case()  # There is a runnable case; [] must not mean "run all".
    env = w.environment()
    business(w.client.post('/regression/preview', json={'mode':'case','ids':[], 'env_id':env['id']}), 422)
    assert w.reports()["total"] == 0


@design_cases("WTP-API-052-N001")
def test_regression_rejects_non_integer_ids(core_workspace):
    w = core_workspace
    business(w.client.post('/regression/preview', json={'mode':'case','ids':['not-a-number']}), 422)
    assert w.reports()["total"] == 0


@design_cases("WTP-API-052-X004")
def test_regression_explicit_selection_does_not_expand_to_other_cases(core_workspace):
    w = core_workspace
    selected, ignored = w.case(), w.case()
    env = w.environment()
    result = business(run_selected_cases(w.client, [selected['id']], env['id']))
    assert result["total"] == 1 and result["passed"] is True
    assert [r["id"] for r in result["results"]] == [selected["id"]]
    assert [r["case_id"] for r in w.reports()["items"]] == [selected["id"]]
    assert ignored["id"] != selected["id"]


@design_cases("WTP-API-087-B002", "WTP-API-087-P001")
def test_suite_partial_update_preserves_bindings(core_workspace):
    w = core_workspace
    case = w.case()
    suite = w.suite(case_ids=[case["id"]], description="keep me")
    path = f"/suites/{suite['id']}"
    unchanged = business(w.client.put(path, json={}))
    for key in ("name", "type", "case_ids", "description"):
        assert unchanged[key] == suite[key]
    new_name = w.name("core_updated_")
    business(w.client.put(path, json={"name": new_name}))
    current = business(w.client.get(path))
    assert current["name"] == new_name
    for key in ("type", "case_ids", "description"):
        assert current[key] == suite[key]


@design_cases("WTP-API-087-N002", "WTP-API-087-N003")
@pytest.mark.parametrize("field", ["name", "type"])
def test_suite_null_update_is_rejected(core_workspace, field):
    w = core_workspace
    suite = w.suite(case_ids=[w.case()["id"]])
    path = f"/suites/{suite['id']}"
    business(w.client.put(path, json={field: None}), 422)
    assert business(w.client.get(path)) == suite


@pytest.mark.smoke
@design_cases("WTP-API-088-P001", "WTP-API-088-X004")
def test_mixed_suite_deduplicates_scenario_and_explicit_cases(core_workspace):
    w = core_workspace
    first, second = w.case(), w.case()
    scenario = w.scenario([first["id"]])
    suite = w.suite(type="mixed", scenario_ids=[scenario["id"]],
                    case_ids=[first["id"], second["id"], second["id"]], )
    env = w.environment()
    result = business(w.client.post(f"/suites/{suite['id']}/run", params={"env_id": env["id"]}))
    assert result["suite_id"] == suite["id"] and result["total"] == result["passed"] == 2
    assert result["failed"] == 0 and result["pass_rate"] == 100
    assert result["scenario_count"] == result["case_count"] == 1
    assert [(r["type"], r["id"]) for r in result["results"]] == [("scenario", scenario["id"]), ("case", second["id"])]
    assert w.reports(scenario=True)["total"] == 1
    page = w.reports()
    assert page["total"] == 2  # One independent case + one summary, not duplicated children.
    assert [r["case_id"] for r in page["items"] if r["case_id"] != 0] == [second["id"]]
    report = suite_report(w, suite["id"])
    assert report["passed"] is True and report["detail"] == result


@design_cases("WTP-API-088-B001")
def test_empty_suite_summary_is_failed(core_workspace):
    w = core_workspace
    suite, env = w.suite(case_ids=[], scenario_ids=[], ), w.environment()
    result = business(w.client.post(f"/suites/{suite['id']}/run", params={"env_id": env["id"]}))
    assert result["total"] == result["passed"] == result["failed"] == 0
    assert result["pass_rate"] == result["case_count"] == result["scenario_count"] == 0
    assert result["results"] == [] and w.reports()["total"] == 1
    assert suite_report(w, suite["id"])["passed"] is False


@design_cases("WTP-API-088-N001")
def test_suite_rejects_foreign_environment_before_execution(core_workspace):
    w = core_workspace
    suite, env = w.suite(case_ids=[w.case()["id"]]), w.environment(w.foreign())
    business(w.client.post(f"/suites/{suite['id']}/run", params={"env_id": env["id"]}), 404)
    assert w.reports()["total"] == w.reports(scenario=True)["total"] == 0


@design_cases("WTP-API-088-X005")
def test_suite_foreign_children_fail_without_foreign_reports(core_workspace):
    w = core_workspace
    foreign = w.foreign()
    foreign_case = w.case(client=foreign)
    foreign_scenario = w.scenario([foreign_case["id"]], foreign)
    local = w.case()
    suite = w.suite(type="mixed", scenario_ids=[foreign_scenario["id"]],
                    case_ids=[foreign_case["id"], local["id"]])
    env = w.environment()
    result = business(w.client.post(f"/suites/{suite['id']}/run", params={"env_id": env["id"]}))
    assert result["total"] == 3 and result["passed"] == 1 and result["failed"] == 2
    assert [r["passed"] for r in result["results"]] == [False, False, True]
    assert w.reports(client=foreign)["total"] == w.reports(scenario=True, client=foreign)["total"] == 0
    assert suite_report(w, suite["id"])["passed"] is False


@design_cases("WTP-API-083-N001", "WTP-API-083-X002")
@pytest.mark.parametrize("actor,status", [("anonymous", 401), ("outsider", 404)])
def test_suite_anonymous_and_outsider_are_rejected(core_workspace, actor, status):
    w = core_workspace
    w.suite()
    client = (RequestUtil(w.base_url, headers={"X-Project-Id": str(w.project_id)})
              if actor == "anonymous" else w.scoped(w.project_id, "outsider"))
    business(client.get("/suites"), status)


@design_cases("WTP-API-086-P001", "WTP-API-081-X010")
def test_member_suite_write_toggle_does_not_disable_read_or_execute(core_workspace):
    w = core_workspace
    suite, env = w.suite(case_ids=[w.case()["id"]]), w.environment()
    member = w.scoped(w.project_id, "member")
    assert business(member.get(f"/suites/{suite['id']}"))["id"] == suite["id"]
    assert business(member.post(f"/suites/{suite['id']}/run", params={"env_id": env["id"]}))["passed"] == 1
    payload = {"name": w.name(), "type": "case"}
    business(member.post("/suites", json=payload), 403)
    permission_path = f"/teams/{w.team_id}/permissions"
    business(w.owner.put(permission_path, json={"role": "member", "permission": "suite.write", "enabled": True}))
    created = business(member.post("/suites", json=payload), 201)
    assert business(member.get(f"/suites/{created['id']}"))["id"] == created["id"]
    business(w.owner.put(permission_path, json={"role": "member", "permission": "suite.write", "enabled": False}))
    business(member.post("/suites", json={"name": w.name(), "type": "case"}), 403)
    assert business(member.get(f"/suites/{suite['id']}"))["id"] == suite["id"]
    assert business(member.post(f"/suites/{suite['id']}/run", params={"env_id": env["id"]}))["passed"] == 1


@design_cases("WTP-API-085-P001", "WTP-API-085-B001")
def test_suite_delete_preserves_execution_history(core_workspace):
    w = core_workspace
    suite, env = w.suite(case_ids=[w.case()["id"]]), w.environment()
    business(w.client.post(f"/suites/{suite['id']}/run", params={"env_id": env["id"]}))
    report = suite_report(w, suite["id"])
    assert business(w.client.delete(f"/suites/{suite['id']}")) is None
    business(w.client.get(f"/suites/{suite['id']}"), 404)
    business(w.client.delete(f"/suites/{suite['id']}"), 404)
    assert business(w.client.get(f"/reports/{report['id']}")) == report


@design_cases("WTP-API-022-P001", "WTP-API-023-P001")
def test_interface_reference_migration_preserves_cases_and_scenario(core_workspace):
    w = core_workspace
    source, target = w.interface(), w.interface()
    cases = [w.case(interface=source), w.case(interface=source)]
    scenario, env = w.scenario([c["id"] for c in cases]), w.environment()
    run_case(w, cases[0], env)
    references = business(w.client.get(f"/interfaces/{source['id']}/references"))
    assert references["case_count"] == 2
    assert {row["id"] for row in references["cases"]} == {c["id"] for c in cases}
    assert all(row["scenario_ids"] == [scenario["id"]] for row in references["cases"])
    assert next(row for row in references["cases"] if row["id"] == cases[0]["id"])["last_passed"] is True
    migrated = business(w.client.post(f"/interfaces/{source['id']}/migrate", json={"target_interface_id": target["id"]}))
    assert migrated["migrated_count"] == 2
    for case in cases:
        assert business(w.client.get(f"/cases/{case['id']}"))["interface_id"] == target["id"]
    assert business(w.client.get(f"/scenarios/{scenario['id']}"))["case_ids"] == [c["id"] for c in cases]
    assert business(w.client.get(f"/interfaces/{source['id']}/references"))["case_count"] == 0
    business(w.client.delete(f"/interfaces/{source['id']}"))
    result = business(w.client.post(f"/scenarios/{scenario['id']}/run", params={"env_id": env["id"]}))
    assert all(row["passed"] for row in result)


@design_cases("WTP-API-019-N002")
def test_referenced_interface_delete_is_conflict_without_data_loss(core_workspace):
    w = core_workspace
    case = w.case()
    business(w.client.delete(f"/interfaces/{case['interface_id']}"), 409)
    assert business(w.client.get(f"/interfaces/{case['interface_id']}"))["id"] == case["interface_id"]
    assert business(w.client.get(f"/cases/{case['id']}"))["interface_id"] == case["interface_id"]
