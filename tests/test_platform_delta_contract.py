"""Run the new HTTP scripts on current routes, SQLite and controlled downstream."""
import pytest
from common.core_flow import CoreWorkspace
from tests.test_core_flow_contract import isolated_core_api
from testcases.test_core import test_platform_delta as delta

CHECKS = [
    *[('test_execution_report_categories_and_children', {'kind': kind}, 1 if kind == 'case' else 2)
      for kind in ('case', 'scenario', 'suite', 'regression')],
    *[('test_report_filter_validation', {'params': params, 'status': status}, 0) for params, status in (
        ({'kind': 'unknown'}, 422), ({'page': 0}, 422), ({'page_size': 101}, 422),
        ({'status': 'unknown'}, 422), ({'date_from': '2026-10-19', 'date_to': '2026-10-18'}, 400))],
    *[('test_regression_preview_is_read_only_and_stale_config_is_rejected', {'mode': mode}, 0)
      for mode in ('case', 'suite')],
    ('test_project_notification_status_permissions_and_clear', {}, 0),
    ('test_notification_rejects_invalid_destination_without_sending', {}, 0),
    ('test_debug_capture_lifecycle_and_filtered_records', {}, 2),
    ('test_debug_replay_requires_environment_and_replacement_for_masked_auth', {}, 2),
    ('test_perf_history_scope_and_member_write_permission', {}, 0),
    ('test_selected_suite_regression_keeps_report_when_notification_unconfigured', {}, 2),
]


@pytest.mark.parametrize('name,args,expected_calls', CHECKS,
                         ids=[f'{i:02d}_{name}' for i,(name,_,_) in enumerate(CHECKS,1)])
def test_platform_delta_against_actual_routes(isolated_core_api, monkeypatch, name, args, expected_calls):
    from app.services import project_notification
    attempted = []
    def forbidden_delivery(*args, **kwargs):
        attempted.append(True)
        raise AssertionError('本批不允许向Webhook发送消息')
    monkeypatch.setattr(project_notification, 'send_feishu', forbidden_delivery)
    actors,calls,database=isolated_core_api
    workspace=CoreWorkspace(actors,'http://isolated.invalid','http://runner.invalid')
    try:
        workspace.initialize()
        if name == 'test_debug_replay_requires_environment_and_replacement_for_masked_auth':
            args = {**args, 'core_replay_target': 'http://runner.invalid'}
        getattr(delta,name)(workspace,**args)
        assert len(calls)==expected_calls
        assert not attempted
    finally:workspace.close()
    from app.models.execution_report import ExecutionReport
    from app.models.project_notification import ProjectNotification
    from app.models.traffic_record import TrafficRecord
    from app.models.traffic_capture import TrafficCapture
    assert all(database.query(model).count()==0 for model in (ExecutionReport,ProjectNotification,TrafficRecord,TrafficCapture))
