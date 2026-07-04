# Case study: script-not-found cron failure (权权, July 2026)

The first time this came up, three cron jobs were silently broken at once.
Capturing the exact transcript so future sessions don't have to re-derive the
diagnosis from scratch.

## Setup (root cause)
- Scripts live under `~/.hermes/cron/scripts/` and `~/.hermes/agency-backup/scripts/`
- Cron job `script` fields stored paths like `cron/scripts/skill-backup.sh`
  and `agency-backup/scripts/agency-backup.sh`
- Hermes scheduler resolves `script` relative to `~/.hermes/scripts/` —
  so the jobs looked for `~/.hermes/scripts/cron/scripts/skill-backup.sh`,
  which doesn't exist

## Jobs broken at the time

| job_id             | name                          | stored script path                                       |
|--------------------|-------------------------------|----------------------------------------------------------|
| `077158d603ec`     | Skills备份到GitHub             | `cron/scripts/skill-backup.sh`                           |
| `dbd63f6e525c`     | Agency备份到GitHub             | `agency-backup/scripts/agency-backup.sh`                 |
| `17dd48924a9f`     | 公众号情感长文                  | `cron/scripts/wechat-article-daily.py`                   |
| `2409bfc322fb`    | Hermes记忆数据每日备份          | (this one worked — uses `hermes-backup.sh` from `~/.hermes/scripts/` directly) |

The fourth one worked because its script happened to live in the exact
directory the scheduler uses by default — confirming the path-resolution rule.

## Log fingerprint

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

## How this was diagnosed in-session

1. `cronjob list` → three identical jobs all in `Status: failed` (only visible
   if you read the output logs)
2. `ls ~/.hermes/cron/output/<job_id>/` and `cat` the newest `.md` files
3. Read the log body → saw the same `Script not found: ...` path three times,
   with the scheduler's resolved path different from where the scripts live
4. `find ~/.hermes -name '<script>'` confirmed real location

## The fix pattern

After diagnosis, fix all three jobs in one batch using absolute paths:

```python
cronjob(action='update',
        job_id='077158d603ec',
        script='/home/ubuntu/.hermes/cron/scripts/skill-backup.sh')

cronjob(action='update',
        job_id='dbd63f6e525c',
        script='/home/ubuntu/.hermes/agency-backup/scripts/agency-backup.sh')

cronjob(action='update',
        job_id='17dd48924a9f',
        script='/home/ubuntu/.hermes/cron/scripts/wechat-article-daily.py')
```

Then verify each one:

```bash
hermes cron run 077158d603ec
sleep 5
cat $(ls -t ~/.hermes/cron/output/077158d603ec/ | head -1 | xargs -I{} echo ~/.hermes/cron/output/077158d603ec/{})
```

Expect `Status: success` and a body that shows the script's actual stdout
(e.g. `📦 技能备份 - <timestamp>` for the skills backup).

## Adjacent signal — same bug elsewhere

If a cron job in the user's content-platforms pipeline is failing with a
generic-looking "backup failed" or "email not sent" message that's a no-op,
check the underlying cron logs for `Script not found:` before assuming the
content script itself is buggy. Several content jobs (wechat-article-daily,
unified-content-daily, xhs-travel-daily, etc.) live in the same
`~/.hermes/cron/scripts/` dir and are subject to the same path-resolution
trap.
