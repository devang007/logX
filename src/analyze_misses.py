#!/usr/bin/env python
"""Bucket an eval misses.jsonl into failure categories for logX. FACTORY-ONLY.

    python -m logX.src.analyze_misses runs/misses.jsonl

Reads the JSONL written by `evaluate --misses-out` and classifies every miss:

  order_only      string-miss but SEMANTICALLY CORRECT (e.g. filter order) — not
                  a real error; canonical filter sorting + retraining removes these
  invalid_json    prediction is not parseable JSON (truncation / repetition)
  action_confusion   show / filter_show / count mixed up
  comparator_flip    >= vs <= (or eq vs ne) inverted
  spurious_time / missing_time   a time window hallucinated / dropped
  topk_value      wrong top_k default
  group_dim       wrong group_by dimension
  source_error    nginx_access vs nginx_error
  value_error     a filter value (number/ip/path) wrong
  filter_mismatch a filter added/removed/changed field
  time_value      time present in both but from/to/last wrong
  other           none of the above

Prints a ranked summary with examples and writes, next to the input:
  <name>.by_category.jsonl   every miss + "category"
  <name>.summary.json        {category: count} + totals + est. semantic EM gain
Pure stdlib — no torch / jsonschema / commons needed; runs anywhere.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

DEFAULTS = {"top_k": 10, "limit": 100}
_FKEYS = ("field", "op", "value")


def _norm(obj):
    """Canonical structure mirroring dsl_common.canonicalize: drop nulls/defaults/
    empty filters and sort the AND-combined filters, so order never matters."""
    if not isinstance(obj, dict):
        return obj
    out = {}
    for k, v in obj.items():
        if v is None:
            continue
        if k in DEFAULTS and v == DEFAULTS[k]:
            continue
        if k == "filters":
            if not v:
                continue
            v = sorted(
                ({fk: f[fk] for fk in _FKEYS if fk in f} if isinstance(f, dict) else f
                 for f in v),
                key=lambda f: (str(f.get("field", "")), str(f.get("op", "")),
                               str(f.get("value", ""))) if isinstance(f, dict) else (str(f), "", ""),
            )
        out[k] = v
    return out


def _key(obj):
    return json.dumps(_norm(obj), sort_keys=True, ensure_ascii=False)


def _filters(obj):
    return [(f.get("field"), f.get("op"), str(f.get("value")))
            for f in (obj.get("filters", []) or []) if isinstance(f, dict)]


def classify(gold: dict, pred_raw: str) -> str:
    try:
        p = json.loads(pred_raw)
    except Exception:
        return "invalid_json"
    if _key(gold) == _key(p):
        return "order_only"
    if not isinstance(p, dict):
        return "other"
    if gold.get("action") != p.get("action"):
        return "action_confusion"
    if ("time" in gold) != ("time" in p):
        return "spurious_time" if "time" in p else "missing_time"
    gf, pf = _filters(gold), _filters(p)
    if sorted(gf) != sorted(pf):
        if sorted((f, v) for f, o, v in gf) == sorted((f, v) for f, o, v in pf):
            return "comparator_flip"       # same field+value, operator differs
        if sorted((f, o) for f, o, v in gf) == sorted((f, o) for f, o, v in pf):
            return "value_error"           # same field+op, value differs
        return "filter_mismatch"           # a filter added/removed/field changed
    if gold.get("group_by") != p.get("group_by"):
        return "group_dim"
    if gold.get("source") != p.get("source"):
        return "source_error"
    if gold.get("top_k") != p.get("top_k"):
        return "topk_value"
    if gold.get("time") != p.get("time"):
        return "time_value"
    return "other"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("misses", type=Path, help="misses.jsonl from `evaluate --misses-out`")
    ap.add_argument("--examples", type=int, default=3, help="examples to print per category")
    args = ap.parse_args(argv)

    rows = [json.loads(l) for l in open(args.misses) if l.strip()]
    if not rows:
        print(f"no misses in {args.misses}")
        return

    counts: Counter = Counter()
    examples = defaultdict(list)
    annotated = []
    for m in rows:
        try:
            gold = json.loads(m["gold"])
        except Exception:
            gold = {}
        cat = classify(gold, m["pred"])
        counts[cat] += 1
        annotated.append({**m, "category": cat})
        if len(examples[cat]) < args.examples:
            examples[cat].append(m)

    n = len(rows)
    order_only = counts.get("order_only", 0)
    print(f"\n{n} misses in {args.misses.name}\n" + "=" * 60)
    for cat, c in counts.most_common():
        print(f"{cat:16} {c:6}  {c / n:5.1%}")
    print("=" * 60)
    if order_only:
        print(f"NOTE: {order_only} ({order_only / n:.1%}) are order_only — semantically "
              f"correct. Real errors: {n - order_only}.")

    for cat, _ in counts.most_common():
        print(f"\n----- {cat} -----")
        for m in examples[cat]:
            print(f"  in  : {m['input']}")
            print(f"  gold: {m['gold']}")
            print(f"  pred: {m['pred']}")

    by_cat = args.misses.with_suffix(".by_category.jsonl")
    summary = args.misses.with_suffix(".summary.json")
    with open(by_cat, "w") as f:
        for m in annotated:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")
    summary.write_text(json.dumps(
        {"n_misses": n, "order_only": order_only, "real_errors": n - order_only,
         "by_category": dict(counts.most_common())}, indent=2) + "\n")
    print(f"\nwrote {by_cat}\n      {summary}")


if __name__ == "__main__":
    main()
