"""Core HTTP-plan cases derived from the backend's documented/schema contract.

Each catalog row includes the nine design fields. Priorities are suggestions,
not approved smoke classifications. New IDs are local additions, not Excel IDs.
"""
from copy import deepcopy


SOURCE = "WhaleTestPro docs/Locust接口与链路压测.md；app/schemas/perf_plan.py；app/schemas/perf.py"


def single_plan(body_type="json"):
    bodies = {"json": {"quantity": 1, "active": True}, "form": {"quantity": "1"},
              "raw": "<quantity>鲸鱼</quantity>"}
    return {"mode": "single", "wait_seconds": 0.2, "timeout_seconds": 3.0,
            "steps": [{"name": "回显", "method": "POST", "path": "/echo",
                       "headers": {"X-Fixture": "perf-core"}, "params": {"source": "apitest"},
                       "body_type": body_type, "body": bodies[body_type], "expected_status": 200}]}


def chain_plan():
    return {"mode": "chain", "wait_seconds": 0.2, "timeout_seconds": 3.0,
            "variables": {"quantity": 1, "active": True}, "steps": [
                {"name": "登录", "method": "POST", "path": "/login", "body_type": "json",
                 "body": {"owner": "${_vu_id}_${_iteration}"}, "expected_status": 200,
                 "extract_rules": {"token": "$.token"}},
                {"name": "创建订单", "method": "POST", "path": "/orders",
                 "headers": {"Authorization": "Bearer ${token}", "X-Fixture": "perf-core"},
                 "params": {"source": "apitest"}, "body_type": "json",
                 "body": {"quantity": "${quantity}", "active": "${active}"},
                 "expected_status": 201, "extract_rules": {"order_id": "$.id"}},
                {"name": "查询订单", "method": "GET", "path": "/orders/${order_id}",
                 "headers": {"Authorization": "Bearer ${token}"}, "expected_status": 200,
                 "assertions": [{"type": "json_eq", "path": "$.id", "expected": "${order_id}"},
                                {"type": "json_eq", "path": "$.fixture", "expected": "whale-perf-core"}]},
            ]}


def request_for(plan):
    return {"name_prefix": "auto_perf_core_", "target_host": "http://fixture.invalid",
            # Deliberately not a fixture route: silent fallback to legacy GET fails.
            "target_path": "/must-not-send-legacy-get", "users": 1, "spawn_rate": 1,
            "duration": 6, "load_config": deepcopy(plan)}


def _case(case_id, title, plan, status=201, host=None):
    request = request_for(plan)
    if host:
        request["target_host"] = host
    return {"module": "压测任务配置", "point": title, "case_id": case_id, "title": title,
            "priority": "P1（建议值，待人工确认）", "source": SOURCE,
            "preconditions": "隔离测试环境；有项目写权限；不运行压测任务",
            "steps": ["查询当前项目的压测任务 ID 集合", "POST /perf/tasks，发送本条 request",
                      "成功时 GET 详情和列表；失败时重新查询任务 ID 集合"],
            "expected": ("HTTP 201/code=0；配置经规范化后保存；详情及列表一致；尚无整轮统计"
                         if status == 201 else "HTTP 422/code=422；提供字段错误；项目任务 ID 集合不变"),
            "request": request, "status": status}


def config_cases():
    rows = [
        _case("PERF-CFG-P001", "POST JSON 配置及 Header/Query 保存正确", single_plan()),
        _case("PERF-CFG-P002", "三步链路顺序、变量及提取规则保存正确", chain_plan()),
        _case("PERF-CFG-P003", "表单对象配置保存正确", single_plan("form")),
        _case("PERF-CFG-P004", "UTF-8 原始文本配置保存正确", single_plan("raw")),
        _case("PERF-CFG-P005", "HEAD 无请求体配置保存正确", {"steps": [{"method": "HEAD", "path": "/health"}]}),
        _case("PERF-CFG-B001", "链路仅含一个步骤时创建成功", {"mode": "chain", "steps": [{"path": "/health"}]}),
        _case("PERF-CFG-B002", "链路恰好包含 100 步时创建成功", {"mode": "chain", "steps": [{"path": "/health"}] * 100}),
    ]
    invalid = [
        ("空步骤拒绝创建", {"steps": []}),
        ("链路 101 步拒绝创建", {"mode": "chain", "steps": [{"path": "/health"}] * 101}),
        ("单接口模式包含两步拒绝创建", {"steps": [{"path": "/health"}] * 2}),
        ("未支持的 TRACE 方法拒绝创建", {"steps": [{"path": "/health", "method": "TRACE"}]}),
        ("表单请求体为字符串拒绝创建", {"steps": [{"path": "/echo", "body_type": "form", "body": "x=1"}]}),
        ("raw 请求体为对象拒绝创建", {"steps": [{"path": "/echo", "body_type": "raw", "body": {"x": 1}}]}),
        ("无请求体模式携带 body 拒绝创建", {"steps": [{"path": "/echo", "body": {"x": 1}}]}),
        ("步骤包含绝对 URL 拒绝创建", {"steps": [{"path": "https://fixture.invalid/echo"}]}),
        ("请求头包含 CRLF 拒绝创建", {"steps": [{"path": "/echo", "headers": {"X-Test": "x\r\ny"}}]}),
        ("变量提取 JSONPath 无效拒绝创建", {"steps": [{"path": "/echo", "extract_rules": {"x": "$["}}]}),
        ("JSON Schema 外部引用拒绝创建", {"steps": [{"path": "/echo", "assertions": [
            {"type": "json_schema", "expected": {"$ref": "https://fixture.invalid/schema"}}]}]}),
    ]
    rows.extend(_case(f"PERF-CFG-N{i:03d}", title, plan, 422) for i, (title, plan) in enumerate(invalid, 1))
    rows.append(_case("PERF-CFG-N012", "Host 内嵌凭证拒绝创建", single_plan(), 422,
                      "http://fixture:synthetic@fixture.invalid"))
    rows.append(_case("PERF-CFG-N013", "Host 携带 Query 拒绝创建", single_plan(), 422,
                      "http://fixture.invalid?source=apitest"))
    return rows
