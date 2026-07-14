"""Shared DSL v0.1 helpers: schema validation + canonical serialization.

Used by executor.py (gate before command build), validate_data.py (gate
before training data is accepted), and later evaluate.py / infer.py.
"""

from __future__ import annotations

import importlib.util
import json
import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import jsonschema

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO_ROOT / "schema" / "dsl_v0.1.json"


def _load_fields():
    spec = importlib.util.spec_from_file_location(
        "loglingo_fields", REPO_ROOT / "schema" / "fields.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fields = _load_fields()

# canonical key order (PLAN.md section 2) and defaults that get omitted
KEY_ORDER = ("action", "source", "filters", "group_by", "top_k", "time", "limit")
FILTER_KEY_ORDER = ("field", "op", "value")
DEFAULTS = {"top_k": 10, "limit": 100}


class DSLValidationError(ValueError):
    """The DSL object does not conform to schema v0.1."""


@lru_cache(maxsize=1)
def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


@lru_cache(maxsize=1)
def _validator() -> jsonschema.Draft7Validator:
    return jsonschema.Draft7Validator(load_schema())


def canonicalize(dsl: dict) -> dict:
    """Return the DSL with canonical key order, nulls and defaults dropped.

    Does NOT validate — unknown keys are preserved so validate_dsl() can
    reject them loudly instead of silently laundering bad teacher output.
    """
    if not isinstance(dsl, dict):
        raise DSLValidationError(f"dsl must be an object, got {type(dsl).__name__}")
    out = {}
    for key in KEY_ORDER:
        if key not in dsl:
            continue
        val = dsl[key]
        if val is None:
            continue
        if key in DEFAULTS and val == DEFAULTS[key]:
            continue
        if key == "filters":
            if val == []:
                continue
            if isinstance(val, list):
                val = [
                    {k: f[k] for k in FILTER_KEY_ORDER if k in f} if isinstance(f, dict) else f
                    for f in val
                ]
        out[key] = val
    for key, val in dsl.items():
        if key not in KEY_ORDER and val is not None:
            out[key] = val
    return out


def to_target(dsl: dict) -> str:
    """Canonical decoder target: single-line minified JSON."""
    return json.dumps(canonicalize(dsl), separators=(",", ":"), ensure_ascii=False)


def validate_dsl(dsl: dict) -> None:
    """Raise DSLValidationError unless `dsl` conforms to schema v0.1."""
    if not isinstance(dsl, dict):
        raise DSLValidationError(f"dsl must be an object, got {type(dsl).__name__}")
    error = jsonschema.exceptions.best_match(_validator().iter_errors(dsl))
    if error is not None:
        path = "/".join(str(p) for p in error.absolute_path) or "<root>"
        raise DSLValidationError(f"at {path}: {error.message}")

    # checks JSON Schema can't express cleanly
    for i, flt in enumerate(dsl.get("filters", []) or []):
        if flt.get("op") == "regex":
            try:
                re.compile(flt["value"])
            except re.error as exc:
                raise DSLValidationError(f"filters/{i}: bad regex {flt['value']!r}: {exc}")
    time_spec = dsl.get("time")
    if isinstance(time_spec, dict) and "from" in time_spec:
        try:
            t_from = datetime.fromisoformat(time_spec["from"])
            t_to = datetime.fromisoformat(time_spec["to"])
        except ValueError as exc:
            raise DSLValidationError(f"time: bad ISO timestamp: {exc}")
        if t_from.replace(tzinfo=None) > t_to.replace(tzinfo=None):
            raise DSLValidationError("time: from > to")
