#!/usr/bin/env python
"""Debug inference for logX: run one input and see the raw output. FACTORY-ONLY.

    python -m logX.src.infer "show me all 400 requests" --model-dir <run>/best
    python -m logX.src.infer --model-dir <run>/best        # interactive loop

Prints the raw decode, a confidence signal (mean token logprob) and JSON/schema
validity — handy for eyeballing the cases `evaluate --misses-out` flagged. The
shippable end-user CLI with the full safety chain + executor is logx_cli.py.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from commons.infer.predict import analyze, load_model, predict
from logX.src.task_spec import SPEC


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("query", nargs="?")
    ap.add_argument("--model-dir", default=str(SPEC.default_model_dir))
    args = ap.parse_args(argv)

    if not Path(args.model_dir).exists():
        raise SystemExit(f"model dir not found: {args.model_dir} — train first")
    tok, model = load_model(args.model_dir)

    def handle(text: str):
        out, conf = predict(SPEC, tok, model, text)
        a = analyze(SPEC, out)
        print(f"raw        : {out!r}")
        print(f"confidence : {conf:.3f}")
        print(f"json/schema: {a['json_valid']}/{a['schema_valid']}")

    if args.query:
        handle(args.query)
        return
    print("interactive mode — empty line to quit")
    while True:
        try:
            text = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not text:
            break
        handle(text)


if __name__ == "__main__":
    main()
