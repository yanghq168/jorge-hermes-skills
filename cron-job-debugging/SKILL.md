---
name: cron-job-debugging
description: "Debug silently-failing Hermes cron jobs (no_agent script mode, scheduled prompt jobs, chained jobs). Diagnose 'Script not found', silent no-op, exit-code-without-output, and path-resolution failures by reading scheduler output logs in ~/.hermes/cron/output/. Applies the script-path resolution rule and the path-rewrite fix loop."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [cron, scheduler, debugging, troubleshooting, no_agent]
---

# Cron Job Debugging

Hermes cron jobs can fail silently — the scheduler writes a markdown report to
`~/.hermes/cron/output/<job_id>/<timestamp>.md`, but nothing surfaces in the
main conversation until the user notices a job isn't delivering. This skill
covers the diagnostic loop and the most common fixes.

## When to use

Load this skill when the user reports any of:
- "My scheduled job isn't running"
- "The [X] cron is failing"
- "I never got the [daily/weekly] digest"
- A no-agent script-mode job that was supposed to run at a specific time but produced nothing
- A scheduler output log file with `Status: script failed`

## The diagnostic loop (5 steps)

When a cron job is misbehaving, always run this loop in order. Don't skip
straight to "the script must be broken" — Hermes cron has its own failure
modes that don't surface until you read the output log.

### 1. List jobs and find the ID

```bash
hermes cron list
# or for cronjob tool user: cronjob(action='list')
```

Record the `job_id` (e.g. `077158d603ec`) and the configured `schedule`.

### 2. Read the most recent output log

Output logs are the source of truth for silent failures:

```bash
ls ~/.hermes/cron/output/<job_id>/ | tail -5
cat ~/.hermes/cron/output/<job_id>/<most-recent>.md
```

The log header always includes:
- `Job ID`, `Run Time`, `Mode` (agent vs `no_agent (script)`), `Status`

If `Status: script failed`, the **body of the log is the error message** — don't
just glance at the header.

### 3. Decode the common errors

| Log body | Meaning | Fix |
|----------|---------|-----|
| `Script not found: <path>` | Scheduler couldn't find the script | See "Script-path resolution" below |
| (empty body, agent mode) | The LLM hit an error before producing output | Re-run with `cronjob(action='run')` and watch stderr |
| Non-zero exit code | Script crashed | Run the script manually to see the traceback |
| (no log file at all) | Job didn't tick — scheduler down or paused | `hermes cron status` |
| Log says success but delivery failed | Job ran but couldn't reach the target | Check `delivery` config + target chat/channel |

### 4. Apply the Script-path resolution rule

**The most common silent-failure cause.** When you create or update a cron job
with `script=some/relative/path.sh`, the scheduler resolves it relative to
`~/.hermes/scripts/` (the Hermes scripts dir), NOT the directory the script
lives in. So a script at `~/.hermes/cron/scripts/skill-backup.sh` entered as
`script="cron/scripts/skill-backup.sh"` is looked for at
`~/.hermes/scripts/cron/scripts/skill-backup.sh` — which doesn't exist.

Diagnose by computing the expected path the scheduler uses and comparing it
to where the script actually lives:

```bash
HERMES_SCRIPTS="${HOME}/.hermes/scripts"
SCHED_PATH="$HERMES_SCRIPTS/<what-you-entered-as-script-field>"
ACTUAL="$(find ~/.hermes -name '<script-name>' -type f 2>/dev/null | head -1)"
echo "Scheduler looks at: $SCHED_PATH"
echo "Script actually at: $ACTUAL"
```

**Three fixes, pick whichever is cleanest for the deployment:**

1. **Change the cron job's `script` field to the absolute path** (preferred —
   survives refactors):
   ```python
   cronjob(action='update', job_id='<id>', script='/home/ubuntu/.hermes/cron/scripts/skill-backup.sh')
   ```
2. **Symlink the scheduler's expected path to the real one:**
   ```bash
   mkdir -p ~/.hermes/scripts/cron/scripts
   ln -sf /home/ubuntu/.hermes/cron/scripts/skill-backup.sh \
          ~/.hermes/scripts/cron/scripts/skill-backup.sh
   ```
3. **Move the script to the scheduler's expected location** (only if option 1
   and 2 don't fit).

Always re-run the job once after the fix:
```bash
hermes cron run <job_id>
cat ~/.hermes/cron/output/<job_id>/<newest>.md   # confirm success
```

### 5. Verify by triggering

```bash
cronjob(action='run', job_id='<id>')
# Wait a moment, then read the new log
ls -t ~/.hermes/cron/output/<job_id>/ | head -1 | xargs -I {} cat ~/.hermes/cron/output/<job_id>/{}
```

## Pitfalls

- **Headers lie, bodies don't.** A log can show `Status: script failed` but
  also contain the exact reason — read the body, not just the header line.

- **The script field is opaque.** The `cronjob` tool, `hermes cron list`, and
  the job-store JSON all show the script as you entered it. They do not tell
  you *how the scheduler will resolve it*. Always verify the resolved path
  yourself if a script-mode job is failing.

- **Profile context matters.** A no_agent script runs with HERMES_HOME pinned
  to the active profile's home. If you reference `~/.hermes/...` from inside
  such a script, it goes to the *profile* home, not the root home. Use
  `${HERMES_HOME}` env var or absolute paths inside cron scripts.

- **Scripts run with the scheduler's env, not your shell env.** Cron jobs do
  NOT inherit your interactive shell's PATH, alias, or sourced env vars. If
  a script depends on PATH, set PATH at the top of the script. If it needs
  `~/.ssh/jorge_server`, set the env var explicitly inside the script.

- **`hermes cron list` shows paused jobs only with `--all`.** A job you
  paused last week won't show in plain `cron list` and you'll waste an hour
  chasing a non-issue.

- **Multiple jobs can hit the same bug at once.** When one cron job's script
  path is wrong, check whether other jobs use the same path pattern — they
  almost certainly do. Fix all of them in one pass.

- **`cronjob(action='run')` runs once on the next tick, not immediately.**
  If you need synchronous verification, execute the script directly via
  terminal and read the log a moment later.

## Diagnostic commands cheatsheet

```bash
# List all jobs including paused
hermes cron list --all

# Check scheduler status
hermes cron status

# View the newest log for a job
LATEST=$(ls -t ~/.hermes/cron/output/<job_id>/ | head -1)
cat ~/.hermes/cron/output/<job_id>/$LATEST

# Find where a script actually lives
find ~/.hermes -name 'skill-backup.sh' -type f 2>/dev/null

# Check expected vs actual scheduler resolution
echo "Expected: ${HOME}/.hermes/scripts/<script-field-as-stored>"
test -f "${HOME}/.hermes/scripts/<script-field-as-stored>" && echo "OK" || echo "MISSING"

# Trigger the job manually
hermes cron run <job_id>

# Tail the most recent output file across all jobs
tail -n 20 ~/.hermes/cron/output/*/*.md | head -50
```
