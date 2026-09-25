"""Live account bootstrap belongs only to the integration-test subtree."""
import pytest


@pytest.fixture(scope="session", autouse=True)
def integration_bootstrap(ensure_test_user):
    return ensure_test_user
