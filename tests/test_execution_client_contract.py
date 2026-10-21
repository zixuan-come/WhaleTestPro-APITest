"""Transport/JSON oracle checks without importing the system under test."""
from types import SimpleNamespace
import httpx
import pytest
from common.request_util import RequestUtil
from common.assert_util import assert_response, assert_values


@pytest.mark.parametrize('path', ['/interfaces/7/run', '/cases/7/run', '/cases/chain',
    '/scenarios/7/run', '/scenarios/7/debug', '/suites/7/run', '/regression/run', '/traffic/replay/7'])
def test_sync_requests_allow_long_executions_but_honor_explicit_timeout(monkeypatch, path):
    calls = []
    monkeypatch.setattr(httpx, 'request', lambda **kwargs: calls.append(kwargs) or httpx.Response(200, json={}))
    client = RequestUtil('http://synthetic.invalid', timeout=4)
    client.post(path); assert calls[-1]['timeout'] == 600
    client.post(path, timeout=12); assert calls[-1]['timeout'] == 12
    client.get(path); assert calls[-1]['timeout'] == 4
    client.post('/regression/preview'); assert calls[-1]['timeout'] == 4
    assert client.timeout == 4


def reply(value):
    return SimpleNamespace(status_code=200, text='synthetic response', envelope_json=lambda: {'code': 0, 'data': value})


@pytest.mark.parametrize('actual,expected', [(True, 1), (1, True), (False, 0), (0, False),
    ({'rows': [1]}, {'rows': [True]}), ([{'flag': False}], [{'flag': 0}]), ('1', 1)])
def test_value_oracle_rejects_typed_json_mismatch(actual, expected):
    with pytest.raises(AssertionError):
        assert_values(reply({'value': actual}), {'value': expected})


def test_value_oracle_accepts_numbers_and_rejects_missing_null_field():
    assert_values(reply({'rows': [1, None, True]}), {'rows': [1.0, None, True]})
    with pytest.raises(AssertionError):
        assert_values(reply({}), {'missing': None})


def test_boolean_never_passes_declared_integer_type():
    with pytest.raises(AssertionError): assert_response(reply(True), {'body_type': 'int'})
    with pytest.raises(AssertionError): assert_response(reply({'id': True}), {'field_types': {'id': 'int'}})
    assert_response(reply({'id': 1, 'active': True}), {'field_types': {'id': 'int', 'active': 'bool'}})
