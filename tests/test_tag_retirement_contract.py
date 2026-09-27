import pytest

from common.core_flow import CoreWorkspace
from tests.test_core_flow_contract import isolated_core_api
from testcases.test_core.test_tag_retirement import test_removed_tag_fields_are_rejected as check_removed_fields


@pytest.mark.parametrize("resource", ["case", "suite", "schedule"])
def test_retired_tag_http_scripts_against_current_routes(isolated_core_api, resource):
    actors, calls, _ = isolated_core_api
    workspace = CoreWorkspace(actors, "http://isolated.invalid", "http://runner.invalid")
    try:
        workspace.initialize()
        check_removed_fields(workspace, resource)
        assert not calls
    finally:
        workspace.close()
