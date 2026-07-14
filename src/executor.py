"""DSL v0.1 -> read-only shell pipeline over raw nginx logs.

Safety model (defense in depth — see PLAN.md Phase 1):
1. Every DSL is canonicalized + schema-validated before a command is built.
2. Only closed-enum values (action, source, field, op) are ever interpolated
   into awk program text — all validated against schema/fields.py first.
3. Filter *values* NEVER enter program text: they are passed as `awk -v`
   variables. Backslashes are doubled so awk's -v escape processing is a
   no-op and the value arrives byte-for-byte.
4. Execution never touches a shell. The pipeline runs as a chain of
   subprocess argv lists; the string from build_command() is display-only.
5. Every pipeline stage's binary must be in READ_ONLY_BINARIES (asserted at
   build time), and the log file is fed via stdin so awk never interprets a
   path argument as a `var=value` assignment.

Known POC limitations:
- Timezone offsets in access-log timestamps are ignored; time comparison is
  on wall-clock strings (YYYYMMDDHHMMSS).
- `limit` applies to show/filter_show only; count/top output is small anyway.
"""

from __future__ import annotations

import re
import shlex
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import dsl_common
from dsl_common import DSLValidationError, fields

READ_ONLY_BINARIES = frozenset({"tail", "grep", "awk", "sort", "uniq", "wc", "zcat"})

DEFAULT_LOG_PATHS = {
    "nginx_access": "/var/log/nginx/access.log",
    "nginx_error": "/var/log/nginx/error.log",
}

DEFAULT_LIMIT = 100
DEFAULT_TOP_K = 10


class ExecutorError(ValueError):
    """DSL is valid but cannot be executed (bad field/source combo, IO, ...)."""


class AbstainError(ExecutorError):
    """action=abstain — nothing to execute; surface to the user instead."""


# --- awk programs -----------------------------------------------------------
# Placeholders (@@COND@@ / @@ACTION@@ / @@END@@) are replaced with code built
# ONLY from schema enums; user-controlled values arrive via -v variables.

_ACCESS_TEMPLATE = r'''function ts_sort(t,  d) {
    split(t, d, "[/: ]")
    return d[3] MONTHS[d[2]] d[1] d[4] d[5] d[6]
}
BEGIN {
    split("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec", __mn, " ")
    for (__i = 1; __i <= 12; __i++) MONTHS[__mn[__i]] = sprintf("%02d", __i)
}
{
    __nq = split($0, __q, "\"")
    split(__q[1], __a, " ")
    ip = __a[1]
    ts = ""
    __lb = index($0, "["); __rb = index($0, "]")
    if (__lb && __rb > __lb) ts = substr($0, __lb + 1, __rb - __lb - 1)
    method = ""; path = ""
    if (__nq >= 2) { split(__q[2], __r, " "); method = __r[1]; path = __r[2] }
    status = ""; bytes = ""
    if (__nq >= 3) { split(__q[3], __s, " "); status = __s[1]; bytes = __s[2] }
    referer = (__nq >= 4) ? __q[4] : ""
    ua = (__nq >= 6) ? __q[6] : ""
    ts_s = ts_sort(ts)
@@COND@@
@@ACTION@@
}
@@END@@'''

_ERROR_TEMPLATE = r'''{
    ts = $1 " " $2
    level = $3
    gsub(/[\[\]]/, "", level)
    pid = $4
    sub(/#.*$/, "", pid)
    msg = ""
    if (match($0, / \*[0-9]+ /)) msg = substr($0, RSTART + RLENGTH)
    else if (match($0, /[0-9]+#[0-9]+: /)) msg = substr($0, RSTART + RLENGTH)
    client = ""
    if (match($0, /client: [^,]+/)) client = substr($0, RSTART + 8, RLENGTH - 8)
    request = ""
    if (match($0, /request: "[^"]*"/)) request = substr($0, RSTART + 10, RLENGTH - 11)
    ts_s = ts
    gsub(/[^0-9]/, "", ts_s)
@@COND@@
@@ACTION@@
}
@@END@@'''

_TEMPLATES = {"nginx_access": _ACCESS_TEMPLATE, "nginx_error": _ERROR_TEMPLATE}

_OP_SYMBOL = {"eq": "==", "ne": "!=", "gte": ">=", "lte": "<="}


def _awk_escape(value: str) -> str:
    """Encode a value for `awk -v` so its escape processing returns the
    original bytes: double backslashes, escape control chars (awk rejects a
    literal newline in -v)."""
    return (
        value.replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )


def _cond(field: str, op: str, var: str) -> str:
    if field not in fields.ALL_FIELDS or op not in fields.OPS:
        raise ExecutorError(f"unknown field/op: {field}/{op}")  # schema should have caught this
    if op in _OP_SYMBOL:
        if field in fields.NUMERIC_FIELDS:
            return f"({field} + 0 {_OP_SYMBOL[op]} {var} + 0)"
        return f"({field} {_OP_SYMBOL[op]} {var})"
    if op == "contains":
        return f"(index({field}, {var}) > 0)"
    return f"({field} ~ {var})"  # regex: dynamic ERE from a variable, not code


def _time_bounds(spec: dict, now: datetime) -> tuple[str | None, str | None]:
    """Return (from, to) as sortable YYYYMMDDHHMMSS strings."""
    if "last" in spec:
        m = re.fullmatch(r"([1-9][0-9]*)([mhd])", spec["last"])
        if not m:
            raise ExecutorError(f"bad time.last: {spec['last']!r}")
        n = int(m.group(1))
        delta = {"m": timedelta(minutes=n), "h": timedelta(hours=n), "d": timedelta(days=n)}[m.group(2)]
        return (now - delta).strftime("%Y%m%d%H%M%S"), None
    t_from = datetime.fromisoformat(spec["from"]).replace(tzinfo=None)
    t_to = datetime.fromisoformat(spec["to"]).replace(tzinfo=None)
    return t_from.strftime("%Y%m%d%H%M%S"), t_to.strftime("%Y%m%d%H%M%S")


def resolve_source(dsl: dict) -> str:
    """Map source=auto (or missing) to a concrete source from the fields used."""
    source = dsl.get("source", "auto")
    used = {f["field"] for f in dsl.get("filters", []) or []}
    if dsl.get("group_by"):
        used.add(dsl["group_by"])
    if source != "auto":
        extra = used - set(fields.FIELDS_BY_SOURCE[source])
        if extra:
            raise ExecutorError(f"fields {sorted(extra)} not valid for source {source}")
        return source
    err_only = used & fields.ERROR_ONLY_FIELDS
    acc_only = used & fields.ACCESS_ONLY_FIELDS
    if err_only and acc_only:
        raise ExecutorError(
            f"cannot infer source: mixes access-only {sorted(acc_only)} "
            f"and error-only {sorted(err_only)} fields"
        )
    return "nginx_error" if err_only else "nginx_access"


def build_pipeline(
    dsl: dict, log_path: str | None = None, now: datetime | None = None
) -> tuple[list[list[str]], str]:
    """Validate the DSL and return ([argv, argv, ...], log_path).

    The first stage reads the log file on stdin; each stage pipes into the next.
    """
    dsl = dsl_common.canonicalize(dsl)
    dsl_common.validate_dsl(dsl)
    action = dsl["action"]
    if action == "abstain":
        raise AbstainError("request cannot be expressed in DSL v0.1")

    source = resolve_source(dsl)
    log_path = str(log_path or DEFAULT_LOG_PATHS[source])

    awk_args: list[str] = []
    conds: list[str] = []
    for i, flt in enumerate(dsl.get("filters", [])):
        var = f"__f{i}"
        awk_args += ["-v", f"{var}={_awk_escape(flt['value'])}"]
        conds.append(_cond(flt["field"], flt["op"], var))

    if dsl.get("time"):
        t_from, t_to = _time_bounds(dsl["time"], now or datetime.now())
        if t_from:
            awk_args += ["-v", f"__tfrom={t_from}"]
            conds.append('(ts_s >= __tfrom)')
        if t_to:
            awk_args += ["-v", f"__tto={t_to}"]
            conds.append('(ts_s <= __tto)')

    cond_line = f"    if (!({' && '.join(conds)})) next" if conds else ""

    group_by = dsl.get("group_by")
    end_block = ""
    if action in ("show", "filter_show"):
        awk_args += ["-v", f"__limit={int(dsl.get('limit', DEFAULT_LIMIT))}"]
        action_line = "    print\n    if (++__n >= __limit + 0) exit"
    elif action == "count" and not group_by:
        action_line = "    __n++"
        end_block = "END { print __n + 0 }"
    else:  # count+group_by, or top (schema guarantees top has group_by)
        action_line = f"    __c[{group_by}]++"
        end_block = 'END { for (__k in __c) printf "%d %s\\n", __c[__k], __k }'

    program = (
        _TEMPLATES[source]
        .replace("@@COND@@", cond_line)
        .replace("@@ACTION@@", action_line)
        .replace("@@END@@", end_block)
        .rstrip()
        + "\n"
    )

    segments: list[list[str]] = []
    if log_path.endswith(".gz"):
        segments.append(["zcat"])
    segments.append(["awk"] + awk_args + [program])
    if group_by and action in ("count", "top"):
        segments.append(["sort", "-rn"])
    if action == "top":
        top_k = int(dsl.get("top_k", DEFAULT_TOP_K))
        segments.append(["awk", "-v", f"__k={top_k}", "NR <= __k + 0"])

    for seg in segments:
        if seg[0] not in READ_ONLY_BINARIES:
            raise ExecutorError(f"internal error: {seg[0]} not in read-only whitelist")
    return segments, log_path


def build_command(dsl: dict, log_path: str | None = None, now: datetime | None = None) -> str:
    """Human-readable shell string of the pipeline. Display only — execution
    goes through execute(), which never invokes a shell."""
    segments, path = build_pipeline(dsl, log_path, now)
    parts = [shlex.join(seg) for seg in segments]
    parts[0] += f" < {shlex.quote(path)}"
    return " | ".join(parts)


def execute(
    dsl: dict,
    log_path: str | None = None,
    now: datetime | None = None,
    timeout: float = 30.0,
) -> str:
    """Run the pipeline (shell-free Popen chain) and return stdout."""
    segments, path = build_pipeline(dsl, log_path, now)
    p = Path(path)
    if not p.is_file():
        raise ExecutorError(f"log file not found: {path}")

    procs: list[subprocess.Popen] = []
    with open(p, "rb") as fh:
        prev = fh
        for i, argv in enumerate(segments):
            last = i == len(segments) - 1
            proc = subprocess.Popen(
                argv,
                stdin=prev,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE if last else subprocess.DEVNULL,
            )
            if prev is not fh:
                prev.close()  # let upstream see SIGPIPE on early exit
            prev = proc.stdout
            procs.append(proc)

    try:
        out, err = procs[-1].communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        for proc in procs:
            proc.kill()
        raise ExecutorError(f"pipeline timed out after {timeout}s")
    for proc in procs[:-1]:
        proc.wait(timeout=5)
    if procs[-1].returncode != 0:
        raise ExecutorError(
            f"pipeline failed (rc={procs[-1].returncode}): {err.decode(errors='replace').strip()}"
        )
    return out.decode("utf-8", errors="replace")
