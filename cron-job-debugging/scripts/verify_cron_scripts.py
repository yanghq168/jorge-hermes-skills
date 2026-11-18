#!/usr/bin/env python3
"""Verify that Hermes no_agent cron jobs can actually EXECUTE their script.

`ls` proves a script exists; it does NOT prove the scheduler can run it.
This drives the scheduler's own entry point (`_run_job_script`), which
reproduces the full chain:

    resolve() -> directory guard -> existence -> interpreter choice
              -> cwd=path.parent -> HERMES_HOME/HOME env

Usage
-----
  # verify every no_agent job that has a script
  python3 verify_cron_scripts.py

  # verify specific script paths (as stored in the job's `script` field)
  python3 verify_cron_scripts.py cron/scripts/xhs-escape-weekend.py \
                                   cron/scripts/skill-backup.sh

  # machine-readable
  python3 verify_cron_scripts.py --json

Exit codes
----------
  0 = every job resolved AND its script ran successfully (or failed only
      on a downstream step like SMTP auth)
  1 = at least one job's script FAILED to execute
  2 = usage / environment error (Hermes checkout not found, etc.)

Reading the result
------------------
A job that fails with `SMTPServerDisconnected` / `535 Login fail` has a
**correct path** — the script ran all the way to its network call. That is
a PASS for path resolution; the credential failure is a separate problem
(see references/smtp-credential-failure-case-study.md). This script
distinguishes the two and reports them separately.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
HERMES_AGENT = Path(os.environ.get("HERMES_AGENT_DIR", HERMES_HOME / "hermes-agent"))
JOBS_JSON = HERMES_HOME / "cron" / "jobs.json"


def load_runner():
    """Import the scheduler's own _run_job_script, or fail loudly."""
    if not HERMES_AGENT.is_dir():
        print(f"ERROR: Hermes checkout not found at {HERMES_AGENT}", file=sys.stderr)
        print("       Set HERMES_AGENT_DIR to override.", file=sys.stderr)
        raise SystemExit(2)
    sys.path.insert(0, str(HERMES_AGENT))
    try:
        from cron.scheduler import _run_job_script  # type: ignore
    except Exception as exc:  # pragma: no cover
        print(f"ERROR: cannot import cron.scheduler: {exc!r}", file=sys.stderr)
        raise SystemExit(2)
    return _run_job_script


def job_scripts():
    """Return [(name, script_field)] for every job with a script field."""
    if not JOBS_JSON.exists():
        return []
    data = json.loads(JOBS_JSON.read_text(encoding="utf-8"))
    jobs = data if isinstance(data, list) else data.get("jobs", [])
    out = []
    for j in jobs:
        s = j.get("script")
        if s:
            out.append((j.get("name") or j.get("job_id") or "?", s))
    return out


# Failure signatures that mean "the path worked, the script ran, but a
# DOWNSTREAM step failed" — these are NOT path failures.
DOWNSTREAM_MARKERS = (
    "SMTPServerDisconnected",
    "535 Login fail",
    "SMTPRecipientsRefused",
    "Connection unexpectedly closed",
)


def classify(ok, out):
    """Return (verdict, reason)."""
    if ok:
        return "PASS", "script executed successfully"
    text = out or ""
    if any(m in text for m in DOWNSTREAM_MARKERS):
        return "PASS_PATH", "path OK - script ran, failed later on a DOWNSTREAM step (SMTP/credential)"
    return "FAIL", "script could not execute"


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("scripts", nargs="*", help="script fields to verify (default: all jobs)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--full", action="store_true", help="print the whole output, not just the head")
    args = ap.parse_args()

    runner = load_runner()

    targets = (
        [(f"<arg:{s}>", s) for s in args.scripts]
        if args.scripts
        else job_scripts()
    )
    if not targets:
        print("No script-mode jobs found (nothing to verify).", file=sys.stderr)
        return 0

    results = []
    hard_fail = 0
    for name, script in targets:
        ok, out = runner(script)
        verdict, reason = classify(ok, out)
        if verdict == "FAIL":
            hard_fail += 1
        results.append({
            "name": name,
            "script": script,
            "verdict": verdict,
            "reason": reason,
            "output": out if args.full else (out or "")[:600],
        })

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        width = max(len(r["script"]) for r in results)
        for r in results:
            print("[{:9}] {}  {}".format(r["verdict"], r["script"].ljust(width), r["name"]))
            print("             {}".format(r["reason"]))
            if r["verdict"] == "FAIL":
                for line in (r["output"] or "").strip().splitlines()[:12]:
                    print("             | {}".format(line))
            print()

    print("summary: {} checked, {} hard failure(s)".format(len(results), hard_fail))
    if hard_fail:
        print("\nFix: create a WRAPPER file in ~/.hermes/scripts/ (see")
        print("references/script-not-found-case-study.md). Absolute paths and")
        print("symlinks are both rejected by the scheduler's resolve() guard.")
    return 1 if hard_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
