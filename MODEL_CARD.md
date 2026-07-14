# Model Card — logx v0.1.0

NL → nginx-log-query translation model. Fine-tune of
[`google/t5-efficient-tiny`](https://huggingface.co/google/t5-efficient-tiny)
(15.57M params, Apache-2.0) that maps English questions about nginx logs to a
strict JSON DSL, executed by this repo's deterministic read-only layer.

- **Task**: seq2seq; input `parse: <question>` (≤64 tokens) → single-line
  minified DSL JSON (≤128 tokens). The DSL contract (4 actions + abstain,
  nginx access/error fields) is defined by
  [schema/dsl_v0.1.json](schema/dsl_v0.1.json) and
  [schema/fields.py](schema/fields.py).
- **Download**: [Releases](https://github.com/devang007/logX/releases) →
  `logx-model-v0.1.0.zip` (56 MB) + `.sha256`. Contains **safetensors and
  JSON only — no pickle files**.
- **License**: Apache-2.0 (code and weights; base model is Apache-2.0).

## How to use

Via the CLI (recommended — includes validation + safe execution):

```bash
git clone https://github.com/devang007/logX && cd logX
./install.sh          # downloads this model zip automatically
logx -q "top 5 ips" -src /var/log/nginx/access.log
```

Or directly with 🤗 Transformers:

```python
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
tok = AutoTokenizer.from_pretrained("path/to/unzipped/model")
model = AutoModelForSeq2SeqLM.from_pretrained("path/to/unzipped/model")
ids = tok("parse: how many 502s in the last hour", return_tensors="pt").input_ids
print(tok.decode(model.generate(ids, max_length=128)[0], skip_special_tokens=True))
# {"action":"count","source":"nginx_access","filters":[{"field":"status","op":"eq","value":"502"}],"time":{"last":"1h"}}
```

The tokenizer is **not** a stock T5 tokenizer: 6 tokens (`< \ ^ { } ~`) were
added so JSON braces survive encoding, with a patched Metaspace pre-tokenizer.
Always load the tokenizer shipped in the zip, never the base model's.

## Training

Trained in a separate private pipeline; this repo distributes the artifacts.

| | |
|---|---|
| Data | 42,558 train / 2,364 val rows, synthetic teacher-generated NL/DSL pairs; every row schema-validated and executor-verified before training |
| Recipe | HF `Seq2SeqTrainer`, 15 epochs, lr 3e-4 (linear, 5% warmup), batch 64, fp32, AdamW, wd 0.01, seed 42 |
| Selection | best val exact-match checkpoint (epoch 14) |
| Hardware | Apple M1 Pro (MPS), ~43 h wall clock |

## Evaluation (val split, n=2,364, greedy decoding)

| Metric | Value |
|---|---|
| Exact match (canonical string) | **90.95%** |
| JSON-valid rate | 98.27% |
| Schema-valid rate | 98.18% |

Held-out `test` and out-of-distribution `test_ood` results are **not yet
published** — treat OOD generalization as unmeasured. Training data is
synthetic; phrasings far from its distribution will degrade accuracy.

## Intended use & limitations

- Intended: translating English questions about **nginx access/error logs**
  into DSL v0.1, **behind schema validation** (as the `logx` CLI does).
  Out-of-scope questions are trained to yield `{"action":"abstain"}`.
- Not intended: general text generation, other log formats, other languages,
  or use of raw outputs without validation (~2% of outputs are invalid, ~9%
  are wrong — validate, and show the DSL to the user before acting on it).
- The model only *translates*; it never executes anything. Execution safety
  (read-only allowlist, shell-free, injection-proof value passing) lives in
  [src/executor.py](src/executor.py) and is enforced regardless of what the
  model emits.
