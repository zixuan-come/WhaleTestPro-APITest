"""HTTP scripts on real routes with a deterministic, non-network runtime adapter.

Runs the actual declarative iteration engine against the pure fixture handler.
Does not claim deployed Celery/Locust or real performance acceptance.
"""
from copy import deepcopy
from datetime import datetime
import re
import time
from types import SimpleNamespace
import pytest
from tests.test_perf_core_contract import isolated_perf_api, SyntheticLocustClient
from common.perf_flow import assert_transaction_metrics
from testcases.test_perf_core import test_perf_history as delta


@pytest.fixture
def sampled_perf_api(isolated_perf_api, monkeypatch):
    from app.models.perf import PerfTask
    from app.repositories import perf as repository
    from app.services import perf
    from app.schemas.perf_plan import PerfLoadConfig
    from app.core.perf_plan import execute_iteration
    from app.core.perf_history import transaction_sample
    api = isolated_perf_api
    route_client = api.client
    generations = {}
    monkeypatch.setattr(delta, 'time', SimpleNamespace(monotonic=time.monotonic, sleep=lambda _: None))

    def advance(task_id):
        task = api.database.get(PerfTask, task_id)
        if task is None or task.status not in {'queued','running'}:
            return
        if task.status == 'queued':
            repository.db_update_if_status(api.database, task.id, api.project_id, 'queued', status='running',
                started_at=datetime.utcnow(), heartbeat_at=datetime.utcnow())
            return
        key = task.celery_task_id
        state = generations.setdefault(key, {'tick':0,'client':SyntheticLocustClient(),'outcomes':[],'samples':[]})
        state['tick'] += 1
        plan = PerfLoadConfig.model_validate(task.load_config)
        for i in range(2):
            state['outcomes'].append(execute_iteration(state['client'],task.target_host,plan,'isolated-vu',len(state['outcomes'])+1))
        count=len(state['outcomes']);failures=sum(not row['passed'] for row in state['outcomes'])
        elapsed=state['tick']*2
        summary={'lease':api.cache.get(perf.RUN_LOCK_KEY),'iterations':count,'failures':failures,
            'elapsed_seconds':elapsed,'iteration_rps':count/elapsed,'configuration_failures':0,
            'fail_ratio':failures/count,'avg_duration_ms':sum(row['duration_ms'] for row in state['outcomes'])/count}
        rows=[{**row,'rps':row['num_requests']/elapsed,'avg_response_ms':1,'p95_response_ms':1,'p99_response_ms':1}
              for row in state['client'].rows.values()]
        rps=sum(row['num_requests'] for row in rows)/elapsed
        sample={'elapsed_s':elapsed,'sampled_at':datetime.utcnow().isoformat()+'Z','rps':rps,'users':task.users,
                'avg_response_ms':1,'p95_response_ms':1,'p99_response_ms':1,'fail_ratio':failures/count,
                **transaction_sample(summary,state['samples'][-1] if state['samples'] else None)}
        state['samples'].append(sample)
        fields={'rps':rps,'avg_response_ms':1,'p95_response_ms':1,'p99_response_ms':1,
            'fail_ratio':failures/count,'request_stats':rows,'history_samples':deepcopy(state['samples']),
            'iteration_stats':summary,'heartbeat_at':datetime.utcnow()}
        if state['tick']==3:fields.update(status='done',finished_at=datetime.utcnow())
        repository.db_update_if_status(api.database,task.id,api.project_id,'running',**fields)
        if state['tick']==3:api.cache.values.clear()  # This fixture's private cache only.

    class Adapter:
        def __getattr__(self,name):return getattr(route_client,name)
        def get(self,path,**kwargs):
            match=re.fullmatch(r'/perf/tasks/(\d+)',path)
            if match:advance(int(match[1]))
            return route_client.get(path,**kwargs)
    api.client=Adapter()
    return api


CHECKS=[
 ('test_edit_pending_configuration_keeps_empty_history',{}),
 *[('test_history_pagination_boundaries',{'params':params}) for params in ({'offset':-1},{'limit':0},{'limit':101})],
 *[('test_invalid_clear_selection_does_not_modify_task',{'selection':selection}) for selection in ({},{'run_ids':[]},{'run_ids':[0]},{'run_ids':[1,1]},{'run_ids':[1],'all_finished':True})],
 *[('test_live_statistics_and_tps_before_completion',{'mode':mode}) for mode in ('single','chain')],
 ('test_repeat_edit_snapshot_pagination_and_selective_clear',{}),
 ('test_active_record_is_protected_then_clear_and_run_again',{}),
]


@pytest.mark.parametrize('name,args',CHECKS,ids=[f'{i:02d}_{name}' for i,(name,_) in enumerate(CHECKS,1)])
def test_perf_history_script_against_current_routes(sampled_perf_api,name,args):
    from common.core_flow import business
    kwargs={'perf_api':sampled_perf_api,**args}
    if name in {'test_live_statistics_and_tps_before_completion','test_repeat_edit_snapshot_pagination_and_selective_clear','test_active_record_is_protected_then_clear_and_run_again'}:
        kwargs['perf_load_target']='http://fixture.invalid'
    getattr(delta,name)(**kwargs)
    # Test-owned definitions and all dependent run snapshots remain removable.
    for task_id in list(sampled_perf_api.tasks):
        business(sampled_perf_api.client.delete(f'/perf/tasks/{task_id}'))
        business(sampled_perf_api.client.get(f'/perf/tasks/{task_id}'),404)
    from app.models.perf import PerfRun
    assert sampled_perf_api.database.query(PerfRun).count()==0


@pytest.mark.parametrize('defect',['missing_samples','wrong_average','wrong_success','negative_tps','wrong_interval'])
def test_transaction_assertions_reject_corrupted_statistics(defect):
    first={'transactions':2,'failed_transactions':0,'transaction_elapsed_s':2,'avg_tps':1,'success_tps':1,'tps':1}
    second={'transactions':4,'failed_transactions':1,'transaction_elapsed_s':4,'avg_tps':1,'success_tps':.75,'tps':1}
    result={'iteration_stats':{'iterations':4,'failures':1,'elapsed_seconds':4,'iteration_rps':1},
            'history_samples':[first,second]}
    assert_transaction_metrics(result)
    if defect=='missing_samples':result['history_samples']=[]
    if defect=='wrong_average':second['avg_tps']=999
    if defect=='wrong_success':second['success_tps']=999
    if defect=='negative_tps':second['tps']=-1
    if defect=='wrong_interval':second['tps']=999
    with pytest.raises(AssertionError):assert_transaction_metrics(result)
