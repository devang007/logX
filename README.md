# logX

**Query your nginx logs in plain English — fully offline, read-only, 15M params.**

```console
$ logx -q "top 5 ips" -src /var/log/nginx/access.log
logx: {"action":"top","source":"nginx_access","group_by":"ip","top_k":5}
  412 10.0.0.2
  301 10.0.0.9
  ...

$ tail -n 100000 access.log | logx -q "how many 502s in the last hour"
$ tail -f access.log | logx -q "show POST requests with status 500"   # live
$ logx -q "top 5 ips" -src access.log.2.gz                            # rotated logs
```

A tiny fine-tuned T5 (15.57M params, [model card](MODEL_CARD.md)) translates
your question into a strict JSON DSL; a deterministic executor compiles that
into a read-only `awk` pipeline. **No network calls, no data egress, no
shell** — your logs never leave the machine.

## Install

```bash
git clone https://github.com/devang007/logX && cd logX
./install.sh
```

That's it. The installer copies everything to `~/.local/lib/logx`, creates a
private venv, and downloads the released model weights (58 MB, sha256-verified
automatically). Make sure `~/.local/bin` is in your `PATH`.

Other options:

```bash
./install.sh --prefix /usr/local     # system-wide (may need sudo)
./install.sh --link                  # dev mode: symlinks + repo .venv
./install.sh --model-dir path/       # use your own checkpoint
./uninstall.sh                       # clean removal
```

Full manual: `man logx` (or `logx --manual`).

## What can it answer?

Four actions over **nginx access and error logs** (Apache combined format
also parses): show/filter matching lines, count (optionally grouped), and
top-K. Filters on ip, status, path, method, bytes, referer, user-agent,
level, client, message… with eq/ne/gte/lte/contains/regex, plus relative
(`last 15 minutes`) or absolute time windows.

Questions outside that scope make the model **abstain** (exit code 2) —
nothing runs on a guess.

## Trust model

- The model only *translates*; every output is schema-validated before
  anything executes. Invalid output → exit 3, nothing runs.
- Execution is a shell-free chain of allowlisted read-only binaries
  (`awk`, `sort`, `zcat`, …). Filter values are passed as `awk -v`
  variables, never interpolated into code — injection-proof by
  construction ([tests/test_executor.py](tests/test_executor.py) asserts
  this against hostile payloads).
- The DSL translation is echoed on stderr for every query, so you always
  see what was understood; audit with `--dsl` or `--cmd` before trusting.
- Exit codes are a contract: `0` ok · `1` usage error · `2` abstain ·
  `3` invalid translation · `4` pipeline failure.

## Accuracy

95.3% exact-match / 99.1% schema-valid on the validation set (n=4,641), and
94.2% / 98.8% on a held-out out-of-distribution set (n=4,775).
Details, training recipe, and honest limitations: [MODEL_CARD.md](MODEL_CARD.md).
The translation is a prediction — glance at the echoed DSL when it matters.

## Repo layout

```
install.sh, uninstall.sh    installer (model downloads from Releases)
src/                        CLI + DSL validation + read-only executor
schema/                     DSL v0.1 JSON Schema + field allowlists (source of truth)
man/logx.1                  the manual
tests/                      executor injection suite + DSL contract tests
```

Model weights ship as [Release assets](https://github.com/devang007/logX/releases),
never in git. Training happens in a separate private pipeline; each trained
version is released here with its model card.

## License

[Apache-2.0](LICENSE) — code and weights (base model
`google/t5-efficient-tiny` is Apache-2.0).
