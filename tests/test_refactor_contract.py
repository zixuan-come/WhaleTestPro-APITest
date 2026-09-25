"""Discovery and import contracts for the behavior-preserving fixture moves."""
import ast
from pathlib import Path

import pytest

from common.perf_flow import stop_and_delete, task_payload


@pytest.mark.parametrize("name,scope,dependencies", [
    ("login_data", "session", ("client", "ensure_test_user")),
    ("team_factory", "session", ("auth_client", "cleanup_state")),
    ("project_id", "session", ("auth_client", "team_id", "cleanup_state")),
    ("team_member_context", "function", ("auth_client", "member_users", "unique_name", "team_factory")),
    ("api_cleanup", "function", ("project_client", "cleanup_state")),
])
def test_fixture_names_scopes_and_dependencies_remain_registered(request, name, scope, dependencies):
    definitions = request._fixturemanager.getfixturedefs(name, request.node)
    assert definitions, f"Root fixture was lost: {name}"
    fixture = definitions[-1]
    assert fixture.scope == scope
    assert fixture.argnames == dependencies


def test_legacy_perf_exports_remain_compatible():
    from testcases.test_perf import test_perf
    assert test_perf._payload is task_payload
    assert test_perf._stop_and_delete is stop_and_delete


@pytest.mark.parametrize("relative", [
    "common/perf_flow.py", "testcases/test_perf_core/conftest.py",
    "testcases/test_perf_core/test_perf_core.py",
])
def test_shared_perf_helpers_do_not_import_legacy_testcase_module(relative):
    root = Path(__file__).resolve().parents[1]
    tree = ast.parse((root / relative).read_text(encoding="utf-8"))
    modules = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not any(module and module.startswith("testcases.test_perf.") for module in modules)
