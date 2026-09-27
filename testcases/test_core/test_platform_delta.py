"""10/18 public HTTP delta. Only owned assets; never sends a real notification."""
import json
import allure
import pytest
from common.core_flow import business

pytestmark = [pytest.mark.core_flow, allure.feature('执行报告、回归、通知和流量增量')]


@pytest.mark.parametrize('kind', ['case', 'scenario', 'suite', 'regression'])
def test_execution_report_categories_and_children(core_workspace, kind):
    w = core_workspace
    env = w.environment()
    cases = [w.case(), w.case()]
    if kind == 'case':
        business(w.client.post(f"/cases/{cases[0]['id']}/run", params={'env_id': env['id']}))
    elif kind == 'scenario':
        scenario = w.scenario([row['id'] for row in cases])
        business(w.client.post(f"/scenarios/{scenario['id']}/run", params={'env_id': env['id']}))
    elif kind == 'suite':
        suite = w.suite(case_ids=[row['id'] for row in cases])
        business(w.client.post(f"/suites/{suite['id']}/run", params={'env_id': env['id']}))
    else:
        selection = {'mode': 'case', 'ids': [row['id'] for row in cases], 'env_id': env['id']}
        preview = business(w.client.post('/regression/preview', json=selection))
        result = business(w.client.post('/regression/run', json={**selection, 'preview_key': preview['preview_key']}))
        assert result['total'] == 2 and result['passed_count'] == 2
    page = business(w.client.get('/reports/executions', params={'kind': kind, 'page_size': 1, 'status': 'passed'}))
    assert page['total'] == page['passed_count'] == 1 and page['failed_count'] == 0
    assert page['total_pages'] == 1 and page['pass_rate'] == 1
    entry = page['items'][0]
    detail = business(w.client.get(f"/reports/executions/{entry['id']}"))
    assert detail['kind'] == kind and detail['passed'] is True
    assert len(detail['children']) == (2 if kind in {'suite', 'regression'} else 0)
    if kind == 'scenario':
        assert len(detail['detail']['steps']) == 2
        assert [row['case_name'] for row in detail['detail']['steps']] == [row['name'] for row in cases]
    assert all(child['kind'] == 'case' and child['passed'] for child in detail['children'])
    business(w.foreign().get(f"/reports/executions/{entry['id']}"), 404)
    failed = business(w.client.get('/reports/executions', params={'kind': kind, 'status': 'failed'}))
    assert failed['items'] == []


@pytest.mark.parametrize('params,status', [
    ({'kind': 'unknown'}, 422), ({'page': 0}, 422), ({'page_size': 101}, 422),
    ({'status': 'unknown'}, 422), ({'date_from': '2026-10-19', 'date_to': '2026-10-18'}, 400),
])
def test_report_filter_validation(core_workspace, params, status):
    business(core_workspace.client.get('/reports/executions', params=params), status)


@pytest.mark.parametrize('mode', ['case', 'suite'])
def test_regression_preview_is_read_only_and_stale_config_is_rejected(core_workspace, mode):
    w = core_workspace
    env = w.environment(); case = w.case()
    item = w.suite(case_ids=[case['id']]) if mode == 'suite' else case
    selection = {'mode': mode, 'ids': [item['id']], 'env_id': env['id']}
    before = business(w.client.get('/reports/executions', params={'kind': 'regression'}))['total']
    options = business(w.client.get('/regression/options'))
    assert any(row['id'] == item['id'] for row in options['suites' if mode == 'suite' else 'cases'])
    preview = business(w.client.post('/regression/preview', json=selection))
    assert preview['ready'] is True and len(preview['preview_key']) == 64
    assert business(w.client.get('/reports/executions', params={'kind': 'regression'}))['total'] == before
    business(w.client.put(f"/cases/{case['id']}", json={**case, 'name': w.name('changed_')}))
    business(w.client.post('/regression/run', json={**selection, 'preview_key': preview['preview_key']}), 409)
    assert business(w.client.get('/reports/executions', params={'kind': 'regression'}))['total'] == before
    business(w.client.post('/regression/preview', json={**selection, 'ids': []}), 422)


def test_project_notification_status_permissions_and_clear(core_workspace):
    w = core_workspace
    path = f'/projects/{w.project_id}/notifications'
    initial = business(w.owner.get(path))
    assert initial == {'enabled': False, 'configured': False, 'signing_configured': False, 'can_manage': True}
    # Unconfigured test must reject before contacting any webhook.
    business(w.owner.post(path + '/test'), 400)
    webhook = 'https://open.feishu.cn/open-apis/bot/v2/hook/11111111-2222-3333-4444-555555555555'
    secret = 'synthetic-not-a-live-signing-secret'
    response = w.owner.put(path, json={'enabled': False, 'webhook_url': webhook, 'signing_secret': secret})
    saved = business(response)
    assert saved['configured'] is True and saved['signing_configured'] is True and saved['enabled'] is False
    assert webhook not in response.text and secret not in response.text
    member = business(w.actors['member']['client'].get(path))
    assert member['can_manage'] is False and member['configured'] is True
    business(w.actors['member']['client'].put(path, json={'enabled': False, 'clear_webhook': True}), 403)
    business(w.actors['outsider']['client'].get(path), 404)
    cleared = business(w.owner.put(path, json={'enabled': False, 'clear_webhook': True, 'clear_signing_secret': True}))
    assert not cleared['configured'] and not cleared['signing_configured']


def test_notification_rejects_invalid_destination_without_sending(core_workspace):
    w = core_workspace
    business(w.owner.put(f'/projects/{w.project_id}/notifications', json={
        'enabled': True, 'webhook_url': 'https://invalid.example/hook',
    }), 422)


def test_debug_capture_lifecycle_and_filtered_records(core_workspace):
    w = core_workspace
    env = w.environment(); interface = w.interface()
    assert business(w.client.get('/traffic/capture'))['active'] is False
    capture = business(w.client.post('/traffic/capture/start'))
    assert capture['active'] is True and capture['count'] == 0 and capture['limit'] == 1000
    assert business(w.client.post('/traffic/capture/start'))['capture_id'] == capture['capture_id']
    assert business(w.scoped(w.project_id, 'member').get('/traffic/capture'))['active'] is False
    business(w.client.post(f"/interfaces/{interface['id']}/run", params={'env_id': env['id']}))
    records = business(w.client.get('/traffic/records', params={'capture_id': capture['capture_id'], 'limit': 1}))
    assert len(records) == 1
    row = records[0]
    assert row['source'] == 'debug' and row['interface_name'] == interface['name']
    assert row['response_status'] == 200 and row['path'] == '/health/live'
    assert business(w.client.get('/traffic/capture'))['count'] == 1
    stopped = business(w.client.post('/traffic/capture/stop'))
    assert stopped['active'] is False and stopped['count'] == 1
    business(w.client.post(f"/interfaces/{interface['id']}/run", params={'env_id': env['id']}))
    assert business(w.client.get('/traffic/capture'))['count'] == 1
    restarted = business(w.client.post('/traffic/capture/start'))
    assert restarted['capture_id'] != capture['capture_id'] and restarted['count'] == 0
    assert business(w.client.get('/traffic/records', params={'capture_id': capture['capture_id'], 'offset': 1})) == []
    business(w.foreign().get(f"/traffic/records/{row['id']}"), 404)
    business(w.client.post('/traffic/capture/stop'))


def test_debug_replay_requires_environment_and_replacement_for_masked_auth(core_workspace, core_replay_target):
    w = core_workspace
    # Replay sends X-Shadow; platform management/health paths intentionally
    # reject that hint. Use the dedicated external synthetic target instead.
    env = w.create('/environments', {'name': w.name('replay_env_'), 'base_url': core_replay_target})
    interface = w.interface(path='/health')
    business(w.client.put(f"/interfaces/{interface['id']}", json={**interface, 'headers': {'Authorization': 'Bearer synthetic-original'}}))
    capture = business(w.client.post('/traffic/capture/start'))
    business(w.client.post(f"/interfaces/{interface['id']}/run", params={'env_id': env['id']}))
    business(w.client.post('/traffic/capture/stop'))
    row = business(w.client.get('/traffic/records', params={'capture_id': capture['capture_id']}))[0]
    assert 'synthetic-original' not in json.dumps(row) and '***' in json.dumps(row['request_headers'])
    business(w.client.post(f"/traffic/replay/{row['id']}", json={}), 400)
    business(w.client.post(f"/traffic/replay/{row['id']}", json={'env_id': env['id']}), 400)
    result = business(w.client.post(f"/traffic/replay/{row['id']}", json={
        'env_id': env['id'], 'headers': {'Authorization': 'Bearer synthetic-replacement'}, 'params': {}, 'body': None,
    }))
    assert result['replayed_status'] == 200 and result['diff']['same'] is True
    assert 'synthetic-replacement' not in json.dumps(result)
    business(w.foreign().post(f"/traffic/replay/{row['id']}", json={'env_id': env['id']}), 404)


def test_perf_history_scope_and_member_write_permission(core_workspace):
    w = core_workspace
    task = w.create('/perf/tasks', {'name': w.name('perf_scope_'), 'target_host': w.runner_url,
        'target_path': '/health/live', 'users': 1, 'spawn_rate': 1, 'duration': 4})
    path = f"/perf/tasks/{task['id']}/runs"
    assert business(w.scoped(w.project_id, 'member').get(path)) == {'total': 0, 'items': []}
    business(w.scoped(w.project_id, 'member').post(path + '/clear', json={'all_finished': True}), 403)
    business(w.scoped(w.project_id, 'outsider').get(path), 404)
    business(w.foreign().get(path), 404)
    business(w.foreign().post(path + '/clear', json={'all_finished': True}), 404)


def test_selected_suite_regression_keeps_report_when_notification_unconfigured(core_workspace):
    w = core_workspace
    env = w.environment(); cases = [w.case(), w.case()]
    suite = w.suite(case_ids=[row['id'] for row in cases])
    selection = {'mode': 'suite', 'ids': [suite['id'], suite['id']], 'env_id': env['id']}
    preview = business(w.client.post('/regression/preview', json=selection))
    assert preview['ready'] is True and preview['suite_count'] == 1
    result = business(w.client.post('/regression/run', json={**selection, 'preview_key': preview['preview_key'], 'notify': True}))
    assert result['passed'] is True and result['total'] == result['passed_count'] == 2
    assert len(result['results']) == 1 and result['results'][0]['name'] == suite['name']
    assert result['notification_warning']  # Fresh project: no credentials, no delivery attempt.
    report = business(w.client.get(f"/reports/executions/{result['report_id']}"))
    assert report['kind'] == 'regression' and report['passed'] is True
    assert len(report['children']) == 1 and report['children'][0]['kind'] == 'suite'
    child = business(w.client.get(f"/reports/executions/{report['children'][0]['id']}"))
    assert len(child['children']) == 2
