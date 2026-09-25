from types import SimpleNamespace
import pytest

from common.assert_util import assert_response


def response(data):
    return SimpleNamespace(status_code=200, text="isolated response",
                           envelope_json=lambda: {"code": 0, "data": data})


@pytest.mark.parametrize("data", [{"hashed_password": "secret"},
                                  [{"user": {"hashed_password": "secret"}}]])
def test_password_hash_extra_fields_fail_contract(data):
    with pytest.raises(AssertionError, match="hashed_password"):
        assert_response(response(data), {"status_code": 200})


def test_explicit_forbidden_fields_are_recursive():
    with pytest.raises(AssertionError, match="access_token"):
        assert_response(response({"rows": [{"access_token": "secret"}]}),
                        {"forbidden_fields": ["access_token"]})


def test_safe_nested_users_pass_contract():
    assert_response(response([{"user": {"id": 1, "username": "owner"}}]),
                    {"body_type": "list"})


@pytest.mark.parametrize("envelope,expected", [
    ({"code": 0, "data": {"id": 1}, "hashed_password": "synthetic-private-value"}, {}),
    ({"code": 0, "data": {"id": 1}, "metadata": [{"HASHED_PASSWORD": "synthetic-private-value"}]}, {}),
    ({"code": 0, "data": {"id": 1}, "access_token": "synthetic-private-value"},
     {"forbidden_fields": ["access_token"]}),
])
def test_forbidden_fields_outside_success_data_are_rejected_without_values(envelope, expected):
    reply = SimpleNamespace(status_code=200, text="isolated response", envelope_json=lambda: envelope)
    with pytest.raises(AssertionError, match="响应包含禁止返回的字段") as error:
        assert_response(reply, expected)
    assert "synthetic-private-value" not in str(error.value)


def test_complete_envelope_scan_preserves_data_contract_unwrapping():
    assert_response(response({"id": 1}), {
        "status_code": 200, "body_type": "dict", "required_fields": ["id"],
        "field_types": {"id": "int"}, "code": 0,
    })


def test_non_json_response_still_allows_status_only_contract():
    def invalid_json():
        raise ValueError("synthetic-non-json")
    reply = SimpleNamespace(status_code=200, text="isolated response", json=invalid_json)
    assert_response(reply, {"status_code": 200})
