import pytest
from common.core_flow import CoreWorkspace
from tests.test_core_flow_contract import isolated_core_api
from testcases.test_core import test_scheduled_regression as delta

CHECKS = [
    *[('test_schedule_saves_explicit_targets_and_preserves_them_on_toggle', {'mode':mode}) for mode in ('case','suite')],
    *[('test_invalid_schedule_targets_do_not_create_jobs', {'selection':selection}) for selection in (
        {'mode':'case','ids':[]},{'mode':'suite','ids':[0]},{'mode':'case','ids':[1],'tag':'smoke'})],
    ('test_schedule_rejects_foreign_selected_asset_without_creating_job', {}),
    ('test_retired_regression_entry_point_cannot_execute', {}),
]

@pytest.mark.parametrize('name,kwargs',CHECKS)
def test_scheduled_http_script_against_current_routes(isolated_core_api,name,kwargs):
    actors,calls,db = isolated_core_api
    w = CoreWorkspace(actors,'http://isolated.invalid','http://runner.invalid')
    try:
        w.initialize(); getattr(delta,name)(w,**kwargs)
        assert not calls
    finally: w.close()
    from app.models.schedule import Schedule
    assert db.query(Schedule).count() == 0
