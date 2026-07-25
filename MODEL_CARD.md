# Model Card — logx v0.2.0

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
  `logx-model-v0.2.0.zip` (58 MB) + `.sha256`. Contains **safetensors and
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

The tokenizer is **not** a stock T5 tokenizer: 50 tokens were added — the 6
ASCII ones (`< \ ^ { } ~`) so JSON braces survive encoding, plus accented-Latin
and CJK characters occurring in the corpus — with a patched Metaspace
pre-tokenizer. Roundtrip is verified lossless on the full corpus at train time.
Always load the tokenizer shipped in the zip, never the base model's.

## Training

Trained in a separate private pipeline; this repo distributes the artifacts.

| | |
|---|---|
| Data | 83,544 train / 4,641 val rows, synthetic teacher-generated NL/DSL pairs; every row schema-validated and executor-verified before training |
| Recipe | HF `Seq2SeqTrainer`, 18 epochs, lr 6e-4, batch 128 × 2 grad-accum, fp32, AdamW |
| Selection | best val exact-match checkpoint (epoch 18) |
| Hardware | Colab GPU (CUDA), ~2 h wall clock |

## Evaluation (greedy decoding)

| Split | n | Exact match | JSON-valid | Schema-valid |
|---|---|---|---|---|
| `val` | 4,641 | **95.3%** | 99.1% | 99.1% |
| `test` (held out) | 4,641 | **95.2%** | 99.0% | 99.0% |
| `test_ood` | 4,775 | **94.2%** | 98.8% | 98.8% |

Latency, 1-thread CPU: p50 532 ms, p95 983 ms per query.

Of the 720 misses across all three splits, the largest buckets are top-K value
errors (209), action confusion (199), and invalid JSON (145); the rest are
filter/value/grouping mistakes. Training data is synthetic, so phrasings far
from its distribution will still degrade accuracy — `test_ood` is the honest
signal here, and it is 1.1 points below `val`.

## Intended use & limitations

- Intended: translating English questions about **nginx access/error logs**
  into DSL v0.1, **behind schema validation** (as the `logx` CLI does).
  Out-of-scope questions are trained to yield `{"action":"abstain"}`.
- Not intended: general text generation, other log formats, other languages,
  or use of raw outputs without validation (~1% of outputs are invalid, ~5%
  are wrong — validate, and show the DSL to the user before acting on it).
- The model only *translates*; it never executes anything. Execution safety
  (read-only allowlist, shell-free, injection-proof value passing) lives in
  [src/executor.py](src/executor.py) and is enforced regardless of what the
  model emits.
