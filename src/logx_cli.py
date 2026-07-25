#!/usr/bin/env python
"""logx — query nginx logs in plain English.

    logx -q "top 5 ips" -src /var/log/nginx/access.log
    tail -n 5000 access.log | logx -q "how many 500 errors"
    logx --dsl -q "count 404s in the last hour"      # print DSL, don't run

Thin CLI over the LogLingo model + executor: NL -> DSL (local seq2seq model)
-> schema validation -> confidence gate -> read-only, shell-free pipeline.
Results go to stdout; the DSL translation is echoed on stderr so stdout can
be piped onward. See man page (logx --manual) for details.

Runs from three layouts without configuration:
  repo checkout        src/logx_cli.py, model at runs/poc/best
  linked install       $LOGX_HOME/{src,schema,model,venv} symlinked to repo
  copied install       same tree, real files (self-contained)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

__version__ = "0.2.0"

TASK_PREFIX = "parse: "
MAX_SOURCE_LEN = 64
MAX_TARGET_LEN = 128

# resolve() follows the link-mode symlink back to the repo, so BASE is the
# repo root there and $LOGX_HOME in a copied install — both hold src/ + schema/
_HERE = Path(__file__).resolve().parent
BASE = Path(os.environ.get("LOGX_HOME") or _HERE.parent)
sys.path.insert(0, str(_HERE))

EXIT_OK, EXIT_ERROR, EXIT_ABSTAIN, EXIT_INVALID, EXIT_EXEC = 0, 1, 2, 3, 4


class Parser(argparse.ArgumentParser):
    def error(self, message):  # argparse defaults to exit 2; 2 means abstain here
        self.exit(EXIT_ERROR, f"{self.prog}: error: {message}\n")


def default_model_dir() -> Path | None:
    for cand in (BASE / "model", BASE / "runs" / "poc" / "best"):
        if (cand / "config.json").is_file():
            return cand
    return None


def load_model(model_dir: str):
    os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(model_dir)
    model = AutoModelForSeq2SeqLM.from_pretrained(model_dir).eval()
    return tok, model


def predict(tok, model, nl: str) -> tuple[str, float]:
    """Greedy decode; returns (text, mean token logprob as confidence)."""
    import torch

    enc = tok(TASK_PREFIX + nl, return_tensors="pt", truncation=True, max_length=MAX_SOURCE_LEN)
    with torch.no_grad():
        out = model.generate(
            **enc,
            max_length=MAX_TARGET_LEN,
            return_dict_in_generate=True,
            output_scores=True,
        )
    text = tok.decode(out.sequences[0], skip_special_tokens=True).strip()
    scores = model.compute_transition_scores(out.sequences, out.scores, normalize_logits=True)
    mask = out.sequences[:, 1:] != tok.pad_token_id
    conf = float(scores[0][mask[0]].mean()) if mask[0].any() else float("-inf")
    return text, conf


def run_stream(segments: list[list[str]]) -> int:
    """Run the pipeline with stdin as the log source and stdout inherited.

    The final stage writes straight to our stdout, so `tail -f | logx` streams
    show/filter results live (count/top aggregate in awk's END block and need
    the input to finish). No timeout: the stream decides when input ends.
    """
    procs: list[subprocess.Popen] = []
    prev = sys.stdin.buffer
    try:
        for i, argv in enumerate(segments):
            last = i == len(segments) - 1
            proc = subprocess.Popen(
                argv,
                stdin=prev,
                stdout=None if last else subprocess.PIPE,
                stderr=subprocess.DEVNULL if not last else None,
            )
            if prev is not sys.stdin.buffer:
                prev.close()  # upstream sees SIGPIPE on early exit (limit hit)
            prev = proc.stdout
            procs.append(proc)
        rc = procs[-1].wait()
        for proc in procs[:-1]:
            proc.wait(timeout=5)
        return EXIT_OK if rc == 0 else EXIT_EXEC
    except KeyboardInterrupt:
        for proc in procs:
            proc.kill()
        print(file=sys.stderr)
        return 130


def show_manual() -> int:
    for cand in (BASE / "man" / "logx.1", _HERE.parent / "logx" / "man" / "logx.1"):
        if cand.is_file():
            os.execvp("man", ["man", str(cand)])
    print("logx: man page not found", file=sys.stderr)
    return EXIT_ERROR


def main(argv=None) -> int:
    ap = Parser(
        prog="logx",
        description="Query nginx logs in plain English (local model, read-only execution).",
        epilog='examples:\n'
               '  logx -q "top 5 ips" -src access.log\n'
               '  tail -n 5000 access.log | logx -q "how many 500 errors"\n'
               '  logx --dsl -q "count 404s in the last hour"\n'
               'full manual: logx --manual  (or: man logx)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("query_pos", nargs="?", metavar="QUERY", help=argparse.SUPPRESS)
    ap.add_argument("-q", "--query", help="natural-language question about the logs")
    ap.add_argument("-src", "--src", dest="src", metavar="FILE",
                    help="log file to query ('-' = stdin; .gz ok; default: stdin if piped, "
                         "else /var/log/nginx/{access,error}.log)")
    ap.add_argument("--dsl", action="store_true", help="print the DSL JSON and exit (no execution)")
    ap.add_argument("--cmd", action="store_true", help="print the equivalent shell pipeline and exit")
    ap.add_argument("-x", "--explain", action="store_true",
                    help="also print confidence and pipeline to stderr before running")
    ap.add_argument("-Q", "--quiet", action="store_true", help="suppress the DSL echo on stderr")
    ap.add_argument("--conf-threshold", type=float,
                    default=float(os.environ.get("LOGX_CONF_THRESHOLD", "-1.0")),
                    help="mean-logprob gate; below this the query is treated as abstain (default %(default)s)")
    ap.add_argument("--model-dir", default=os.environ.get("LOGX_MODEL_DIR"),
                    help="override the bundled model directory")
    ap.add_argument("--timeout", type=float, default=30.0,
                    help="pipeline timeout in seconds, file mode only (default %(default)s)")
    ap.add_argument("--manual", action="store_true", help="open the full manual page")
    ap.add_argument("--version", action="version", version=f"logx {__version__}")
    args = ap.parse_args(argv)

    if args.manual:
        return show_manual()

    query = args.query or args.query_pos
    if not query:
        ap.error("a query is required: logx -q \"top 5 ips\" (see logx --help)")
    if args.query and args.query_pos:
        ap.error("query given twice (positional and -q)")

    # input source: explicit file > explicit '-' > piped stdin > nginx defaults
    log_path, stdin_mode = args.src, False
    if log_path == "-":
        log_path, stdin_mode = None, True
    elif log_path is None and not sys.stdin.isatty():
        stdin_mode = True
    elif log_path and not Path(log_path).is_file():
        print(f"logx: log file not found: {log_path}", file=sys.stderr)
        return EXIT_ERROR

    model_dir = args.model_dir or default_model_dir()
    if not model_dir:
        print("logx: no model found — reinstall logx or set LOGX_MODEL_DIR", file=sys.stderr)
        return EXIT_ERROR

    if sys.stderr.isatty() and not args.quiet:
        print("logx: loading model…", end="\r", file=sys.stderr, flush=True)
    tok, model = load_model(str(model_dir))
    text, conf = predict(tok, model, query)
    if sys.stderr.isatty() and not args.quiet:
        print(" " * 24, end="\r", file=sys.stderr)  # clear the loading line

    import dsl_common
    import executor as executor_mod
    from executor import AbstainError, ExecutorError

    try:
        dsl = dsl_common.canonicalize(json.loads(text))
        dsl_common.validate_dsl(dsl)
    except (json.JSONDecodeError, dsl_common.DSLValidationError) as exc:
        print(f"logx: model output is not valid DSL ({exc})\nlogx: raw output: {text!r}",
              file=sys.stderr)
        return EXIT_INVALID

    if conf < args.conf_threshold:
        print(f"logx: confidence {conf:.3f} below threshold {args.conf_threshold} — refusing to run",
              file=sys.stderr)
        return EXIT_ABSTAIN
    if dsl["action"] == "abstain":
        print("logx: can't express that as a log query — try rephrasing "
              "(supported: show / filter / count / top over nginx access+error logs)",
              file=sys.stderr)
        return EXIT_ABSTAIN

    if args.dsl:
        print(dsl_common.to_target(dsl))
        return EXIT_OK

    try:
        display_cmd = executor_mod.build_command(dsl, log_path="<stdin>" if stdin_mode else log_path)
    except ExecutorError as exc:
        print(f"logx: DSL valid but not executable: {exc}", file=sys.stderr)
        return EXIT_INVALID
    if args.cmd:
        print(display_cmd)
        return EXIT_OK

    if not args.quiet:
        print(f"logx: {dsl_common.to_target(dsl)}", file=sys.stderr)
        if args.explain:
            print(f"logx: confidence {conf:.3f}\nlogx: {display_cmd}", file=sys.stderr)

    try:
        if stdin_mode:
            segments, _ = executor_mod.build_pipeline(dsl, log_path="-")
            return run_stream(segments)
        out = executor_mod.execute(dsl, log_path=log_path, timeout=args.timeout)
        sys.stdout.write(out if out.strip() else "(no matching lines)\n")
        return EXIT_OK
    except AbstainError as exc:
        print(f"logx: {exc}", file=sys.stderr)
        return EXIT_ABSTAIN
    except ExecutorError as exc:
        print(f"logx: {exc}", file=sys.stderr)
        return EXIT_EXEC


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except BrokenPipeError:  # e.g. `logx ... | head`
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        sys.exit(EXIT_OK)
