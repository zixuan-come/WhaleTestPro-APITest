"""New HTTP scripts on actual routes and SQLite; private in-memory debug cache."""
from types import SimpleNamespace
import pytest
from common.core_flow import CoreWorkspace
from tests.test_core_flow_contract import isolated_core_api
from testcases.test_core import test_report_debug_delta as delta

CHECKS = [
    ('test_report_folder_create_rename_duplicate_and_delete', {}, 0),
    *[('test_report_folder_name_validation', {'name': name}, 0) for name in ('', '   ', 'x' * 101)],
    *[('test_report_move_between_folders_and_folder_delete_preserves_evidence', {'kind': kind}, 1)
      for kind in ('case', 'scenario', 'suite', 'regression')],
    *[('test_report_delete_removes_derived_evidence_preserves_cases', {'kind': kind, 'mode': mode}, 1)
      for kind in ('case', 'scenario', 'suite', 'regression') for mode in ('single', 'batch')],
    ('test_report_selection_is_atomic_and_project_scoped', {}, 1),
    ('test_report_write_permission_toggle', {}, 0),
    ('test_step_debug_and_cached_extraction_do_not_save_assets_or_reports', {}, 1),
    *[('test_failed_step_debug_keeps_response_or_explains_missing_input', {'failure': failure}, count)
      for failure, count in (('missing_variable', 0), ('wrong_status', 1))],
    ('test_debug_requires_environment_and_rejects_foreign_scope', {}, 0),
    *[('test_case_json_assertion_type_contract', {'expected': expected, 'passed': passed}, 1)
      for expected, passed in ((False, False), (0, True))],
]


@pytest.mark.parametrize('name,args,expected_calls', CHECKS,
    ids=[f'{i:02d}_{name}' for i, (name, _, _) in enumerate(CHECKS, 1)])
def test_report_debug_http_contract(isolated_core_api, monkeypatch, name, args, expected_calls):
    from app.services import scenario_debug
    values = {}
    cache = SimpleNamespace(
        get=lambda key: values.get(key), set=lambda key, value, **kw: values.update({key: value}),
        lock=lambda *a, **kw: SimpleNamespace(acquire=lambda **kw: True, release=lambda: None))
    monkeypatch.setattr(scenario_debug, 'redis_client', cache)
    actors, calls, database = isolated_core_api
    workspace = CoreWorkspace(actors, 'http://isolated.invalid', 'http://runner.invalid')
    try:
        workspace.initialize()
        getattr(delta, name)(workspace, **args)
        assert len(calls) == expected_calls, '提取验证或无效配置不应重发请求'
    finally:
        workspace.close()
    from app.models.report_folder import ReportFolder, ReportFolderItem
    from app.models.execution_report import ExecutionReport
    assert all(database.query(model).count() == 0 for model in (ReportFolder, ReportFolderItem, ExecutionReport))


def test_new_scripts_and_offline_parameter_variants_match():
    functions = {name: value for name, value in vars(delta).items() if name.startswith('test_') and callable(value)}
    assert set(functions) == {name for name, _, _ in CHECKS}
    for name, function in functions.items():
        count = 1
        for mark in getattr(function, 'pytestmark', []):
            if mark.name == 'parametrize': count *= len(mark.args[1])
        assert count == sum(candidate == name for candidate, _, _ in CHECKS), name
