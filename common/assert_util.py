def assert_response(resp, expected):
    if "status_code" in expected:
        assert resp.status_code == expected["status_code"], (
            f"状态码不符合预期: expected={expected['status_code']}, "
            f"actual={resp.status_code}, response={resp.text}"
        )

    if "detail" in expected:
        data = resp.json()
        assert data.get("detail") == expected["detail"], (
            f"detail 不符合预期: expected={expected['detail']}, "
            f"actual={data.get('detail')}, response={resp.text}"
        )