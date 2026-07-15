import pytest

# YAML 里 body_type 声明 → Python 类型，用于校验响应体整体结构
BODY_TYPE_MAP = {
    "list": list,
    "dict": dict,
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
}


def skip_if_pending(case):
    # 用例标了 pending（多为待开发确认的疑似 bug）就跳过，理由打进 skip 信息
    if case.get("pending"):
        pytest.skip(case.get("pending_reason", "pending"))


def assert_response(resp, expected):
    """契约断言：按 YAML expected 里声明了哪几项就查哪几项。

    支持 4 类检查，彼此独立：
      status_code    —— HTTP 状态码
      body_type      —— 响应体整体类型（list / dict …）
      required_fields—— 响应 dict 必须包含的字段（只查存在性，不查值）
      detail         —— FastAPI 报错体的 detail 文案
    """
    # 1. 状态码
    if "status_code" in expected:
        assert resp.status_code == expected["status_code"], (
            f"状态码不符合预期: expected={expected['status_code']}, "
            f"actual={resp.status_code}, response={resp.text}"
        )

    # 响应体解析一次；非 JSON（理论上本 API 不会出现）时置 None，后续检查各自兜底
    try:
        body = resp.json()
    except Exception:
        body = None

    # 2. 响应体整体类型
    if "body_type" in expected:
        expected_type = BODY_TYPE_MAP[expected["body_type"]]
        assert isinstance(body, expected_type), (
            f"响应体类型不符合预期: expected={expected['body_type']}, "
            f"actual={type(body).__name__}, response={resp.text}"
        )

    # 3. 必含字段（存在性）
    if "required_fields" in expected:
        assert isinstance(body, dict), (
            f"required_fields 只能对 dict 响应校验, 实际={type(body).__name__}, "
            f"response={resp.text}"
        )
        missing = [f for f in expected["required_fields"] if f not in body]
        assert not missing, (
            f"响应缺少必含字段: missing={missing}, "
            f"actual_keys={list(body.keys())}, response={resp.text}"
        )

    # 4. 报错文案
    if "detail" in expected:
        actual = body.get("detail") if isinstance(body, dict) else None
        assert actual == expected["detail"], (
            f"detail 不符合预期: expected={expected['detail']}, "
            f"actual={actual}, response={resp.text}"
        )


def assert_values(resp, expected_values):
    """结果值校验:响应 dict 里指定字段的值必须等于期望值。

    区别于 assert_response 的 required_fields(只查字段在不在),这里查"值对不对"。
    典型用法:创建/更新后,断言响应回显的 name/method/... 确实等于刚提交的值,
    确认写入生效而非只返回了结构。
    """
    body = resp.json()
    assert isinstance(body, dict), f"值校验只能对 dict 响应, 实际={type(body).__name__}, response={resp.text}"
    mismatch = {k: (v, body.get(k)) for k, v in expected_values.items() if body.get(k) != v}
    assert not mismatch, (
        f"字段值不符合预期(字段: (期望, 实际)): {mismatch}, response={resp.text}"
    )
