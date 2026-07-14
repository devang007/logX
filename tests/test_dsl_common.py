"""Contract tests: canonical serialization + schema/fields.py consistency."""

import json

import pytest

import dsl_common
from dsl_common import DSLValidationError, canonicalize, fields, to_target


def test_canonical_key_order_and_minified():
    dsl = {
        "time": {"last": "1h"},
        "filters": [{"value": "500", "op": "eq", "field": "status"}],
        "source": "nginx_access",
        "action": "filter_show",
    }
    assert to_target(dsl) == (
        '{"action":"filter_show","source":"nginx_access",'
        '"filters":[{"field":"status","op":"eq","value":"500"}],'
        '"time":{"last":"1h"}}'
    )


def test_defaults_and_nulls_dropped():
    dsl = {
        "action": "top",
        "source": "nginx_access",
        "filters": [],
        "group_by": "ip",
        "top_k": 10,
        "time": None,
        "limit": 100,
    }
    assert canonicalize(dsl) == {"action": "top", "source": "nginx_access", "group_by": "ip"}


def test_non_default_values_kept():
    dsl = {"action": "top", "source": "nginx_access", "group_by": "ip", "top_k": 5, "limit": 20}
    assert canonicalize(dsl) == dsl


def test_unknown_keys_preserved_then_rejected():
    dsl = {"action": "show", "explain": True}
    assert "explain" in canonicalize(dsl)  # not silently laundered
    with pytest.raises(DSLValidationError):
        dsl_common.validate_dsl(canonicalize(dsl))


def test_validate_rejects_bad_regex_and_time():
    with pytest.raises(DSLValidationError, match="regex"):
        dsl_common.validate_dsl(
            {"action": "count", "filters": [{"field": "path", "op": "regex", "value": "[unclosed"}]})
    with pytest.raises(DSLValidationError, match="from > to"):
        dsl_common.validate_dsl(
            {"action": "count", "time": {"from": "2026-07-12T10:00:00", "to": "2026-07-12T09:00:00"}})


def test_schema_and_fields_py_in_sync():
    schema = json.loads(dsl_common.SCHEMA_PATH.read_text())
    props = schema["properties"]
    assert tuple(props["action"]["enum"]) == fields.ACTIONS
    assert tuple(props["source"]["enum"]) == fields.SOURCES
    assert tuple(props["filters"]["items"]["properties"]["op"]["enum"]) == fields.OPS
    assert tuple(props["filters"]["items"]["properties"]["field"]["enum"]) == fields.ALL_FIELDS
    assert tuple(props["group_by"]["enum"]) == fields.ALL_FIELDS
    per_source = {
        cond["if"]["properties"]["source"]["const"]:
            tuple(cond["then"]["properties"]["group_by"]["enum"])
        for cond in schema["allOf"]
        if "source" in cond.get("if", {}).get("properties", {})
    }
    assert per_source["nginx_access"] == fields.NGINX_ACCESS_FIELDS
    assert per_source["nginx_error"] == fields.NGINX_ERROR_FIELDS
    # canonical key order matches the schema's property order (PLAN.md section 2)
    assert tuple(props.keys()) == dsl_common.KEY_ORDER
