"""Independent core regression; collection has no live-service side effects."""
import os

import pytest

from common.core_flow import CoreWorkspace, bootstrap_core_actors
from config import BASE_URL, RUNNER_BASE_URL


@pytest.fixture(scope="session", autouse=True)
def integration_bootstrap():
    # Override the parent subtree's bootstrap only for test_core. In particular,
    # do not depend on ensure_test_user/reset_login_rate_limit/member_users.
    return None


@pytest.fixture(scope="session")
def core_actors():
    if os.environ.get("WHALE_CORE_ALLOW_WRITES") != "1":
        pytest.skip("核心 HTTP 回归会创建测试资产；仅隔离环境设置 WHALE_CORE_ALLOW_WRITES=1")
    return bootstrap_core_actors(BASE_URL)


@pytest.fixture
def core_workspace(core_actors):
    workspace = CoreWorkspace(core_actors, BASE_URL, RUNNER_BASE_URL)
    try:
        yield workspace.initialize()
    finally:
        workspace.close()
