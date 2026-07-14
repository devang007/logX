"""Phase 1 acceptance + safety tests for executor.py.

Two guarantees:
1. Acceptance — 20+ hand-written DSL examples execute correctly on sample
   nginx access/error logs (PLAN.md Phase 1 acceptance).
2. Safety — no possible DSL input produces a mutating command: pipelines only
   use read-only whitelisted binaries, values never enter awk program text,
   and adversarial values (quotes, semicolons, $(), backticks) have no effect.
"""

import gzip
import shlex
from datetime import datetime
from pathlib import Path

import pytest

import executor
from executor import AbstainError, ExecutorError
from dsl_common import DSLValidationError

FIXTURES = Path(__file__).parent / "fixtures"
ACCESS = str(FIXTURES / "access.log")
ERROR = str(FIXTURES / "error.log")
NOW = datetime(2026, 7, 12, 10, 30, 0)  # fixed clock for time_relative cases


def run(dsl, log=ACCESS, now=NOW):
    out = executor.execute(dsl, log_path=log, now=now)
    return [line for line in out.splitlines() if line]


def f(field, op, value):
    return {"field": field, "op": op, "value": value}


# --- acceptance: (id, dsl, log, expected) -----------------------------------
# expected: int -> number of output lines; ("first", s) -> first output line;
# ("exact", [..]) -> exact output lines.
ACCEPTANCE = [
    ("show_all", {"action": "show", "source": "nginx_access"}, ACCESS, 12),
    ("status_eq_500", {"action": "filter_show", "source": "nginx_access",
                       "filters": [f("status", "eq", "500")]}, ACCESS, 2),
    ("status_gte_500", {"action": "filter_show", "source": "nginx_access",
                        "filters": [f("status", "gte", "500")]}, ACCESS, 4),
    ("count_5xx", {"action": "count", "source": "nginx_access",
                   "filters": [f("status", "gte", "500")]}, ACCESS, ("exact", ["4"])),
    ("top_ip", {"action": "top", "source": "nginx_access", "group_by": "ip",
                "top_k": 1}, ACCESS, ("exact", ["4 10.0.0.2"])),
    ("top_method", {"action": "top", "source": "nginx_access", "group_by": "method",
                    "top_k": 1}, ACCESS, ("exact", ["9 GET"])),
    ("method_post", {"action": "filter_show", "source": "nginx_access",
                     "filters": [f("method", "eq", "POST")]}, ACCESS, 1),
    ("path_contains", {"action": "filter_show", "source": "nginx_access",
                       "filters": [f("path", "contains", "/api/")]}, ACCESS, 7),
    ("path_regex", {"action": "filter_show", "source": "nginx_access",
                    "filters": [f("path", "regex", "^/static/")]}, ACCESS, 2),
    ("ua_contains", {"action": "filter_show", "source": "nginx_access",
                     "filters": [f("ua", "contains", "curl")]}, ACCESS, 3),
    ("bytes_gte", {"action": "filter_show", "source": "nginx_access",
                   "filters": [f("bytes", "gte", "1000")]}, ACCESS, 2),
    ("negation_ne_200", {"action": "filter_show", "source": "nginx_access",
                         "filters": [f("status", "ne", "200")]}, ACCESS, 7),
    ("time_absolute", {"action": "filter_show", "source": "nginx_access",
                       "time": {"from": "2026-07-12T00:00:00", "to": "2026-07-12T23:59:59"}},
     ACCESS, 5),
    ("time_last_6h", {"action": "filter_show", "source": "nginx_access",
                      "time": {"last": "6h"}}, ACCESS, 5),
    ("time_last_1d", {"action": "filter_show", "source": "nginx_access",
                      "time": {"last": "1d"}}, ACCESS, 9),  # cutoff 2026-07-11 10:30
    ("multi_filter", {"action": "count", "source": "nginx_access",
                      "filters": [f("status", "gte", "500"), f("ua", "contains", "curl")]},
     ACCESS, ("exact", ["1"])),
    ("limit_3", {"action": "show", "source": "nginx_access", "limit": 3}, ACCESS, 3),
    ("top_path_5xx", {"action": "top", "source": "nginx_access", "group_by": "path",
                      "top_k": 1, "filters": [f("status", "gte", "500")]},
     ACCESS, ("exact", ["2 /api/v1/users"])),
    ("count_group_status", {"action": "count", "source": "nginx_access",
                            "group_by": "status"}, ACCESS, ("first", "5 200")),
    ("err_level_eq", {"action": "filter_show", "source": "nginx_error",
                      "filters": [f("level", "eq", "error")]}, ERROR, 2),
    ("err_count_all", {"action": "count", "source": "nginx_error"}, ERROR, ("exact", ["4"])),
    ("err_msg_contains", {"action": "filter_show", "source": "nginx_error",
                          "filters": [f("msg", "contains", "timed out")]}, ERROR, 1),
    ("err_client_eq", {"action": "filter_show", "source": "nginx_error",
                       "filters": [f("client", "eq", "10.0.0.2")]}, ERROR, 2),
    ("err_level_ne", {"action": "filter_show", "source": "nginx_error",
                      "filters": [f("level", "ne", "error")]}, ERROR, 2),
    ("err_top_client", {"action": "top", "source": "nginx_error", "group_by": "client",
                        "top_k": 1}, ERROR, ("exact", ["2 10.0.0.2"])),
    ("err_time_abs", {"action": "count", "source": "nginx_error",
                      "time": {"from": "2026-07-12T00:00:00", "to": "2026-07-12T23:59:59"}},
     ERROR, ("exact", ["2"])),
    ("err_request_contains", {"action": "filter_show", "source": "nginx_error",
                              "filters": [f("request", "contains", "claims")]}, ERROR, 2),
]


@pytest.mark.parametrize("name,dsl,log,expected", ACCEPTANCE, ids=[c[0] for c in ACCEPTANCE])
def test_acceptance(name, dsl, log, expected):
    lines = run(dsl, log=log)
    if isinstance(expected, int):
        assert len(lines) == expected, lines
    elif expected[0] == "exact":
        assert lines == expected[1]
    else:
        assert lines[0] == expected[1], lines


def test_gzip_source(tmp_path):
    gz = tmp_path / "access.log.gz"
    gz.write_bytes(gzip.compress(Path(ACCESS).read_bytes()))
    dsl = {"action": "filter_show", "source": "nginx_access",
           "filters": [f("status", "eq", "500")]}
    assert len(run(dsl, log=str(gz))) == 2
    assert executor.build_command(dsl, log_path=str(gz)).startswith("zcat <")


# --- source resolution -------------------------------------------------------

def test_auto_source_inference():
    assert executor.resolve_source(
        {"action": "filter_show", "filters": [f("level", "eq", "error")]}) == "nginx_error"
    assert executor.resolve_source(
        {"action": "filter_show", "filters": [f("path", "contains", "/api")]}) == "nginx_access"
    assert executor.resolve_source({"action": "show"}) == "nginx_access"
    with pytest.raises(ExecutorError):  # mixes access-only and error-only fields
        executor.resolve_source(
            {"action": "count", "filters": [f("path", "eq", "/x"), f("level", "eq", "warn")]})


# --- validation gate ---------------------------------------------------------

def test_abstain_raises():
    with pytest.raises(AbstainError):
        executor.build_pipeline({"action": "abstain"}, log_path=ACCESS)


def test_invalid_dsl_rejected():
    with pytest.raises(DSLValidationError):  # top without group_by
        executor.build_pipeline({"action": "top", "source": "nginx_access"}, log_path=ACCESS)
    with pytest.raises(DSLValidationError):  # unknown field
        executor.build_pipeline(
            {"action": "filter_show", "filters": [f("hostname", "eq", "x")]}, log_path=ACCESS)
    with pytest.raises(DSLValidationError):  # error-only field on access source
        executor.build_pipeline(
            {"action": "filter_show", "source": "nginx_access",
             "filters": [f("level", "eq", "error")]}, log_path=ACCESS)
    with pytest.raises(DSLValidationError):  # abstain must have no other keys
        executor.build_pipeline({"action": "abstain", "source": "auto"}, log_path=ACCESS)


# --- safety: no DSL input can produce a mutating command ----------------------

EVIL_VALUES = [
    '"; rm -rf ~; echo "',
    "$(touch pwned_subshell)",
    "`touch pwned_backtick`",
    "'; system(\"touch pwned_awk\"); '",
    'a" || touch pwned_or; #',
    "value | tee pwned_pipe",
    "multi\nline; touch pwned_nl",
    "back\\slash\\d+",
]


@pytest.mark.parametrize("evil", EVIL_VALUES)
def test_adversarial_values_are_inert(evil, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # any file side effect would land here
    dsl = {"action": "filter_show", "source": "nginx_access",
           "filters": [f("path", "contains", evil)]}

    segments, _ = executor.build_pipeline(dsl, log_path=ACCESS)
    # every stage binary is read-only whitelisted
    assert all(seg[0] in executor.READ_ONLY_BINARIES for seg in segments)
    # the value never appears in awk program text — only in a -v assignment
    program = segments[-1][-1]
    assert evil not in program
    assert any(arg.startswith("__f0=") for seg in segments for arg in seg)

    out = executor.execute(dsl, log_path=ACCESS)  # must run, match nothing
    assert out.strip() == ""
    assert list(tmp_path.iterdir()) == [], "adversarial value caused a side effect"


def test_display_command_is_shell_safe():
    evil = "$(touch pwned)'; rm -rf ~ #"
    cmd = executor.build_command(
        {"action": "filter_show", "source": "nginx_access",
         "filters": [f("ua", "eq", evil)]}, log_path=ACCESS)
    # shlex round-trip: the evil value stays a single token, never syntax
    for part in cmd.split(" | "):
        tokens = shlex.split(part.split(" < ")[0])
        assert tokens[0] in executor.READ_ONLY_BINARIES


def test_awk_backslash_value_roundtrip():
    # value with backslashes arrives byte-for-byte (escaping is a no-op)
    dsl = {"action": "count", "source": "nginx_access",
           "filters": [f("path", "contains", "back\\slash")]}
    assert run(dsl) == ["0"]


def test_regex_metachars_in_contains_are_literal():
    # contains uses index(), so regex metachars must not act as regex
    dsl = {"action": "count", "source": "nginx_access",
           "filters": [f("path", "contains", ".*")]}
    assert run(dsl) == ["0"]


def test_missing_log_file():
    with pytest.raises(ExecutorError, match="not found"):
        executor.execute({"action": "show"}, log_path="/nonexistent/access.log")
