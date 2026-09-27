"""Unified scheduled selection CRUD, scope and retired HTTP entry point."""
import pytest
from common.core_flow import business

pytestmark = pytest.mark.core_flow


@pytest.mark.parametrize('mode', ['case', 'suite'])
def test_schedule_saves_explicit_targets_and_preserves_them_on_toggle(core_workspace, mode):
    w = core_workspace
    case = w.case(); env = w.environment()
    target = w.suite(case_ids=[case['id']]) if mode == 'suite' else case
    config = {'name':w.name('scheduled_'), 'cron':'0 2 * * *', 'env_id':env['id'],
              'enabled':False, 'selection':{'mode':mode, 'ids':[target['id'],target['id']]}, 'notify':False}
    row = w.create('/schedules', config)
    assert row['selection'] == {'mode':mode,'ids':[target['id']]}
    assert row['sync_status'] == 'synced'
    path = f"/schedules/{row['id']}"
    assert business(w.client.get(path))['selection'] == row['selection']
    assert any(item['id'] == row['id'] for item in business(w.client.get('/schedules')))
    business(w.foreign().get(path), 404)
    business(w.scoped(w.project_id,'outsider').get(path), 404)
    # PUT still permits omitted optional target fields, retaining saved choices.
    updated = business(w.client.put(path, json={'name':row['name'], 'cron':row['cron'], 'env_id':env['id'], 'enabled':True}))
    assert updated['selection'] == row['selection']
    business(w.client.put(path, json={**config, 'enabled':False}))
    business(w.client.delete(path))
    business(w.client.get(path), 404)


@pytest.mark.parametrize('selection', [{'mode':'case','ids':[]},{'mode':'suite','ids':[0]}, {'mode':'case','ids':[1],'tag':'smoke'}])
def test_invalid_schedule_targets_do_not_create_jobs(core_workspace, selection):
    w = core_workspace
    env = w.environment()
    config = {'name':w.name(), 'cron':'0 2 * * *', 'env_id':env['id'], 'selection':{k:v for k,v in selection.items() if k != 'tag'}}
    if 'tag' in selection: config['tag'] = selection['tag']
    business(w.client.post('/schedules', json=config), 422)
    assert business(w.client.get('/schedules')) == []


def test_schedule_rejects_foreign_selected_asset_without_creating_job(core_workspace):
    w = core_workspace
    env = w.environment(); other = w.case(client=w.foreign())
    business(w.client.post('/schedules', json={'name':w.name(), 'cron':'0 2 * * *', 'env_id':env['id'],
        'selection':{'mode':'case','ids':[other['id']]}}), 404)
    assert business(w.client.get('/schedules')) == []


def test_retired_regression_entry_point_cannot_execute(core_workspace):
    w = core_workspace
    assert w.client.post('/regression', json=[w.case()['id']]).status_code == 404
    assert business(w.client.get('/reports/executions', params={'kind':'regression'}))['total'] == 0
