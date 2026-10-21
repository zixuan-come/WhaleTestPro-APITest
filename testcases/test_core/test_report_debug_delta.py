"""Public HTTP contracts for the 10/19–10/21 report/debug additions."""
from copy import deepcopy
import allure
import pytest
from common.core_flow import business, run_selected_cases

pytestmark = [pytest.mark.core_flow, allure.feature('报告目录和场景单步调试增量')]


def page(w, client=None, **params):
    return business((client or w.client).get('/reports/executions', params={'kind': 'all', **params}))


def make_report(w, kind):
    case, env = w.case(), w.environment()
    if kind == 'case':
        business(w.client.post(f"/cases/{case['id']}/run", params={'env_id': env['id']}))
    elif kind == 'scenario':
        scene = w.scenario([case['id']])
        business(w.client.post(f"/scenarios/{scene['id']}/run", params={'env_id': env['id']}))
    elif kind == 'suite':
        suite = w.suite(case_ids=[case['id']])
        business(w.client.post(f"/suites/{suite['id']}/run", params={'env_id': env['id']}))
    else:
        business(run_selected_cases(w.client, [case['id']], env['id']))
    rows = page(w)['items']
    assert len(rows) == 1 and rows[0]['kind'] == kind
    return rows[0], case


def folder(w, name=None):
    return business(w.client.post('/reports/folders', json={'name': name or w.name('folder_')}), 201)


def test_report_folder_create_rename_duplicate_and_delete(core_workspace):
    w = core_workspace
    a = folder(w)
    name = w.name('renamed_')
    saved = business(w.client.put(f"/reports/folders/{a['id']}", json={'name': '  ' + name + '  '}))
    assert saved == {'id': a['id'], 'name': name, 'count': 0}
    business(w.client.post('/reports/folders', json={'name': name.upper()}), 409)
    rows = business(w.client.get('/reports/folders'))
    assert rows['can_manage'] is True and rows['items'] == [saved]
    assert rows['total'] == rows['unfiled'] == 0
    business(w.client.delete(f"/reports/folders/{a['id']}"))
    assert business(w.client.get('/reports/folders'))['items'] == []


@pytest.mark.parametrize('name', ['', '   ', 'x' * 101])
def test_report_folder_name_validation(core_workspace, name):
    w = core_workspace
    business(w.client.post('/reports/folders', json={'name': name}), 422)
    assert business(w.client.get('/reports/folders'))['items'] == []


@pytest.mark.parametrize('kind', ['case', 'scenario', 'suite', 'regression'])
def test_report_move_between_folders_and_folder_delete_preserves_evidence(core_workspace, kind):
    w = core_workspace
    entry, _ = make_report(w, kind)
    a, b = folder(w), folder(w)
    ref = entry['id']
    evidence = business(w.client.get('/reports/executions/' + ref))
    for target in (a, b):
        result = business(w.client.post('/reports/executions/move', json={'report_ids': [ref, ref], 'folder_id': target['id']}))
        assert result == {'moved': 1, 'folder_id': target['id']}
        assert [row['id'] for row in page(w, folder_id=target['id'])['items']] == [ref]
        assert page(w, folder_id=0)['total'] == 0
    assert page(w, folder_id=a['id'])['total'] == 0
    removed = business(w.client.delete(f"/reports/folders/{b['id']}"))
    assert removed['unfiled'] == 1
    assert [row['id'] for row in page(w, folder_id=0)['items']] == [ref]
    assert business(w.client.get('/reports/executions/' + ref))['detail'] == evidence['detail']


@pytest.mark.parametrize('kind', ['case', 'scenario', 'suite', 'regression'])
@pytest.mark.parametrize('mode', ['single', 'batch'])
def test_report_delete_removes_derived_evidence_preserves_cases(core_workspace, kind, mode):
    w = core_workspace
    entry, case = make_report(w, kind)
    detail = business(w.client.get('/reports/executions/' + entry['id']))
    refs = [entry['id'], *[child['id'] for child in detail['children']]]
    result = business(w.client.delete('/reports/executions/' + entry['id']) if mode == 'single' else
                      w.client.post('/reports/executions/delete', json={'report_ids': [entry['id']]}))
    assert result['deleted'] == 1 and page(w)['total'] == 0
    assert w.reports()['total'] == w.reports(scenario=True)['total'] == 0
    for reference in refs:
        business(w.client.get('/reports/executions/' + reference), 404)
    assert business(w.client.get(f"/cases/{case['id']}"))['id'] == case['id']


def test_report_selection_is_atomic_and_project_scoped(core_workspace):
    w = core_workspace
    entry, _ = make_report(w, 'case')
    target = folder(w)
    ref = entry['id']
    for path in ['/reports/executions/move', '/reports/executions/delete']:
        payload = {'report_ids': [ref, 'run-999999999']}
        if path.endswith('move'): payload['folder_id'] = target['id']
        business(w.client.post(path, json=payload), 404)
        assert page(w, folder_id=0)['total'] == 1
        assert business(w.client.get('/reports/executions/' + ref))['id'] == ref
        business(w.foreign().post(path, json=payload), 404)
    business(w.foreign().put(f"/reports/folders/{target['id']}", json={'name': 'foreign'}), 404)
    business(w.foreign().delete(f"/reports/folders/{target['id']}"), 404)
    business(w.foreign().get('/reports/executions', params={'kind': 'all', 'folder_id': target['id']}), 404)
    business(w.client.post('/reports/executions/delete', json={'report_ids': []}), 422)


def test_report_write_permission_toggle(core_workspace):
    w = core_workspace
    member = w.scoped(w.project_id, 'member')
    assert business(member.get('/reports/folders'))['can_manage'] is False
    business(member.post('/reports/folders', json={'name': w.name()}), 403)
    business(w.owner.put(f'/teams/{w.team_id}/permissions', json={'role': 'member', 'permission': 'report.write', 'enabled': True}))
    created = business(member.post('/reports/folders', json={'name': w.name()}), 201)
    assert business(member.get('/reports/folders'))['can_manage'] is True
    business(member.delete(f"/reports/folders/{created['id']}"))
    business(w.owner.put(f'/teams/{w.team_id}/permissions', json={'role': 'member', 'permission': 'report.write', 'enabled': False}))
    business(member.post('/reports/executions/delete', json={'report_ids': ['run-1']}), 403)


def debug_assets(w):
    case = w.case()
    scene, env = w.scenario([case['id']]), w.environment()
    step = deepcopy(scene['steps'][0])
    return scene, env, step


def test_step_debug_and_cached_extraction_do_not_save_assets_or_reports(core_workspace):
    w = core_workspace
    scene, env, step = debug_assets(w)
    before = business(w.client.get(f"/scenarios/{scene['id']}"))
    step['name'] = 'temporary step'
    path = f"/scenarios/{scene['id']}/debug"
    result = business(w.client.post(path, params={'env_id': env['id']}, json={'step': step}))
    assert result['passed'] is True and result['actual_status'] == 200
    assert result['response_detail']['body']['data']['status'] == 'alive'
    assert result['response_id'] and result['session_id']
    checked = business(w.client.post(path + '/extract', params={'env_id': env['id']}, json={
        'session_id': result['session_id'], 'response_id': result['response_id'], 'extract_rules': {'health': '$.data.status'}}))
    assert checked['passed'] is True and checked['variables']['health'] == 'alive'
    assert checked['extraction'] == [{'name': 'health', 'path': '$.data.status', 'passed': True, 'value': 'alive'}]
    assert business(w.client.get(f"/scenarios/{scene['id']}")) == before
    assert page(w)['total'] == w.reports()['total'] == w.reports(scenario=True)['total'] == 0


@pytest.mark.parametrize('failure', ['missing_variable', 'wrong_status'])
def test_failed_step_debug_keeps_response_or_explains_missing_input(core_workspace, failure):
    w = core_workspace
    scene, env, step = debug_assets(w)
    if failure == 'missing_variable': step['params'] = {'marker': '${not_provided}'}
    else: step['expected_status'] = 201
    result = business(w.client.post(f"/scenarios/{scene['id']}/debug", params={'env_id': env['id']}, json={'step': step}))
    assert result['passed'] is False
    if failure == 'missing_variable':
        assert result['missing_variables'] == ['not_provided'] and result['response_detail'] is None
    else:
        assert result['actual_status'] == 200 and result['response_detail']['body']['data']['status'] == 'alive'
    assert page(w)['total'] == 0


def test_debug_requires_environment_and_rejects_foreign_scope(core_workspace):
    w = core_workspace
    scene, env, step = debug_assets(w)
    path = f"/scenarios/{scene['id']}/debug"
    business(w.client.post(path, json={'step': step}), 422)
    foreign_env = w.environment(client=w.foreign())
    business(w.client.post(path, params={'env_id': foreign_env['id']}, json={'step': step}), 404)
    business(w.foreign().post(path, params={'env_id': env['id']}, json={'step': step}), 404)
    business(w.client.post(path + '/extract', params={'env_id': env['id']}, json={
        'session_id': 'f' * 32, 'response_id': 'e' * 32, 'extract_rules': {}}), 409)
    assert page(w)['total'] == 0


@pytest.mark.parametrize('expected,passed', [(False, False), (0, True)])
def test_case_json_assertion_type_contract(core_workspace, expected, passed):
    w = core_workspace
    case = w.case(assertions=[{'type': 'json_eq', 'path': '$.code', 'expected': expected}])
    result = business(w.client.post(f"/cases/{case['id']}/run", params={'env_id': w.environment()['id']}))
    assert result['passed'] is passed and result['assertions'][0]['passed'] is passed
