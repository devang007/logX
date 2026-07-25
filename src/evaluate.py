#!/usr/bin/env python
"""Evaluate logX. Thin entry point over the commons eval harness. FACTORY-ONLY.

    # full report + dump EVERY failing case to a JSONL you can inspect / re-run:
    python -m logX.src.evaluate --model-dir <run>/best \
        --splits val,test,test_ood --misses-out misses.jsonl

Exact match, per-tag EM and validity rates come for free; slot-F1 / executability
/ abstain P/R activate once those hooks are wired on SPEC. `eval_report.json` keeps
a 30-row miss sample per split; `--misses-out` writes them all.
"""

from commons.eval import harness
from logX.src.task_spec import SPEC

if __name__ == "__main__":
    harness.run(SPEC)
