"""Reusable performance definitions, independent run history and live TPS."""
import time
import allure
import pytest
from common.core_flow import business
from common.perf_cases import single_plan, chain_plan
from common.perf_flow import assert_transaction_metrics

pytestmark = [pytest.mark.perf_core, allure.feature('压测复用、执行历史与TPS')]


def create_task(api, target='http://fixture.invalid', mode='single'):
    config = {'name': api.name('perf_history_'), 'target_host': target, 'target_path': '/echo',
              'users': 1, 'spawn_rate': 1, 'duration': 8,
              'load_config': chain_plan() if mode == 'chain' else single_plan()}
    task = business(api.client.post('/perf/tasks', json=config), 201)
    api.tasks.append(task['id'])
    return task, config


def start(api, task):
    result = business(api.client.post(f"/perf/tasks/{task['id']}/run"))
    assert result['status'] == 'queued' and result['celery_task_id']
    assert type(result['latest_run_id']) is int and result['history_count'] > 0
    assert result['rps'] is None and result['request_stats'] is None and result['history_samples'] is None
    return result


def finish(api, task, execution):
    deadline = time.monotonic() + 90
    observed = []
    while True:
        current = business(api.client.get(f"/perf/tasks/{task['id']}"))
        assert current['celery_task_id'] == execution['celery_task_id']
        if current['status'] == 'running' and current['history_samples'] and current['request_stats']:
            observed.append(current)
            live_run = business(api.client.get(f"/perf/tasks/{task['id']}/runs/{execution['latest_run_id']}"))
            assert live_run['status'] in {'running', 'done'}
            assert live_run['result']['request_stats'] is not None
        if current['status'] in {'done', 'failed', 'cancelled'}:
            break
        assert time.monotonic() < deadline, '压测未在期限内完成'
        time.sleep(.2)
    assert current['status'] == 'done'
    assert observed, '运行中未读到实时采样，不能只验证停止后的报告'
    assert_transaction_metrics(current)
    run = business(api.client.get(f"/perf/tasks/{task['id']}/runs/{execution['latest_run_id']}"))
    assert run['status'] == 'done' and run['result']['celery_task_id'] == execution['celery_task_id']
    assert run['result']['request_stats'] == current['request_stats']
    return current


def test_edit_pending_configuration_keeps_empty_history(perf_api):
    task, config = create_task(perf_api)
    assert task['history_count'] == 0 and task['latest_run_id'] is None
    business(perf_api.client.put(f"/perf/tasks/{task['id']}", json={**config, 'users': 3, 'duration': 10}))
    current = business(perf_api.client.get(f"/perf/tasks/{task['id']}"))
    assert current['users'] == 3 and current['duration'] == 10
    assert current['load_config'] == task['load_config'] and current['status'] == 'pending'
    assert business(perf_api.client.get(f"/perf/tasks/{task['id']}/runs")) == {'total': 0, 'items': []}


@pytest.mark.parametrize('params', [{'offset': -1}, {'limit': 0}, {'limit': 101}])
def test_history_pagination_boundaries(perf_api, params):
    task,_ = create_task(perf_api)
    business(perf_api.client.get(f"/perf/tasks/{task['id']}/runs", params=params), 422)


@pytest.mark.parametrize('selection', [{}, {'run_ids': []}, {'run_ids': [0]}, {'run_ids': [1,1]}, {'run_ids': [1], 'all_finished': True}])
def test_invalid_clear_selection_does_not_modify_task(perf_api, selection):
    task,_ = create_task(perf_api)
    business(perf_api.client.post(f"/perf/tasks/{task['id']}/runs/clear", json=selection), 422)
    assert business(perf_api.client.get(f"/perf/tasks/{task['id']}"))['status'] == 'pending'


@pytest.mark.async_e2e
@pytest.mark.parametrize('mode', ['single', 'chain'])
def test_live_statistics_and_tps_before_completion(perf_api, perf_load_target, mode):
    task,_ = create_task(perf_api, perf_load_target, mode)
    finish(perf_api, task, start(perf_api, task))


@pytest.mark.async_e2e
def test_repeat_edit_snapshot_pagination_and_selective_clear(perf_api, perf_load_target):
    api = perf_api
    task,config = create_task(api, perf_load_target)
    first = start(api, task); finish(api, task, first)
    before = business(api.client.get(f"/perf/tasks/{task['id']}/runs/{first['latest_run_id']}"))
    business(api.client.put(f"/perf/tasks/{task['id']}", json={**config, 'users': 2}))
    assert business(api.client.get(f"/perf/tasks/{task['id']}/runs/{first['latest_run_id']}")) == before
    second = start(api, task)
    assert second['latest_run_id'] != first['latest_run_id'] and second['celery_task_id'] != first['celery_task_id']
    finish(api, task, second)
    pages = [business(api.client.get(f"/perf/tasks/{task['id']}/runs", params={'limit': 1, 'offset': n})) for n in (0,1)]
    assert all(page['total'] == 2 for page in pages)
    assert [page['items'][0]['id'] for page in pages] == [second['latest_run_id'], first['latest_run_id']]
    assert pages[0]['items'][0]['result']['users'] == 2 and pages[1]['items'][0]['result']['users'] == 1
    # A mixed valid/missing selection must not partially delete the valid row.
    business(api.client.post(f"/perf/tasks/{task['id']}/runs/clear", json={'run_ids': [first['latest_run_id'], 2147483647]}), 404)
    assert business(api.client.get(f"/perf/tasks/{task['id']}/runs"))['total'] == 2
    cleared = business(api.client.post(f"/perf/tasks/{task['id']}/runs/clear", json={'run_ids': [second['latest_run_id']]}))
    assert cleared['deleted'] == 1
    current = business(api.client.get(f"/perf/tasks/{task['id']}"))
    assert current['users'] == 2 and current['latest_run_id'] == first['latest_run_id'] and current['history_count'] == 1
    assert business(api.client.get(f"/perf/tasks/{task['id']}/runs/{first['latest_run_id']}")) == before
    business(api.client.get(f"/perf/tasks/{task['id']}/runs/{second['latest_run_id']}"), 404)


@pytest.mark.async_e2e
def test_active_record_is_protected_then_clear_and_run_again(perf_api, perf_load_target):
    api = perf_api
    task,config = create_task(api, perf_load_target)
    first = start(api, task)
    business(api.client.post(f"/perf/tasks/{task['id']}/run"), 409)
    business(api.client.put(f"/perf/tasks/{task['id']}", json={**config, 'users': 2}), 409)
    business(api.client.post(f"/perf/tasks/{task['id']}/runs/clear", json={'run_ids': [first['latest_run_id']]}), 409)
    assert business(api.client.post(f"/perf/tasks/{task['id']}/runs/clear", json={'all_finished': True}))['deleted'] == 0
    business(api.client.post(f"/perf/tasks/{task['id']}/stop", params={'execution_id': 'wrong-execution'}), 409)
    stopped = business(api.client.post(f"/perf/tasks/{task['id']}/stop", params={'execution_id': first['celery_task_id']}))
    assert stopped['status'] == 'cancelled' and stopped['latest_run_id'] == first['latest_run_id']
    deadline = time.monotonic() + 30
    while True:
        response = api.client.post(f"/perf/tasks/{task['id']}/runs/clear", json={'all_finished': True})
        if response.status_code == 200:
            assert business(response)['deleted'] == 1
            break
        business(response, 503)  # Control cleanup can still be in flight.
        assert time.monotonic() < deadline, '停止后的执行锁未正常清理'
        time.sleep(.2)
    current = business(api.client.get(f"/perf/tasks/{task['id']}"))
    assert current['status'] == 'pending' and current['history_count'] == 0 and current['users'] == config['users']
    assert current['rps'] is None and current['request_stats'] is None
    finish(api, task, start(api, task))
