"""Allowed DSL field names per log source (DSL v0.1).

Mirrors schema/dsl_v0.1.json — a unit test (tests/test_dsl_common.py)
asserts the two never drift apart.
"""

NGINX_ACCESS_FIELDS = ("ip", "ts", "method", "path", "status", "bytes", "referer", "ua")
NGINX_ERROR_FIELDS = ("ts", "level", "pid", "msg", "client", "request")

# union, order-preserving, access first (matches the enum order in the JSON schema)
ALL_FIELDS = tuple(dict.fromkeys(NGINX_ACCESS_FIELDS + NGINX_ERROR_FIELDS))

FIELDS_BY_SOURCE = {
    "nginx_access": NGINX_ACCESS_FIELDS,
    "nginx_error": NGINX_ERROR_FIELDS,
    "auto": ALL_FIELDS,
}

# fields compared numerically by the executor (gte/lte/eq/ne)
NUMERIC_FIELDS = frozenset({"status", "bytes", "pid"})

# used by source=auto inference
ERROR_ONLY_FIELDS = frozenset(NGINX_ERROR_FIELDS) - frozenset(NGINX_ACCESS_FIELDS)
ACCESS_ONLY_FIELDS = frozenset(NGINX_ACCESS_FIELDS) - frozenset(NGINX_ERROR_FIELDS)

ACTIONS = ("show", "filter_show", "count", "top", "abstain")
OPS = ("eq", "ne", "gte", "lte", "contains", "regex")
SOURCES = ("nginx_access", "nginx_error", "auto")

# phenomenon labels for coverage accounting (PLAN.md section 3)
TAG_VOCAB = frozenset({
    "status", "method", "path", "ip", "ua", "bytes", "level",
    "time_relative", "time_absolute", "group_top", "count", "plain_show",
    "multi_filter", "negation", "regex", "typo", "hinglish", "abstain",
})
