"""Reusable performance task builders and verified lifecycle cleanup."""
from copy import deepcopy
import math
import time

from common.assert_util import assert_response


def assert_transaction_metrics(result):
    """Check public counter/rate consistency, not a performance acceptance SLO."""
    summary = result['iteration_stats']
    count, failures, elapsed = (summary[key] for key in ('iterations', 'failures', 'elapsed_seconds'))
    assert type(count) is int and count > 0 and type(failures) is int and 0 <= failures <= count
    assert elapsed > 0 and math.isclose(summary['iteration_rps'], count / elapsed, rel_tol=1e-6)
    samples = [row for row in result['history_samples'] if row.get('tps') is not None]
    assert samples, '缺少运行中TPS采样，不能只验证最终HTTP吞吐量'
    for row in samples:
        assert row['transaction_elapsed_s'] > 0 and row['transactions'] >= row['failed_transactions'] >= 0
        assert math.isclose(row['avg_tps'], row['transactions'] / row['transaction_elapsed_s'], rel_tol=1e-6)
        assert math.isclose(row['success_tps'], (row['transactions'] - row['failed_transactions']) / row['transaction_elapsed_s'], rel_tol=1e-6)
        assert row['tps'] >= 0 and row['transactions'] <= count
    for previous, current in zip(samples, samples[1:]):
        elapsed_delta = current['transaction_elapsed_s'] - previous['transaction_elapsed_s']
        assert elapsed_delta > 0
        assert math.isclose(current['tps'], (current['transactions'] - previous['transactions']) / elapsed_delta, rel_tol=1e-6)


def task_payload(unique_name, req):
    payload = {
        "name": unique_name(req["name_prefix"]),
        "target_host": req["target_host"],
        "target_path": req["target_path"],
        "users": req["users"],
        "spawn_rate": req["spawn_rate"],
        "duration": req["duration"],
    }
    # Omission keeps the legacy GET contract; explicit null is also preserved.
    if "load_config" in req:
        payload["load_config"] = deepcopy(req["load_config"])
    return payload


def stop_and_delete(project_client, task_id):
    stopped = project_client.post(f"/perf/tasks/{task_id}/stop")
    assert_response(stopped, {"status_code": 200})
    deadline = time.monotonic() + 30
    while True:
        current = project_client.get(f"/perf/tasks/{task_id}")
        assert_response(current, {"status_code": 200})
        if current.json()["status"] in {"pending", "done", "failed", "cancelled"}:
            # GET also reconciles the old Worker lease. A control request may
            # still be in flight, so verify deletion instead of swallowing 404.
            deleted = project_client.delete(f"/perf/tasks/{task_id}")
            if deleted.status_code == 200:
                assert_response(deleted, {"status_code": 200})
                assert project_client.get(f"/perf/tasks/{task_id}").status_code == 404
                return
            # 409: status changed; 503: owned Master cleanup is unavailable.
            # Keep legacy 404 polling for older deployments, but never treat
            # any of these responses as successful deletion.
            assert deleted.status_code in {404, 409, 503}, f"压测任务删除失败: {deleted.text}"
        assert time.monotonic() < deadline, "压测清理未完成，任务或执行锁仍未释放"
        time.sleep(1)
