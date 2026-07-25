"""logX TaskSpec — binds the commons pipeline to the logX NL -> DSL corpus.

FACTORY-ONLY: used to train the model via `python -m logX.src.train` from the
models-factory repo root; it imports `commons` and is NOT part of the shipped CLI
(install.sh copies only logx_cli.py / dsl_common.py / executor.py).

`check_target` uses the lenient JSON-only default from commons: it feeds only the
`schema_valid` leading-indicator metric — exact-match (which selects the best
checkpoint) is a plain string compare and is unaffected. To also report
schema-valid / executable / slot-F1, wire the hooks to this repo's dsl_common +
executor (note they use flat `import dsl_common`, so they'd need src/ on sys.path).
"""

from __future__ import annotations

import json

from commons import TaskSpec


def canonical(text: str) -> str | None:
    """Order-insensitive canonical form of a raw output, or None if unparseable.

    Parses the JSON and re-serializes through the DSL canonicalizer (sorts the
    AND-combined filters, canonical key order, drops defaults), so two outputs
    that mean the same thing map to one string. Powers the harness's semantic EM.
    """
    try:
        obj = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    try:
        import logX.src.dsl_common as dsl_common
        return dsl_common.to_target(obj)
    except Exception:
        return None


SPEC = TaskSpec(
    name="logX",
    base_model="google/t5-efficient-tiny",
    task_prefix="parse: ",
    input_field="nl",
    target_field="target",
    tags_field="tags",
    max_source_len=64,
    max_target_len=128,
    acceptance_em=0.80,
    canonical=canonical,
)
