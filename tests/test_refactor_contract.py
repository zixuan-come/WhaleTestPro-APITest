"""Discovery contracts for the behavior-preserving fixture move."""
import pytest


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
