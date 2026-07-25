#!/usr/bin/env python
"""Fine-tune logX (NL -> DSL). Thin entry point over the commons trainer.

FACTORY-ONLY: run from the models-factory repo root, not part of the shipped CLI.

    python -m logX.src.train                          # full run (t5-efficient-tiny)
    python -m logX.src.train --limit 64 --epochs 1    # smoke test
    python -m logX.src.train --model "$DATA_DIR/logX/base_model" \
        --data-dir "$DATA_DIR/logX/clean" --out-dir "$DATA_DIR/logX/runs/local" \
        --batch-size 128 --grad-accum 2 --lr 6e-4 --eval-subset 500 \
        --group-by-length --early-stop-threshold 0.003   # GPU run

All flags, checkpointing/resume, the T5 tokenizer repair and best-on-val-EM
selection live in `commons.seq2seq.train`; the task specifics come from SPEC.
"""

from commons.seq2seq import train
from logX.src.task_spec import SPEC

if __name__ == "__main__":
    train.run(SPEC)
