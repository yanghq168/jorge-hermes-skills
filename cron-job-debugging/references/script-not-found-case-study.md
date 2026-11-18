# Case study: script-not-found cron failure

**Two incidents:** the original (July 2026, three jobs) and the recurrence
(2026-11-18, four jobs, five months of silent failure). The second one
invalidated the original's "fix pattern" — read the correction below before
applying anything from this file.

---

## Part 1 — The original incident (2026-07-04)

### Setup (root cause)
- Scripts live under `~/.hermes/cron/scripts/` and `~/.hermes/agency-backup/scripts/`
- Cron job `script` fields stored paths like `cron/scripts/skill-backup.sh`
  and `agency-backup/scripts/agency-backup.sh`
- Hermes scheduler resolves `script` relative to `~/.hermes/scripts/` —
  so the jobs looked for `~/.hermes/scripts/cron/scripts/skill-backup.sh`,
  which doesn't exist

### Jobs broken at the time

| job_id             | name                          | stored script path                                       |
|--------------------|-------------------------------|----------------------------------------------------------|
| `077158d603ec`     | Skills备份到GitHub             | `cron/scripts/skill-backup.sh`                           |
| `dbd63f6e525c`     | Agency备份到GitHub             | `agency-backup/scripts/agency-backup.sh`                 |
| `17dd48924a9f`     | 公众号情感长文                  | `cron/scripts/wechat-article-daily.py`                   |
| `2409bfc322fb`    | Hermes记忆数据每日备份          | (this one worked — uses `hermes-backup.sh` from `~/.hermes/scripts/` directly) |

The fourth one worked because its script happened to live in the exact
directory the scheduler uses by default — confirming the path-resolution rule.

### Log fingerprint

When a script-mode job fails this way, every run produces an identical log:

```
# Cron Job: Skills备份到GitHub

**Job ID:** 077158d603ec
**Run Time:** 2026-07-04 03:00:36
**Mode:** no_agent (script)
**Status:** script failed

Script not found: /home/ubuntu/.hermes/scripts/cron/scripts/skill-backup.sh
```

Recognition hint: the error message always contains `Script not found:` +
the absolute path the scheduler *tried* to load (not the path you stored).

### How this was diagnosed in-session

1. `cronjob list` → three identical jobs all in `Status: failed` (only visible
   if you read the output logs)
2. `ls ~/.hermes/cron/output/<job_id>/` and `cat` the newest `.md` files
3. Read the log body → saw the same `Script not found: ...` path three times,
   with the scheduler's resolved path different from where the scripts live
4. `find ~/.hermes -name '<script>'` confirmed real location

---

## Part 2 — The 2026-11-18 recurrence, and why the original fix is wrong

Four jobs failed with the identical error — and had been failing since
**2026-05-31**:

| job_id             | name                  | stored script path                        |
|--------------------|-----------------------|-------------------------------------------|
| `7e93716df129`    | 小红书周末出逃计划      | `cron/scripts/xhs-escape-weekend.py`      |
| `17dd48924a9f`    | 公众号情感长文          | `cron/scripts/wechat-article-daily.py`    |
| `077158d603ec`    | Skills备份到GitHub      | `cron/scripts/skill-backup.sh`            |
| `dbd63f6e525c`    | Agency备份到GitHub      | `agency-backup/scripts/agency-backup.sh`  |

**172 runs each, 172 `Script not found` each — zero successes, five months.**
The original incident's "fix" was applied to the job definitions but **never
actually worked** — it silently stayed broken.

### The diagnostic that settles it in one step

```bash
for j in <job_id1> <job_id2> ...; do
  tot=$(ls ~/.hermes/cron/output/$j/*.md 2>/dev/null | wc -l)
  nf=$(grep -l 'Script not found' ~/.hermes/cron/output/$j/*.md 2>/dev/null | wc -l)
  echo "$j total=$tot notfound=$nf"
done
```

If `total == notfound`, the script **never ran even once** — the fault is
100% path resolution and there is no point reading the script's code. If
`notfound < total`, some runs succeeded and you're looking at a *different*
bug (or the path was fixed mid-stream).

### ⚠️ Why "set the script field to the absolute path" no longer works

The original file recommended:

```python
cronjob(action='update', job_id='077158d603ec',
        script='/home/ubuntu/.hermes/cron/scripts/skill-backup.sh')
```

**As of 2026-11-18 this is rejected by the tool layer:**

```
Script path must be relative to ~/.hermes/scripts/. Got absolute or
home-relative path: '/home/ubuntu/.hermes/cron/scripts/skill-backup.sh'.
Place scripts in ~/.hermes/scripts/ and use just the filename.
```

### ⚠️ Why the symlink workaround doesn't work either

The obvious workaround is to symlink the expected path to the real one:

```bash
ln -sf /home/ubuntu/.hermes/cron/scripts/skill-backup.sh \
       ~/.hermes/scripts/cron/scripts/skill-backup.sh
```

**This fails for two independent reasons.**

**(a) The scheduler's path guard blocks it.** From `cron/scheduler.py`
(`_run_job_script()`, lines ~878-896):

```python
scripts_dir = _get_hermes_home() / "scripts"
scripts_dir_resolved = scripts_dir.resolve()

raw = Path(script_path).expanduser()
if raw.is_absolute():
    path = raw.resolve()
else:
    path = (scripts_dir / raw).resolve()

# Guard against path traversal, absolute path injection, and symlink
# escape — scripts MUST reside within HERMES_HOME/scripts/.
try:
    path.relative_to(scripts_dir_resolved)
except ValueError:
    return False, ("Blocked: script path resolves outside the scripts directory "
                   f"({scripts_dir_resolved}): {script_path!r}")
```

`Path.resolve()` **follows symlinks**, so the link resolves to
`~/.hermes/cron/scripts/skill-backup.sh`, which is outside
`~/.hermes/scripts/` ⇒ rejected with `Blocked: script path resolves
outside the scripts directory`. Verified directly:

```python
>>> sd = Path('/home/ubuntu/.hermes/scripts').resolve()
>>> (sd / 'cron/scripts/xhs-escape-weekend.py').resolve()
PosixPath('/home/ubuntu/.hermes/cron/scripts/xhs-escape-weekend.py')
>>> p.relative_to(sd)
ValueError   # → BLOCKED
```

**(b) Even if it passed, it splits the script's state file.** Python sets
`__file__` to the path *as invoked*, and `sys.path[0]` to the *resolved*
script directory. A script that derives its state-file location from
`os.path.dirname(os.path.abspath(__file__))` then writes into the **link
directory**, not the production directory. Observed with
`xhs-escape-weekend.py`:

```
# real dir  (production)
/home/ubuntu/.hermes/cron/scripts/.xhs_escape_visited.json   → 1 entry
# link dir  (accidental duplicate)
/home/ubuntu/.hermes/scripts/cron/scripts/.xhs_escape_visited.json → 2 entries
```

Two files, both growing, dedup broken across them. This is a *silent*
second failure hiding behind the path fix.

### ✅ The fix that works: a wrapper file in `~/.hermes/scripts/`

A **real file** (not a symlink) inside `~/.hermes/scripts/` survives
`resolve()`, and it can execute the production script by absolute path
while preserving the production script's runtime semantics.

**Python wrapper** (`~/.hermes/scripts/cron/scripts/<name>.py`):

```python
#!/usr/bin/env python3
"""Hermes cron wrapper for <name>.py

The Hermes scheduler resolves a no_agent job's `script` field against
HERMES_HOME/scripts/ and rejects any path that resolves outside that
directory (symlinks are followed by Path.resolve() and are rejected too).
This real file inside ~/.hermes/scripts/ executes the production script via
runpy with the REAL path so that:

* __file__    -> the real path (the script's own _SCRIPT_DIR logic keeps
                 pointing at ~/.hermes/cron/scripts/).
* sys.path[0] -> the real script's directory, so
                 `from config_loader import get_mail_config` still resolves.

Do NOT replace this with a symlink, and do NOT move the production script
here — either change breaks one of the two guarantees above.
"""
import os
import runpy
import sys

REAL_SCRIPT = "/home/ubuntu/.hermes/cron/scripts/<name>.py"

if not os.path.isfile(REAL_SCRIPT):
    sys.stderr.write(f"wrapper: target script missing: {REAL_SCRIPT}\n")
    raise SystemExit(2)

_real_dir = os.path.dirname(REAL_SCRIPT)
if _real_dir not in sys.path:
    sys.path.insert(0, _real_dir)

runpy.run_path(REAL_SCRIPT, run_name="__main__")
```

**Shell wrapper** (`~/.hermes/scripts/cron/scripts/<name>.sh`):

```bash
#!/bin/bash
# Hermes cron wrapper for <name>.sh
# Do NOT replace this with a symlink.
exec bash /home/ubuntu/.hermes/cron/scripts/<name>.sh
```

Then point the job at the wrapper with a **relative** path:

```python
cronjob(action='update', job_id='<id>', script='cron/scripts/<name>.py')
```

### 🔴 The one verification that counts

Do not verify with `ls` — that proves existence, not runnability. Drive the
scheduler's own entry point, which reproduces the full chain (resolve →
guard → existence → interpreter choice → `cwd=path.parent` → `HERMES_HOME`/
`HOME` env):

```bash
cd ~/.hermes/hermes-agent && python3 -c "
import sys; sys.path.insert(0, '/home/ubuntu/.hermes/hermes-agent')
from cron.scheduler import _run_job_script
ok, out = _run_job_script('cron/scripts/<name>.py')
print('success:', ok); print(out[:800])
"
```

Expected on a healthy job: `success: True` plus the script's stdout.

**Interpreting the result:** a job whose only remaining failure is
`SMTPServerDisconnected` / `535` has a **fixed path** — the script ran all
the way to the network call. That is a PASS for the path fix, and the SMTP
failure is a separate, already-documented credential problem. Don't conflate
them.

### ⚠️ Testing the wrapper consumes production state

Running a wrapper executes the real production script, which will:
- consume a dedup-pool entry (e.g. `.xhs_escape_visited.json`),
- write an extra product file (e.g. `article-wechat-<date>-<hash>.md`),
- push an extra notification.

**Restore after testing:**
```bash
# remove extra products
rm -f /home/ubuntu/article-wechat-<today>-*.md
# restore the dedup state file to its pre-test value
# (check `stat -c '%y'` for the original, then write the original content back)
```
And always confirm no split state file was created:
```bash
ls -la ~/.hermes/cron/scripts/.<name>_visited.json \
       ~/.hermes/scripts/cron/scripts/.<name>_visited.json 2>&1
```
The link-dir copy must NOT exist. If it does, delete it and restore the real one.

### 🔴 Fixing the path can uncover duplicate scheduling

A never-running job was harmless. Once it runs, check for a classic-crontab
twin before declaring victory:

```bash
crontab -l | grep -E '<script-name>'
```

Distinguish the two cases:
- **agent-mode** Hermes job + classic cron on the same script ⇒ usually fine
  (the agent audits rather than regenerates). Confirm by counting artifacts:
  `ls -1 ~/.hermes/cron/outbox/<platform>/<today>*.html | wc -l` should be 1.
- **no_agent** Hermes job + classic cron on the same script ⇒ **real
  double-fire**. On 2026-11-18 this applied to `wechat-article-daily.py`
  (classic 22:00 vs Hermes 07:00) and `skill-backup.sh` (classic 03:00 vs
  Hermes 03:00 — same minute).

Back up the crontab before editing, and ask the user which scheduler to keep
— classic-cron entries also drive scripts that have NO Hermes job:

```bash
crontab -l > /tmp/crontab_backup_$(date +%Y%m%d_%H%M).txt
```

---

## Adjacent signal — same bug elsewhere

If a cron job in the user's content-platforms pipeline is failing with a
generic-looking "backup failed" or "email not sent" message that's a no-op,
check the underlying cron logs for `Script not found:` before assuming the
content script itself is buggy. Several content jobs (wechat-article-daily,
unified-content-daily, xhs-travel-daily, etc.) live in the same
`~/.hermes/cron/scripts/` dir and are subject to the same path-resolution
trap.
