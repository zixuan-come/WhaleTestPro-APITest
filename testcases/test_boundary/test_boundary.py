"""边界 / 畸形输入特征化:用数据驱动一次性钉住被测系统对畸形值的现状。

数据在 data/boundary.yaml。每条给 path + body + expected,body 里的哨兵
"{{LONG}}" 由 _build 替换成 300 个 'a'(超过常见 varchar(255))。

现状(被测系统多数字段不校验):
- 空 name          → 201(应 400/422)
- 超长 name(>255) → 500 未捕获的服务端错误(应 400/422)—— BUG
- 非法 cron        → 500(cron 未校验)—— BUG
- perf users<=0    → 201(负数/0 也接受,应 >=1)

断言 pin 住现状:后端补了校验/修了 500,对应用例会翻红,提示复核期望。
"""
import pytest
import allure

from common.yaml_util import load_yaml
from common.assert_util import assert_response, skip_if_pending

cases = load_yaml("data/boundary.yaml")["cases"]

LONG_VALUE = "a" * 300


def _build(body):
    """把 body 里的 "{{LONG}}" 哨兵替换成超长字符串,其它值原样保留。"""
    return {k: (LONG_VALUE if v == "{{LONG}}" else v) for k, v in body.items()}


def _ids(cs):
    return [c["case_id"] for c in cs]


@allure.feature("边界与畸形输入")
@allure.story("字段校验特征化")
class TestBoundary:

    @pytest.mark.parametrize("case", cases, ids=_ids(cases))
    def test_boundary(self, case, project_client, api_cleanup):
        skip_if_pending(case)
        resp = project_client.post(case["path"], json=_build(case["body"]))
        assert_response(resp, case["expected"])
        # 若畸形值意外建成功(如空 name / 负 users 现状 201),登记清理不留垃圾
        if resp.status_code < 300:
            api_cleanup(f"{case['path']}/{resp.json()['id']}")
