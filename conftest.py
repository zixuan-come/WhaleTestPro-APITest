"""Fixture registration and collection policy; implementations are grouped by role."""
from pathlib import Path

import pytest

from common.fixtures.authentication import (
    access_token,
    auth_client,
    auth_headers,
    clear_login_rate_limit,
    client,
    disposable_token,
    ensure_test_user,
    login_data,
    reset_login_rate_limit,
)
from common.fixtures.membership import member_users, team_member_context
from common.fixtures.resources import (
    ResourceCleanupState,
    api_cleanup,
    cleanup_state,
    project_cleanup,
    project_client,
    project_headers,
    project_id,
    project_only_client,
    runner_env,
    seed_case,
    seed_interface,
    seed_named_runnable_case,
    seed_runnable_case,
    team_factory,
    team_id,
    unique_name,
)
from common.fixtures.runtime import configure_http_logging

# Keep the original root import-time log setup and fixture names for pytest.
configure_http_logging()


def pytest_collection_modifyitems(items):
    root = Path(__file__).resolve().parent
    for item in items:
        relative = item.path.relative_to(root)
        if relative.parts[0] == "tests":
            item.add_marker(pytest.mark.offline)
        elif relative.parts[0] == "testcases":
            item.add_marker(pytest.mark.integration)
