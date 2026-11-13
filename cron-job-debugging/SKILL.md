---
name: cron-job-debugging
description: "Debug silently-failing Hermes cron jobs (no_agent script mode, scheduled prompt jobs, chained jobs). Diagnose 'Script not found', silent no-op, exit-code-without-output, path-resolution failures, AND credential/SMTP delivery failures by reading scheduler output logs in ~/.hermes/cron/output/. Applies the script-path resolution rule, the SMTP-credential deep-dive, and the local-fallback save pattern."
version: 1.5.0
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
| `Connection unexpectedly closed` / `SMTPServerDisconnected` | Almost always a **credential/transport failure**, not a network blip | See "SMTP/credential failure deep-dive" below |
| `535 Login fail` / `535 Authentication failed` | SMTP auth code / password is wrong or expired | See "SMTP/credential failure deep-dive" below |

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

### 5. SMTP / credential failure deep-dive (delivery-side silent failures)

The other common silent-failure class: the script runs, prints `❌ 发送失败: Connection unexpectedly closed`, exits 0 — and nothing reaches the inbox. The cryptic "connection closed" hides the real cause (almost always auth).

**The trap**: Python's `smtplib` re-raises the server's *post-AUTH* socket teardown as a generic `SMTPServerDisconnected("Connection unexpectedly closed")`. The real rejection is buried in the server transcript a few lines earlier. You cannot see it from the script's stdout.

**Step 1 — Reproduce with debug output to surface the real error:**

```bash
cd ~/.hermes/cron/scripts
python3 -c "
import smtplib, socket
from email.mime.text import MIMEText
socket.setdefaulttimeout(30)
smtplib.SMTP.debuglevel = 1
with smtplib.SMTP_SSL('<smtp_server>', 465, timeout=30) as s:
    s.login('<user>', '<pass>')
    s.sendmail('<user>', '<to>', 'Subject: t\n\ntest')
"
```

Look at the `reply:` lines. The smoking gun is one of:

- `535 Login fail. Account is abnormal, service is not open, password is incorrect, login frequency limited...` — **auth code/password is wrong, expired, or service not enabled**. Cannot be fixed remotely; user must log into the mail provider's web UI and regenerate. This is the **expected default for QQ Mail** when an SMTP authorization code has been revoked — see the dedicated callout below.
- `550 Mailbox not found` / `User not found` — recipient address wrong, or sender not authorized to send as that address.
- `554 DT:SPM ...` (QQ specific) — message body rejected as spam; shorten subject, remove URL shorteners, or fix plain-text/HTML mismatch.
- `454 4.7.0 Too many login attempts` — rate-limited; back off and try later, or stop running the script from multiple places.

**Most reliable probe — manual AUTH LOGIN + `getreply()` per step.** When `debuglevel=1` buries the 535 inside AUTH retries, drive the SMTP session yourself so each protocol step produces its own line:

```bash
python3 -c "
import smtplib, base64
s = smtplib.SMTP_SSL('smtp.qq.com', 465, timeout=15)
s.ehlo()
s.send(b'AUTH LOGIN\r\n'); code, msg = s.getreply(); print(f'AUTH LOGIN  -> {code} {msg!r}')
s.send(base64.b64encode(b'USER') + b'\r\n'); code, msg = s.getreply(); print(f'username   -> {code} {msg!r}')
s.send(base64.b64encode(b'PASS') + b'\r\n'); code, msg = s.getreply(); print(f'password   -> {code} {msg!r}')
"
```

On this deployment with a revoked auth code, the third `getreply()` prints:

```
password -> 535 b'Login fail. Account is abnormal, service is not open, password is incorrect, login frequency limited, or system is busy. ...'
```

Always deterministic. No scrolling past fast output, no second AUTH retry muddying the transcript. See Case I for the full transcript + the AUTH-recipe patch history.

**⚠️ QQ Mail default failure shape (Case A — explicit 535):** For this QQ deployment, the most common signature when an SMTP authorization code has been revoked is a **visible `535 Login fail. Account is abnormal, service is not open, password is incorrect, login frequency limited, or system is busy.` line in the SMTP transcript** between the AUTH command and the bare `SMTPServerDisconnected`. `smtplib.SMTP.debuglevel = 1` will usually surface it, but `smtplib` retries AUTH LOGIN after AUTH PLAIN fails with 535, and the second AUTH closes abruptly — the 535 can scroll past fast. **More reliable recipe — do AUTH LOGIN manually and call `getreply()` after each step so the 535 is its own line** (recipe above).

**Rarer edge case — QQ silent-reject (Case B, no 535 in transcript):** When QQ's anti-spam system has *aggressively* revoked an auth code, the server may close the TLS socket IMMEDIATELY after `AUTH` with NO `reply:` line at all — `debuglevel=1` will show a clean `EHLO 250` then a bare `SMTPServerDisconnected` with no `535` between them. This is indistinguishable from a network drop except by the pattern: SSL handshake + EHLO succeed + AUTH never gets a reply → credential revoked by aggressive anti-spam (not just expired). Same user fix (regenerate in QQ web UI), but the diagnostic signature is different — don't conclude "network issue" just because the 535 line is missing. Confirm by trying port 587 STARTTLS as well: if EHLO succeeds there too and AUTH dies silently, it's the same silent-reject. If port 587 hangs at connect, you have a real firewall/network problem instead. The manual AUTH recipe above also makes this case unambiguous — the third `getreply()` returns `(0, b'')` or raises before printing anything if the server tore down the socket.

**Faster path — run `scripts/probe_smtp.py`** instead of retyping the debuglevel recipe. It auto-detects which credential sources this Hermes deployment uses (`config.yaml` + `~/.hermes/.env`), runs both 465-SSL and 587-STARTTLS probes, and reports which of the three failure modes you're in: 535-in-transcript (Case A), no-reply-silent-reject (Case B), or connect-time failure (Case C). Exit 0 = auth dead, exit 1 = real network problem. See `references/smtp-credential-failure-case-study.md` for the full Case B transcript.

**Step 2 — Verify the credential actually matches what's stored.** Cron scripts read from `~/.hermes/cron/config/config.yaml` (via the standard `config_loader.py`). They do NOT inherit your interactive shell's env vars. So if your working theory is "the env-var auth code works but the YAML one doesn't" — check both:

```bash
# What's in the config file
grep -A1 smtp_pass ~/.hermes/cron/config/config.yaml
# What's in the env (if the script reads os.environ)
env | grep -iE "smtp|auth_code|mail_pass"
# Which one is the script actually using?
grep -nE "smtp_pass|os\.environ|SMTP_PASS" ~/.hermes/cron/scripts/<script>.py | head
```

In Hermes' standard pattern (`from config_loader import get_mail_config`), the YAML wins over env. If both are wrong, the fix is the YAML; env vars are only a fallback inside the `try/except ImportError` block.

**Step 3 — Try the alternate transport.** Port 465 (SMTPS/SSL) and port 587 (STARTTLS) are independent — one can be blocked by the host firewall while the other works. If 465 fails, retry with `smtplib.SMTP('host', 587)` + `.starttls()`. If both fail with the same `535`, the credential is dead regardless of transport.

**Step 4 — Save locally as a fallback so today's content isn't lost.** While waiting for the user to fix the credential, persist the generated output so the article/digest is still recoverable:

```python
# Inside the cron script's main(), BEFORE send_email(), or in a wrapper:
import os
from datetime import datetime
out_dir = os.path.expanduser('~/.hermes/cron/output')
os.makedirs(out_dir, exist_ok=True)
ts = datetime.now().strftime('%Y-%m-%d_%H-%M')
with open(f'{out_dir}/<script>_{ts}.html', 'w', encoding='utf-8') as f:
    f.write(full_html)
with open(f'{out_dir}/<script>_{ts}.txt', 'w', encoding='utf-8') as f:
    f.write(plain_text)
```

Then in the failure report, point the user at the saved file. This is the difference between "today's content is gone" and "today's content is on disk, please fix auth."

### 6. Tiered fallback: retry transient, then save locally on hard failure

Step 4's "save before send" is the right pattern for content that takes a long time to generate. But most cron scripts already have the content in memory by the time they call `send_email()`, and saving-then-attempting-then-re-saving-on-failure is two writes of the same bytes. A tighter pattern that works well in practice:

**a. Retry transient `SMTPServerDisconnected` once with a 3s backoff.** Most 535 / socket-teardown failures are NOT transient — but a real network blip looks identical to a credential failure from the script's side. One cheap retry distinguishes them and recovers the rare real-blip case without hiding real auth failures.

```python
import time
last_err = None
for attempt in range(2):
    try:
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=15) as server:
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, TO_EMAIL, msg.as_string())
        return True, "发送成功"
    except (smtplib.SMTPServerDisconnected, smtplib.SMTPException, OSError) as e:
        last_err = e
        if attempt == 0:
            time.sleep(3)
        continue
```

**b. On final failure, save to a dedicated outbox.** Don't reuse `~/.hermes/cron/output/<job_id>/` — that's the scheduler's log dir and gets confused with run records. Use `~/.hermes/cron/outbox/<platform>/` (one subdir per delivery platform: `toutiao/`, `wechat/`, `email/`):

```python
from pathlib import Path
from datetime import datetime
outbox = Path("/home/ubuntu/.hermes/cron/outbox/toutiao")
outbox.mkdir(parents=True, exist_ok=True)
ts = datetime.now().strftime("%Y%m%d_%H%M")
fname = outbox / f"{ts}_{topic['direction']}.html"
fname.write_text(full_html, encoding="utf-8")
return False, f"{last_err} (重试2次仍失败，HTML已备份: {fname})"
```

**c. Tell the user where the backup is in the failure message.** The whole point is that today's content isn't lost while the credential gets fixed. Embed the absolute path in the script's stderr so the failure report can show "HTML saved to /home/ubuntu/.hermes/cron/outbox/toutiao/20260825_2031_亲戚恩怨.html" and the user can open it.

**Working example**: `~/.hermes/cron/scripts/toutiao-article-daily.py::send_email()` after the 2026-08-25 fix — read it directly as the reference implementation.

### 7. Verify by triggering

```bash
cronjob(action='run', job_id='<job_id>')
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

- **A `no_agent` script that exits 0 can still show `last_status: error`.**
  This is a platform reporting bug, not a script bug — the mirror image of the
  `last_status=ok` masking case below. Tell-tale signs: `last_status: error`
  but `last_run_at` advancing normally, `last_delivery_error: null`, and the
  script's own log showing ✅. **Trust the script's own log and the outbox,
  not the scheduler's status field** — it is unreliable in *both* directions.
  Confirm with `python3 ~/.hermes/cron/scripts/<script>.py; echo "Exit: $?"`
  before assuming anything is broken. Known false-reporters on this deployment:
  `xhs-escape-weekend.py`, `wechat-article-daily.py`, `skill-backup.sh`,
  `agency-backup.sh`. Details in
  `references/no-agent-false-error-reporting.md`.

- **`last_status: error` cannot distinguish "false report" from "partial
  success".** A `no_agent` script that produced its output but then failed
  delivery exits non-zero — so the scheduler's `error` is *accurate*, yet the
  work product is safe on disk. Verified 2026-10-28: `wechat-article-daily.py`
  logs `❌ 邮件发送失败` **and** `✅ MD文件已生成`, and
  `/home/ubuntu/article-wechat-*.md` has a fresh file every night, while
  `jobs.json` shows `last_status: error`. **Always check for the artifact
  before re-running** (`ls -lt ~/.hermes/cron/outbox/<platform>/*.html`,
  `ls -lt /home/ubuntu/article-*.md`). If a product exists, the production
  step succeeded — fix only the delivery channel, and do NOT re-run the
  script (a second run generates different content and creates a second
  backup). Three-way triage — false report / partial success / total failure —
  in `references/no-agent-false-error-reporting.md`.

- **Multiple jobs can hit the same bug at once.** When one cron job's script
  path is wrong, check whether other jobs use the same path pattern — they
  almost certainly do. Fix all of them in one pass.

- **`cronjob(action='run')` runs once on the next tick, not immediately.**
  If you need synchronous verification, execute the script directly via
  terminal and read the log a moment later.

- **`Connection unexpectedly closed` is almost never a real network issue.**
  Python's `smtplib` reports the server's post-AUTH socket teardown as that
  generic error. The actual cause (535, rate limit, blocked port) is in the
  SMTP transcript one level deeper. Turn on `smtplib.SMTP.debuglevel = 1`
  (or better: drive the SMTP session manually with `AUTH LOGIN` + `getreply()`
  per step — see Case I) and re-read the `reply:` lines before assuming
  connectivity is the problem.
  See the "SMTP / credential failure deep-dive" section for the full recipe.

- **`debuglevel=2` is NOT a "more verbose" upgrade — it can still bury the
  535.** Both `debuglevel=1` and `debuglevel=2` rely on Python's smtplib to
  walk through the AUTH negotiation, and Python retries with AUTH LOGIN after
  AUTH PLAIN fails with 535. The second AUTH closes abruptly and your
  terminal scrolls past the actual rejection. The only deterministic recipe
  for surface-the-535 on QQ is the manual `server.send(b"AUTH LOGIN\r\n");
  server.getreply()` per step pattern from Case I. Verified 2026-09-09
  (failure #15): `debuglevel=2` + `SMTP_SSL(...)` reproduces the exact same
  buries-the-535 behavior as `debuglevel=1`. Don't trust debuglevel alone.

- **Before any SMTP work, check the outbox age to detect a same-outage repeat.**
    `ls -1 ~/.hermes/cron/outbox/<platform>/*.html 2>/dev/null | wc -l` is the fastest "is this the same SMTP outage I've already diagnosed?" check.
    If the count is ≥3 AND the platform's `outbox/<platform>/README.md` has no
    "Outage resolved" entry, you are looking at a known chronic failure —
    skip Steps 1-5 of the diagnostic loop and jump to the Case H terse-report
    pattern (outbox path + one-line fix). Saves the user from another 30s of
    SMTP probe output for a problem they've been ignoring for ≥3 nights.
    Pair with the **time-to-failure fingerprint**: a revoked QQ SMTP auth
    code returns 535 in ~0.6-0.8 seconds (measured 2026-09-09: 0.62s wall
    clock from `SMTP_SSL()` open to the `SMTPServerDisconnected`). If your
    probe completes in under 1s and prints `Connection unexpectedly closed`,
    it's a credential problem, not a network one — skip the port-587 retry
    and go straight to the user-fix instructions. At N≥20 the probe is purely
    ceremonial; one line of AUTH LOGIN output (the `password -> 535:` line)
    is the entire diagnostic value, the rest is noise.

- **The "From header invalid" error mode (2026-08-23) was fixed and has
  not recurred.** If you see `550 ... "From" header is missing or invalid.
  Please follow RFC5322...` (vs `Connection unexpectedly closed`), check
  the script's `msg['From']` line uses `formataddr((str(Header('Name',
  'utf-8')), SMTP_USER))` — that pattern is the stable fix. The
  `Connection unexpectedly closed` family of errors is a separate
  credential problem; don't conflate them.

- **Cron scripts do not inherit your interactive env vars.** A script that
  reads `os.environ['QQ_EMAIL_AUTH_CODE']` will get an empty string in cron
  context, and your "I tested it manually and it worked" recollection is
  wrong because your shell *did* have the var set. Either bake the credential
  into `~/.hermes/cron/config/config.yaml`, or `export` it at the top of the
  script. See `references/smtp-credential-failure-case-study.md` for a
  worked case study.

- **Once `probe_smtp.py` confirms a known auth-revocation pattern, stop re-running the script.** The credential is binary (valid or revoked), not probabilistic — re-running the full content-generation + SMTP-failure cycle produces zero new information, just more identical `❌ 发送失败: Connection unexpectedly closed` output that consumes cron-output bandwidth. After the first confirm, switch immediately to user-report mode (point at the outbox backup, give the fix command). See Case E in `references/smtp-credential-failure-case-study.md`.

- **A failed email cron loses today's content unless you save it locally.**
  The script's `try/except` around `sendmail` swallows the error and exits
  cleanly — the article is gone. Always save the rendered HTML/text to
  `~/.hermes/cron/output/<script>_<timestamp>.{html,txt}` BEFORE attempting
  delivery, so a credential outage doesn't also nuke the work product.
  See "Step 4 — Save locally as a fallback" in the SMTP deep-dive.

- **Provider-specific error codes are not interchangeable.** QQ's `535` is
  a generic auth/account-abnormal message; Gmail is more specific; Outlook
  /Office365 adds a `5.7.606` error code you'll need to look up. Don't try
  to pattern-match across providers — read the full error string the first
  time.

- **Save AFTER failure, not only BEFORE send.** The Step 4 pattern (write
  HTML to disk before calling send_email) covers the "script crashes mid-
  delivery" case, but the common SMTP failure is the script completing
  cleanly with the article still in memory. A second backup at the catch-
  block tail catches BOTH the "credential died" and "network blip" paths
  without a wasted write on success. Combine: one retry on transient
  `SMTPServerDisconnected` (3s backoff), then save to
  `~/.hermes/cron/outbox/<platform>/` on final failure with the absolute
  path embedded in the error message. See step 6 of the SMTP deep-dive for
  the working template from `toutiao-article-daily.py`.

- **Three outbox-resident artifact types, three purposes (Case V, 2026-10-12).** Chronic-outage crons should maintain three sibling artifacts under `outbox/<platform>/`: (1) the rendered `YYYYMMDD_HHMM_<direction>.html` (full content), (2) the `PENDING_<date>.html` symlink to one canonical content file, (3) a `STANDBY_<date>.txt` plain-text dispatch metadata file (title / direction / HTML path / ≤200-char reason). The STANDBY file is for crons whose primary delivery channel is broken AND whose report rides a secondary channel (e.g. Feishu / Lark / Slack) that doesn't render file paths — that secondary consumer can quote the STANDBY as a low-bandwidth pickup notification. Worked implementation lives in `toutiao-article-daily.py::main()` (block added 2026-10-12 — preserve it on future edits). Don't move the STANDBY write out of the `if not success:` branch, and don't store STANDBY files in `~/.hermes/cron/output/<job_id>/` (that's scheduler log territory, see §5/Case C). Full lessons + porting guide in `references/toutiao-cron-outage-2026-09.md` Case V.

- **The failure report must NOT depend on the broken channel.** When the
  cron is failing because of email, the failure report cannot be an email.
  Always check the cron's `deliver` config: if it's `deliver: origin` to
  Feishu/Lark/Slack, the agent's final response auto-delivers there and
  the failure report can ride that channel safely. If no `deliver` is
  configured, write the failure report into
  `~/.hermes/cron/outbox/<platform>/README.md` alongside the HTML backups
  so the user finds it when they next inspect the outbox. See Case F in
  `references/smtp-credential-failure-case-study.md` for the canonical
  report template.

- **Escalate to explicit user-facing fix instructions after the 3rd
  consecutive identical failure.** The first 1–2 occurrences: confirm with
  `probe_smtp.py`, save the outbox backup, and report minimally. From the
  3rd occurrence onward: include the verbatim QQ-web-UI fix steps
  (mail.qq.com → 设置 → 账户 → regenerate SMTP authorization code →
  update `~/.hermes/cron/config/config.yaml`) in the report, plus the
  cumulative failure count. By day 5+, the report should read like a
  runbook entry, not a passive error message — the user has likely been
  ignoring the first two.

- **At 10+ consecutive identical failures, stop running `probe_smtp.py`.**
  The credential state hasn't changed in a week; running the probe again
  consumes tokens to confirm what `~/.hermes/cron/outbox/<platform>/README.md`
  already says. Skip straight to: outbox path + auth code location + the
  one-line fix. The user knows — they just haven't done it. Treat it like
  a runbook dispatch, not an investigation. See Case H for the canonical
  terse report template.

- **⚠️ The README extension is independent of the failure report — and it is the
  step agents skip at high N.** At failure count ≥30 the terse dispatch report
  already "feels complete", so agents skip the `## YYYY-MM-DD（持续中 — 第N天）`
  README append. But the report rides the `deliver` channel and scrolls past;
  the README persists and is what lets the *next* session reconstruct the
  outage. Treat it as a terminal action, not cleanup. Verify with
  `grep -c "^## " ~/.hermes/cron/outbox/<platform>/README.md` — the count must
  increase by 1 per session. See the Escalation policy below and Case W in
  `references/case-log-chronic-outage.md`.

- **🔴 Do the README append EARLY, not last (2026-11-05, a session got cut off).**
  A cron session hit its tool-call limit *after* the content fixes and verification
  but *before* the README append and the outbox prune — the two terminal actions.
  The fixes landed in the source (good), but the cross-session outage log skipped
  a night, so the next session's "第N天" counter was wrong and the README had no
  record of the linter repair.
  **Rule: for a chronic-outage cron, append the README entry and prune the outbox
  EARLY in the session** (right after confirming delivery), not as cleanup at the end.
  The audit/fix work is the part that can be cut off; the persistence step must not be.
  If you suspect you're near a limit, write the README entry first and treat any
  remaining analysis as a bonus.
  Also note the README heading count is the verification: `grep -c "^## "` must go up
  by exactly 1 per session — if it didn't, the entry was never written.
  - **🆕 2026-11-08 复现：这是第二次因会话被截断而漏记 —— 而且漏的不止一夜。**
    11-07 会话被工具调用上限截断，没能追加 README；11-08 会话开头发现
    README 最后一条是 11-06（**第74天**），而 11-07（第75天）**整夜缺失**。
    处理方式：按上面「backfill EVERY gap night」补记 11-07，并追加 11-08。
    **标题数 31 → 33**（= 1 + 1 个补记夜），已用 `grep -c "^## "` 核验。
    - **实操顺序（2026-11-08 会话验证有效）**：
      ① 先确认当晚产物与送达（读 outbox + `_verify_feishu_msg.py` 回查 `message_id`）
      → ② **立刻**补记 README（回填所有缺口夜 + 追加今晚）
      → ③ 再做内容审计与修复 → ④ 最后清理 outbox。
      把 README 放在修复之前，是因为修复最容易耗尽工具调用额度。
    - **⚠️ 补记时的取数纪律**：事实**必须从产物取**，不能凭记忆 ——
      标题/方向从 `outbox/<platform>/YYYYMMDD_HHMM_<direction>.html` 的 banner 取，
      失败原因从对应的 `STANDBY_YYYYMMDD.txt` 取，
      飞书 `message_id` 从 scheduler 输出日志（`~/.hermes/cron/output/<job_id>/*.md`）
      或 `STANDBY` 文件里抠 —— **不要重跑脚本去「重新拿一个 ID」**（会产生第二份产物）。
      本次补记 11-07 时，`message_id=om_x100b61c5d22b40a8c1ea4391e128090`
      就是从 11-07 的 `STANDBY_20261107.txt` 取的，再用 `_verify_feishu_msg.py` 回查确认
      `file_name=20261107_2030_亲戚恩怨.html` —— **补记不等于抄旧结论，要重新回查**。
    - **⚠️ 用 `execute_code` 读写 README 时注意行号前缀**：本会话用
      `read_file()` 读回来的是 `行号|内容` 格式，直接拼接会把行号写进文件。
      **必须先剥掉 `^\d+\|` 前缀再落盘**，写完再 `grep -c "^## "` 核验标题数。
      另注：写入长中文段落要检查有没有产生**乱码字符**（本次有一处 `五六���`
      被写进文件，靠 `grep` 发现后补修）—— 落盘后扫一遍非正常字符。

- **⚠️ Case K ("IP-level AUTH block") is NOT reproducible on this deployment — never cite
  it without a fresh raw-socket control test.** Originally "discovered" 2026-09-11 (failure
  #17) from `server.login(good_pass)` and `server.login(wrong_pass)` both returning
  `SMTPServerDisconnected("Connection unexpectedly closed")` in ~0.6s with no `reply:` line
  and no 535, which looked like QQ rejecting AUTH from this IP before credential validation.
  **Disproven 2026-10-20 (failure #57):** a raw socket + manual `AUTH LOGIN` probe against
  smtp.qq.com:465 produced a complete, explicit transcript — `220` banner,
  `250-AUTH LOGIN PLAIN XOAUTH XOAUTH2`, `334 VXNlcm5hbWU6`, `334 UGFzc3dvcmQ6`, then
  **`535 Login fail. Account is abnormal, service is not open, password is incorrect, login
  frequency limited, or system is busy.`** TCP and TLS are healthy; QQ does validate the
  credential and returns Case A (explicit 535). The reason `smtplib.login()` appears to
  "hide" the 535 is purely client-side: `smtplib` tries AUTH PLAIN, gets the 535, retries AUTH
  LOGIN, and the second attempt's abrupt teardown surfaces as `SMTPServerDisconnected`.
  That exception is a **symptom of smtplib's retry logic**, not evidence of an IP block.
  **Operational rule:** never conclude "IP-level block" from `SMTPServerDisconnected`
  alone. Drive the session yourself — `socket.create_connection()` + `ssl.wrap_socket()`,
  then send `AUTH LOGIN`, base64 username, base64 password, printing every server line. If a
  `535` appears, the credential is dead; the fix is regenerating the auth code, full stop.
  Also keep `references/smtp-credential-failure-case-study.md` in sync with this correction.

- **⚠️ A backfilled outage log must cover EVERY missed night, not just tonight (2026-11-06).**
  The "append README early" rule fires per *session*, but sessions can be cut off before
  they append — so the log develops **holes**, not just a missing tail. On 2026-11-06 the
  README's last entry was 11-03 (day 71) even though 11-04 and 11-05 had both run and
  been delivered; the 11-04 session was truncated mid-work and the 11-05 session ran out
  of tool-call budget before its append.
  - **Fix on the next session: backfill EVERY gap night**, not only the current one. Each
    backfilled entry needs the same fields as a live one: symptom, cron trigger count,
    generated article + direction, HTML backup path + size, PENDING/STANDBY presence,
    Feishu `message_id` (readable from the scheduler output log at
    `~/.hermes/cron/output/<job_id>/*.md` — **don't re-run the script to get one**, that
    makes a second artifact), and what was fixed.
  - **Source the facts from the artifacts, not from memory**: `outbox/<platform>/YYYYMMDD_HHMM_<direction>.html`
    for title/direction, the `STANDBY_YYYYMMDD.txt` file for the failure reason, and the
    scheduler output log for the `message_id`.
  - **Verify the backfill with the heading count**, not by eyeballing:
    `grep -n '^## ' outbox/<platform>/README.md` — the count of `## YYYY-MM-DD` headings
    must increase by the number of nights backfilled (not by 1).
  - **Corollary:** the "count must increase by exactly 1 per session" check is for a
    *single-night* session. When you discover holes, the expected delta is
    *1 + (number of missing nights)*.

- **`crontab.txt` and Hermes `jobs.json` are independent schedulers.** Some
  deployments run the same script under both classic cron (`crontab -l` →
  `~/.hermes/cron/crontab.txt`) AND the Hermes cron scheduler (`jobs.json`).
  When debugging a "silent" cron, check both — `jobs.json` may show the job
  exists but not actually be the one firing, or vice versa. The log dir
  `~/.hermes/cron/output/<job_id>/` only exists for Hermes-scheduler runs.

- **`crontab.txt` is invisible to the Hermes health view.** Classic cron
  fires the script, the script writes to `toutiao-article-daily.log` (the
  redirect target), and `jobs.json` is never touched. So `jobs.json`'s
  `last_run_at` / `last_status` only reflects Hermes-scheduler runs of the
  script — classic cron is a parallel universe the scheduler can't see.
  Detection recipe for "is classic cron firing?": compare
  `ls -t ~/.hermes/cron/outbox/<platform>/*.html | head -1 | xargs stat -c %y`
  (outbox mtime, fires under either scheduler) against
  `python3 -c "import json; j=json.load(open('$HOME/.hermes/cron/jobs.json')); ..."`
  (Hermes-side timestamp). If outbox is newer than Hermes's last run, classic
  cron fired in between. This is the only way to detect double-fires when
  the same script is registered under both.

- **`outbox/<platform>/README.md` is the durable outage log; extend it
  on every failed night, don't rewrite.** When a cron has been failing
  for ≥3 consecutive nights, append a `## YYYY-MM-DD（持续中 — 第N天）`
  entry to the outbox README — never overwrite the file. The README is
  the cross-session memory that lets a fresh cron-run agent reconstruct
  the full outage history without burning tokens re-diagnosing. See
  `references/outage-readme-template.md` for the full template and
  "what goes in vs out" rules.

- **⚠️ 飞书 `message.get` 回查在本 SDK 版本有三处 API 差异（2026-11-03 实测）**：想确认备用通道「真的送达」而不是「脚本说送达」，必须回查消息。踩到的三个坑：**① `message.get` 是同步方法**（`await` 会报 `TypeError: object GetMessageResponse can't be used in 'await' expression`）；**② `success`/`code`/`msg` 是属性不是方法**（`resp.success()` 会报 `'int' object is not callable`）；**③ `data.items` 是 `Message` 对象不是 dict**（`it.get('msg_type')` 会报 `'Message' object has no attribute 'get'`）。`body.content` 里能看到 `{"file_key": "...", "file_name": "20261103_2030_房产纠纷.html"}` —— 用 `file_name` 核对「送达的是不是今夜那份」，比只看 `msg_type=file` 更可靠。
  - **已固化为 `~/.hermes/cron/scripts/_verify_feishu_msg.py`**（venv python 执行，`python3 _verify_feishu_msg.py <message_id>`）—— 以后每晚可直接回查，不用每次重写这段踩坑代码。
  - **注意 `create_time` 是毫秒时间戳**（如 `1793709006972`），不是秒。
- **⚠️ 飞书备用通道的 `message_id` 只出现在脚本自己的日志/错误串里**：`send_email()` 的失败返回串是 `[QQ SMTP 限频 / 飞书附件投递成功 (message_id=om_...)] Connection unexpectedly closed`。要回查就把这串 ID 抠出来 —— 别重跑脚本去"重新拿一个 ID"，那会生成第二份产物（Case R）。

- **⚠️ A dead mail channel is not a dead content channel (2026-10-25, failure #62).**
  When the email/SMTP channel has been down for weeks but the cron also has a healthy
  chat-platform `deliver` route, **push the content as a native file attachment on that
  route** instead of only writing a report that says "email failed". Working recipe:
  `tools.send_message_tool._send_to_platform(Platform.FEISHU, pconfig, chat_id, caption,
  thread_id=None, media_files=[(abs_html_path, False)])` → returns
  `{'success': True, 'message_id': 'om_...'}`. Verify by reading the message back
  (`lark.im.v1.GetMessageRequest` → confirm `msg_type == 'file'`, `deleted == False`).
  Caveats: `.html` is NOT in the `MEDIA:` regex whitelist but IS in `extract_local_files`'s
  `_LOCAL_MEDIA_EXTS`, and Feishu `file_type=stream` accepts arbitrary files; the SDK class
  is `lark.im.v1.GetMessageRequest` (top-level, not `lark.im.v1.message.*`); delete any
  superseded duplicate message so the user doesn't get two files. Be explicit in the report
  that this is a **channel substitution, not a mailbox fix** — the QQ auth code still needs
  regenerating if `569545015@qq.com` is the destination that matters.
  See `references/toutiao-cron-outage-2026-10-week4.md` Case Y.

- **⚠️ A dedup helper whose read key ≠ write key fails SILENTLY and forever (2026-10-27).**
  A content-generator can look like it has working cross-day topic rotation while
  never actually deduplicating. The failure mode: `_record_topic()` appends
  `{'key': ..., 'title': ..., 'date': ...}` but `_pick_topic()` reads
  `h.get('direction')` → every lookup returns `None` → `recent` becomes
  `['None','None',...]` → the "not recently used" candidate set is always the
  FULL pool → `random.choice(fresh)` degenerates to uniform random over the pool.
  No exception, no warning, no visible symptom other than repeated titles.
  **Detection recipe:** compare the key the writer emits against the key the
  reader looks up, then assert the candidate set is actually smaller than the pool:
  ```python
  recent = [mod._hist_key(h) for h in hist[-mod.MAX_RECENT:]]
  fresh = [t for t in POOL if t['direction'] not in recent]
  assert len(fresh) < len(POOL), "dedup is a no-op!"
  ```
  **Rule: whenever you add cross-day rotation, write an assertion that the
  candidate set SHRINKS, and simulate N future days before shipping.**
  A 12-day simulation should show 0 consecutive repeats and even distribution
  across the pool. "It generates different things" is not evidence of dedup.

- **⚠️ A brand-new history file starts EMPTY → dedup silently does nothing until backfilled (2026-10-27).**
  When you introduce a rotation feature and seed its history file with *only
  today's picks*, the dedup window has no prior data to compare against, so the
  feature is a no-op on day 1 and stays a no-op until the window fills (~5 days).
  Real damage measured here: micro-topic history created 10-26 with only 2
  entries → near-8-day observed distribution was 婆媳关系 ×15, 老年婚姻 ×12,
  养老金 ×11 — the same micro-post went out many nights running.
  **Fix:** backfill the history file from ground truth before shipping —
  for this deployment the source of truth was parsing `方向：X` out of the
  accumulated outbox HTML (`outbox/<platform>/YYYYMMDD_HHMM_<direction>.html`),
  which yielded 50 micro-topic records for 10-11 → 10-27.
  **Rule: a new rotation feature ships with (a) a backfill of historical picks
  and (b) a multi-day simulation showing 0 consecutive repeats.** Verify the
  *frequency distribution*, not just the presence of the feature.

- **⚠️ A sliding window sized in *records* is the wrong unit for multi-per-day feeds (2026-10-28).**
  The 10-27 fix above made `MAX_RECENT` a **record count** (`history[-MAX_RECENT:]`).
  That is correct for a 1-record-per-day feed, but the micro feed emits **2 records
  per day** — so a 9-record window covers only 4.5 days, and while the window is still
  filling, the "not recently used" candidate set is 7-8 items wide. `random.choice`
  over that set hits a repeat with real probability. Measured 30-day simulation:
  **6 consecutive repeats, only 6/10 directions ever used**, worst offender at 22%
  of all micro posts.
  **Fix: use LRU (least-recently-used), not windowed-random.** Rank candidates by
  the index of their last appearance in the history and take the oldest — no random
  collision, the pool cycles cleanly, and the distribution is perfectly even.
  ```python
  def _pick_lru(pool, history_path, key='direction', exclude=()):
      history = _load_history(history_path)
      last_seen = {}
      for i, h in enumerate(history):
          k = _hist_key(h)
          if k:
              last_seen[k] = i          # bigger index = more recent
      exclude = set(exclude or ())
      avail = [t for t in pool if str(t.get(key)) not in exclude] or list(pool)
      def _rank(t):
          return last_seen.get(str(t.get(key)), -1)   # never seen = -1 = oldest
      oldest = min(_rank(t) for t in avail)
      ties = [t for t in avail if _rank(t) == oldest]
      return random.choice(ties)
  ```
  Result: 0 consecutive repeats, 10/10 directions covered, distribution exactly even
  (3× each for 30 long-form picks; 6× each for 60 micro picks).
  **Two corollaries:**
  - **The window must also track pool size.** A hardcoded `MAX_RECENT = 5` against a
    10-item pool means the expanded pool is only half used — expanding the pool
    without widening the window is a no-op.
  - **Same-day exclusions must key on `direction`, not list index** — two micro posts
    on one night must never share a direction.
  Full write-up + the 30-day simulation harness:
  `content-platforms/references/topic-pool-rotation-and-length-engineering.md`.

- **⚠️ Rotation simulation MUST use a temp history file, or it corrupts production and lies to you (2026-10-28).**
  Pointing the picker at the real `topic_history.json` while simulating rewrites
  production state on every iteration and yields a wrong distribution. One run here
  reported "micro covers only 4/10 directions" — an artifact of the simulator reading
  and appending the live file, not a real defect.
  **Recipe:** redirect the module's history globals to `tempfile` paths, and make the
  picker accept an injected path so it is testable at all:
  ```python
  tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8')
  tmp.write('[]'); tmp.close()
  T.HISTORY_FILE = tmp.name
  # ... simulate N days ...
  os.unlink(tmp.name)
  ```
  Then **diff the real files** to prove nothing leaked:
  `diff <(cat /tmp/bk_topic.json) outbox/<platform>/topic_history.json`.

- **⚠️ `str.format(**kwargs)` silently DROPS kwargs the template doesn't reference (2026-10-25).**
  `generate_article()` passed `story_a_dialogue` / `story_a_ending` / `story_b_ending` into
  `HTML_TEMPLATE.format(...)`, but the template had **no placeholders for them** — so they were
  accepted and thrown away with no error. Every article since v1.1.0 shipped with its story
  dialogue and endings missing, silently violating 「故事要完整」. `str.format()` raises only on
  *missing* placeholders, never on *unused* kwargs.
  **Rule: after ANY generator/template edit, read the rendered product back and grep for the
  key content fields** — "renders without error" does NOT prove the output is complete.
  Verify the product, not the process. Same class of bug applies to any
  `dict`-driven template (`jinja2` silently renders empty for undefined vars too).

- **One revoked credential fails N scripts, not one.** When a content-platform
  cron (e.g. `toutiao-article-daily.py`) hits `SMTPServerDisconnected`, grep
  the whole `~/.hermes/cron/scripts/` directory for `smtp_pass` /
  `get_mail_config` to find every script that shares the credential. One
  bash one-liner tallies success/fail counts across all of them and gives
  the user the real blast radius (see `references/toutiao-cron-outage-2026-08.md`
  for the worked example: this deployment's QQ credential failure silently
  drops content from 3 content-platform scripts, not just the one in the
  log title). Don't fix one and report — fix the credential once and tell
  the user how many crons recover.

- **Match the report length to the delivery channel.** Case H's 4-line terse
  dispatch is right when the cron delivers via the same broken channel
  (e.g. `deliver: email` and email is what's broken — long reports burn the
  user's inbox) OR when failure count is ≥30 (user has been ignoring it
  for a month). For cron deliveries that route through the agent's main
  chat (`deliver: origin` to Feishu/Lark/etc.) at failure counts 10–25, a
  hybrid — headline + cross-script blast radius + generated-content
  summary, NO SMTP transcript — communicates more without wasting tokens.
  See `references/toutiao-cron-outage-2026-08.md` "Hybrid report shape".

- **Use a dedicated `outbox/` tree, not the scheduler's `output/` tree.**
  `~/.hermes/cron/output/<job_id>/` is the scheduler's own log directory;
  dropping backup artifacts there blurs "script ran" records with
  "content the user can still read" records, and the auto-rotation / log
  cleaners may eat your backups. Use `~/.hermes/cron/outbox/<platform>/`
  with one subdir per delivery platform (`toutiao/`, `wechat/`,
  `unified/`, `email/`) and a `README.md` in each explaining the most
  recent outage + the user-facing fix (regenerate QQ auth code, etc.).

- **Two-source-of-truth can both be stale.** When `config.yaml`'s `smtp_pass`
  and `~/.hermes/.env`'s `QQ_EMAIL_AUTH_CODE` were copied from the same QQ
  authorization code at setup time, a single revocation leaves BOTH dead.
  Just updating one won't help. Diff both against the live QQ web UI value
  before deciding the YAML is the canonical source. Pattern: `diff <(echo "$QQ_EMAIL_AUTH_CODE") <(grep smtp_pass ~/.hermes/cron/config/config.yaml | awk '{print $2}' | tr -d '"')` — if they match, you only have one
  credential to regenerate, not two.

- **QQ silent-reject has no `535` reply in the transcript.** Unlike the
  documented case study, a QQ anti-spam that aggressively revokes an auth
  code may close the TLS socket right after `AUTH` with no `reply:` line at
  all — `debuglevel=1` shows a clean EHLO then a bare `SMTPServerDisconnected`.
  Don't conclude "network problem" just because the 535 is missing.
  See the "Rarer edge case — QQ silent-reject (Case B)" callout in §5.

- **Manual AUTH LOGIN + `getreply()` is more reliable than `debuglevel=1`.**
  For QQ specifically, the default revocation signature (Case A) is a visible
  `535 Login fail. Account is abnormal...` line — but `debuglevel=1` can
  scroll past it because `smtplib` retries with AUTH LOGIN after AUTH PLAIN
  fails, and the second AUTH closes abruptly. Driving the SMTP session
  yourself with `server.send(b"AUTH LOGIN\r\n"); server.getreply()` per step
  prints each protocol reply on its own line — the 535 is deterministic.
  Prefer the manual recipe for terminal-typed probes, or when you suspect
  smtplib's AUTH retry is hiding the actual error. See Case I for the full
  transcript.

- **⚠️ `last_status=ok` does NOT mean the report was delivered (Case Y, 2026-10-24).**
  The scheduler records `ok` because the *job* ran and produced a response; the
  *delivery* step is separate and its failure only surfaces in `last_delivery_error`.
  This deployment had BOTH channels broken at once: QQ SMTP dead 61 nights AND the
  Feishu `deliver: origin` route broken by a stale `omt_` thread_id (`99992402 field
  validation failed`, root cause `99992354 invalid open_message_id` — `omt_` is a thread
  id, not a valid `receive_id` for `receive_id_type=thread_id`).
  **Operational rule: when investigating "I didn't get the cron message", read
  `last_delivery_error` FIRST, before diagnosing the job body.** And when running as a
  cron whose report rides a channel, check that channel's health — a broken delivery
  route makes the failure report invisible, so the user sees silence instead of an
  error. Fix: `hermes cron edit <job_id> --deliver "feishu:<chat_id>"` (omit the thread
  id). Full diagnosis + 3-step verification in `references/feishu-stale-thread-id-delivery-failure.md`.

- **⚠️ A *content* cron has a second, quieter failure mode: the pipeline works but the product is bad (2026-10-28).**
  Every symptom in this file is a *delivery* failure — SMTP 535, dead channel, false
  `last_status`. But a content cron can also fail **while every green light stays on**:
  the script exits 0, the Feishu attachment lands, the user receives a file — and that
  file is the same headline they received last cycle, or 400 characters short of the
  script's own checklist target. Nothing errors. Nothing looks wrong. The user just
  quietly stops reading.
  **Diagnosis order for a content cron — check the PRODUCT first, then the channel:**
  1. Read the latest outbox HTML back and **measure** it (Chinese-char count, story
     sections present, topic direction).
  2. Compare against the *script's own* `CHECKLIST_ITEMS` — the checklist is a contract,
     not decoration. (Measured here: the script's own "1500字以上" target had **zero**
     articles meeting it — 813-1159 chars against a 1500 target.)
  3. Audit topic-direction frequency across recent outbox files:
     `ls -1 outbox/<platform>/*.html | sed 's/.*_//' | sort | uniq -c`.
  4. Only then diagnose delivery.
  **Rule: a cron that ships the same artifact to the same audience every N days is
  failing, even when the delivery channel is 100% green.** Fix the pool/rotation, not
  the channel. Full recipes (pool sizing, LRU rotation, length assertions, the
  `str.format()` silent-drop check) in
  `content-platforms/references/topic-pool-rotation-and-length-engineering.md`.

- **🔴 The audit tool can be DEAD and the session still reports "all green" (2026-11-05, 2 nights lost).**
  The content linter (`lint_content_consistency.py`) crashed on **every** run for two
  consecutive nights — `NameError: check_orphan_character` (the `_self_test()` called a
  function that was never defined) — **and the ORPHAN rule it was supposed to enforce
  was never wired into `lint()` at all**. Both nights were recorded as "linter green,
  content clean". They were not: the linter never reached the check.
  **Root cause of the concealment: the exit code was swallowed by a pipe.**
  `python3 linter.py ... | tail -30; echo "EXIT=$?"` reports **tail's** exit code (0),
  not the linter's. The linter actually exited 1 with **empty stdout** and a one-line
  traceback on stderr.
  **Rules:**
  - **Never run an audit tool through a pipe when you care about its exit code.**
    ```bash
    python3 linter.py --pool ... --extensions ... > /tmp/lo.txt 2>/tmp/le.txt
    echo "REAL EXIT=$?"; cat /tmp/lo.txt; echo "--stderr--"; cat /tmp/le.txt
    ```
  - **Triage by output shape, not by the exit code alone:** *stdout empty + stderr has a
    traceback* = **the tool is broken**, not "the content has problems". These demand
    opposite responses (fix the tool vs. fix the prose) and mixing them up wastes a
    night.
  - **A tool that self-checks must exit 2 on self-check failure** — never let an
    exception drag it down to 1, which means "content has problems".
  - **"I wrote the function" ≠ "the rule works."** Prove a new rule fires by feeding it
    a real counter-example (a temp pool + temp extensions file) and asserting exit 1
    plus the expected check code. Running it against clean content only proves the
    empty-set case, which is exit 0 regardless of whether the rule is wired up.
  - **🔴 2026-11-07 新增第三步：「跨池型不误报」。** 前两步（正例不报 + 反例必报）**都不够** ——
    `HOOK_PROMISE` 规则落地时两步都过了，却立刻产生 **14 处假阳性**（15 处命中里只有 1 处是真缺陷）。
    根因：规则自己的装配函数只认 `story_a`/`story_b` 系列字段，而**微头条池的正文在 `content`** ——
    微头条的「正文」被装配成空串，于是钩子/标题里的每个数字都判成「未兑现」。
    **第三步：对每一个选题池各跑一遍，把命中项连同该池正文一起打出来逐条人工核对。**
    ⚠️ **不要只看汇总数**（15 实际只有 1 个真缺陷）—— 汇总数会让人以为是 15 个缺陷。
    便捷工具：`content-platforms/scripts/check_pool_type_false_positives.py`
    （退出码 2 = 装配不出正文 = 该池字段结构与装配函数不匹配 = 假阳性来源）。
    **新增装配函数前，先看 linter 里有没有现成的池型分叉助手**（`_units_for()` / `_ext_pair()`）——
    自造第二套装配逻辑 = 迟早与主流程漂移。
  - **When a cron session's report says "audit passed", check the audit tool's own
    health at least once per session** — a green light from a tool you haven't run
    correctly is not evidence.
  - Full write-up (incl. the `PROMPT_HAS_CJK` and `PERIODIC_VS_YEARLY` rules added
    alongside the repair): `content-platforms/references/audit-tool-death-and-prompt-language.md`.

- **⚠️ Even a GREEN content audit can hide a broken product: check the arithmetic and the cast (2026-11-01).** The diagnostic order above says "measure the product first, then diagnose delivery" — but `audit_rendered_article.py` measures **length and structure only** (word count, sections present, image prompts, hashtags, micro-post word range). It **cannot** see (a) numbers that don't add up, or (b) characters that don't exist. Measured on a shipped article: monthly fee 8000, children contributed 5000+5000+3000 = **13000**, and the text claimed the children "covered a bit over half"; a character declared "two daughters" then referred to "his son" twice; a micro-post split 220,000 as "73,000 each ×3 + 51,000" = **270,000**. Every green light stayed green: script exit 0, HTML rendered, Feishu attachment delivered, audit exit 0 "全部检查通过". The only thing that caught it was **reading the rendered prose and doing the arithmetic by hand**.
  **Root cause: the article is assembled from multiple sources.** The pool entry lives in `toutiao_topics_extra.py`; the **expansion paragraphs live in a separate file `toutiao_story_extensions.py`** and are concatenated onto `story_a`/`story_b` at render time. Base text says "two daughters each give 1,000/month"; the expansion says "he doesn't ask his son for money". Neither is wrong alone — **together they are wrong**. No single-file check can find this.
  **Rules:**
  1. **When auditing a content cron, read the rendered prose end-to-end and add up the numbers.** Length checks passing means nothing if the subject matter is arithmetic.
  2. **Run the self-consistency linter** (`content-platforms/scripts/lint_content_consistency.py`, `--pool`/`--extensions`/`--json`): `SUM_EXCEEDS_FEE`, `SPLIT_VS_TOTAL`, `FRACTION_MISMATCH`, `PERIOD_MONTH_YEAR`, `CONTRIB_VS_FEE`, `PHANTOM_SON`, `FREQ_CONFLICT`. Exit 0 = clean.
  3. **Split story A and story B into separate units** for character checks — they are *different people*, and merging them makes legitimate references look like contradictions.
  4. **Verify the parser against known-good examples.** Chinese money shorthand (`7万3` = 73000, `一万五` = 15000) must be expanded; a parser that misses it reports unit-confused nonsense that looks like a finding.
     - **🔴 2026-11-02 实测：这类解析器的 bug 比内容缺陷更危险。** 修复那 6 处硬伤时发现 `lint_content_consistency.py` 把**每一种**口语缩写都算错了 —— `_num('7万3')` 返回 **70003**（应 73000）、`_num('一万五')` 返回 **10005**、`_num('十八万七')` 返回 **180007**、`_num('三百二十')` 返回 **500**。旧实现把「万位 + 省略尾数」当成了简单加法，而中文口语的尾数代表**下一级单位**（万→千、千→百、百→十）。
     - **危害方向是双向的**：报出的「缺陷」里有一部分**只是解析器假象**。一个把「5万6」当「5」的解析器，会把**已经写对的文案**报成缺陷，害得修复方把对的改回错的 —— 你「修」了 6 处，其中几处原本就是对的。
     - **规则：写完检查器必须用已知正确的算例验证解析器本身，不能只看「有没有报错」。** 本部署已在 `content-platforms/scripts/lint_content_consistency.py` 内置 `_self_test()`：15 个金额算例 + 正误两条拆分算例；自检失败 → **退出码 2**（工具坏了），与内容问题的 **退出码 1** 区分开。**改解析器后第一件事是看自检输出，而不是直接改文案。**
     - **两套口径别混用**：`_num()` 返回**元**（`_num('5万6')` = 56000），`_wan_amount()` 返回**万**（`_wan_amount('5','6')` = 5.6），差 1e4 —— 两个函数的 docstring 都必须写清单位。
  Full write-up + the 6 recorded defects: `content-platforms/references/content-self-consistency-checking.md`.

- **🔴 2026-11-04 实测：自动化审计全绿 ≠ 内容对。** 那一晚头条号文章的
  `audit_rendered_article.py` 报「✅ 全部检查通过」、`lint_content_consistency.py`
  exit 0、脚本 exit 0、飞书附件已回查确认送达 —— **全绿**，但**人工逐段通读 +
  手动加数**抓到 **9 处读者可见硬伤 + 3 段「孤儿扩写」**（扩写段落整个换成了
  另一个故事，读者看到主角无预兆换人）。
  - **原因**：自动化规则查的是**单字段内的算式**，查不到**跨段落/跨时间链**的
    口径不一致 —— 起始年龄+储蓄率+目标额算不出结束年龄；主体段「退休金 3500」
    与扩写段「3200」不同值；「凑了 2 万」与「护工 6000/月 × 2 月」跨句对不上。
  - **规则：审计内容 cron 的产物，除了跑工具，必须逐段通读并手动加数。**
    重点盯 6 条链：① 年龄链 ② 金额链 ③ 时长链 ④ 同属性取值链
    ⑤ 币种/口径链 ⑥ 汇总链。
    - **🆕 2026-11-07 补充第 7、8 条链**（当晚 audit/lint/脚本全绿、飞书已送达，
      仍靠通读抓到 10 类硬伤）：
      ⑦ **薪资链**（月薪 × 12 = 年薪？同一人月薪 15000 却写年薪 30万 → 差 40%）；
      ⑧ **同角色称呼链**（扩写段的「二儿子/老三」与主体段的「大儿子/二女儿/小儿子」
      是不是同一个人？主体换称谓读者不一定察觉，但「老三说」出现在只有两个儿子的
      家庭里就是硬伤）。
      ⚠️ **同属性取值链要按「同一人物」分组比，不是整篇比** —— 整篇比会把故事A的
      退休金 4800 与故事B的 3200 误报成冲突（2026-11-07 实测踩过）。
      ⑨ **金句复读链**（同一句金句在 viewpoint/action/*_ending 里整句复读；
      判定范围**必须含 `story_a_ending`/`story_b_ending`**，只扫 viewpoint+action 会漏 3 处）。
  - **通读主干 ≠ 读完**：整篇主干读下来仍可能漏 —— **扩写段落**是最容易藏
    「整个故事被换掉」的地方（正文主干看不出异常，拼接后才发现主角换了人）。
    扩写段落必须**单独读一遍**，并对照它对应的主体故事核人物。
  - 详见 `content-platforms/references/orphan-extensions-and-hand-arithmetic-audit.md`。

- **⚠️ 改内容源码时的批次原子性陷阱（2026-11-04）**：批量替换里**只要有一条匹配
  失败**，实现若写成「全部成功才落盘」，**已成功的编辑会被一起丢弃**。实测 16 条
  中 5 条因源文本措辞/空格差异匹配为 0 → 11 条成功编辑全丢、得重做一遍。
  - **规则：逐条落盘** —— 每条替换成功后立即写文件，失败的单独报告、不回滚已成功的。
  - **匹配失败时先打印实际源文本再改**：`src.find(key)` 拿到上下文比猜原文可靠得多。
  - 改完对全部源文件跑 `py_compile`。

- **⚠️ 给检查器加新规则时，先证明规则本身是对的（2026-11-04）**：本次给
  `lint_content_consistency.py` 新增 3 条规则，**第一次跑就 4 条自检失败** ——
  规则本身有 bug（金额单位口径混用差 1e4、「一个月 X」误把养老院月费当护工费、
  人名抽取太贪婪抽出「房管局」「张问刘婶」）。
  - **规则：新规则必须在 `_self_test()` 里配「正例不报 + 反例必报」两条算例**，
    否则你不知道规则本身对不对。
  - **退出码语义严格区分**：`0` = 内容干净 / `1` = 内容有问题 /
    **`2` = 检查器自身自检失败（工具坏了，不是内容坏了）**。
  - **自检失败时先看自检输出再动文案** —— 绝不能因为「规则报了假阳性」就去改
    本来写对的文案（这会把对的改回错的，比漏报更危险）。
  - **新规则要分清单位口径**：捕获组不含「万」时数值本身就是「万」，
    组内自带「万」才是「元」；匹配「一个月 X」必须确认紧邻业务词。

- **⚠️ A dead mail channel is not a dead content channel (2026-10-25, failure #62).**
  `toutiao-article-daily.py` renders its own `CHECKLIST_ITEMS` list into a visible
  "发布前检查清单" block at the bottom of every article. When v1.1.0 changed the sender
  from `权权的HERMES（头条）` to `围炉家常话（头条）`, it updated `send_email()` but **not**
  the checklist string — so every article had been telling the user to verify a sender
  name the pipeline doesn't use. The checklist was not decoration this time; it was
  *shipping*, so the drift reached the reader.
  **Rule: any value that appears in more than one place (a config string, a brand
  name, a from-header, a checklist item) must be asserted against its source of truth,
  not eyeballed.** Cheap check for this deployment:
  ```bash
  # every identity string in the script, side by side
  grep -rn "围炉家常话\|权权的HERMES" ~/.hermes/cron/scripts/*.py
  # the checklist item that ships to the reader
  grep -n "发件人是否为" ~/.hermes/cron/scripts/toutiao-article-daily.py
  ```
  Also note the **version banner drifted the same way** (`v1.1.0` in the file header and
  `main()`'s stdout while the code was already at v1.2.x) — version strings are the most
  commonly left-stale field in a long-lived script. Bump them in the same edit as the
  feature they describe.

- **⚠️ Two pools that rotate in lockstep will eventually pair a story with its own twin (2026-10-31).** Cross-day LRU dedup guarantees a topic doesn't repeat *itself* — it says nothing about a long-form topic and a micro topic colliding *with each other*. On `toutiao-article-daily.py` six of the ten micro entries retell the **same story** as a long-form entry (same protagonist, same beats: 老周头/随份子/烧本子, 大伯/供学费/断联, 住院/分家产, 房产证/过户, 立遗嘱/子女沉默, 养老院/算账). Both pools are 10 items and LRU advances them **in lockstep**, so a micro topic and its long-form twin land on the same night ~1/10 of the time — the reader reads the same story twice in one email. **Measured: 28/40 random rotation phases hit at least one collision; 264/2400 nights (11%) duplicated.** The tell is in the *pool*, not the output: two direction names that sound different (`人情往来` vs `随礼人情`) can be the same story. **Fix:** declare an explicit shadow map and exclude the twins when picking the companion pool:
  ```python
  SHADOW_MAP = {'人情往来': '随礼人情', '亲戚帮衬': '亲戚恩怨', ...}  # micro -> long
  def _pick_micro_index(used, history_path=None, exclude_directions=()):
      used_dirs = {...} | {str(d) for d in (exclude_directions or ())}
      ...
  micro_articles = generate_micro_articles(long_direction=topic['direction'])
  ```
  **Verify with the multi-phase harness, not a single run** — a single seeded run missed it entirely (0/20 collisions) while 28/40 phases hit it. The metric that matters is *collision nights / total nights across many phases*, not "did tonight collide". After the fix: **264/2400 → 0/2400**, with direction coverage still 10/10 on both pools. Also add a checklist line (it renders to the reader) so the rule is visible in the product.

- **⚠️ Measure the ASSEMBLED product, not an intermediate return value (2026-10-30).**
  A generator can look broken in an audit when the audit simply measures the wrong
  object. Two concrete traps hit on `toutiao-article-daily.py`:
  1. `generate_article()` returns **only the long-form** HTML. The micro-article HTML
     is appended later, inside `send_email()`:
     `full_html = html_content + '\n'.join(m['html'] for m in micro_articles)`.
     Auditing `generate_article()`'s return value → "micro-articles are missing!" —
     a false alarm. **Replicate the real assembly before measuring.**
  2. A micro-post's word-count target (150-250) applies to the **source `content`
     field**, not to the rendered block (content + dialogue highlight + image prompt +
     tags). Measured here: `content` = 250 chars (compliant) but the rendered block
     read 322 chars — looked like a violation, but the wrong object was measured.
  **Rule: before asserting a threshold, confirm the threshold's unit and its scope
  against the code that actually ships.** Use the ready-made auditor rather than
  hand-rolled regexes (a non-greedy `<div class="prompt-text">.*?</div>` truncates at
  the first inner `</div>`, letting English prompt text leak into the word count):
  ```bash
  python3 ~/.hermes/skills/productivity/content-platforms/scripts/audit_rendered_article.py \
      ~/.hermes/cron/outbox/toutiao/<today>.html \
      --pool ~/.hermes/cron/scripts/toutiao-article-daily.py
  ```
  It reports body Chinese-char count, section presence (故事A·对话/结局、故事B·结局、
  观点、行动、金句1-3), image-prompt block count vs `no text` occurrences, hashtag
  count, and micro `content` word-count range — exit 0 = clean, 1 = problems found.
  Full recipe set: `content-platforms/references/topic-pool-rotation-and-length-engineering.md`
  (缺陷四 + the two measurement traps).

- **⚠️ The "don't re-run the script" rule (Case R) and the "fix the content" mandate are in tension — resolve it by fixing the code, not by re-running (2026-10-28).**
  Case R says: if the outbox already has today's backup, do NOT run the script again
  (each extra run generates a *different* random topic and creates a second backup).
  But a session that audits the content and finds a defect still needs to ship the fix.
  The resolution that honours both:
  - **Do not re-run the production script** to prove the fix — that would duplicate
    today's already-delivered artifact.
  - **Do fix the script**, so tonight and every future night benefit.
  - **Prove the fix with an isolated harness**: load the module via
    `importlib.util.spec_from_file_location(...)`, redirect its history/artifact paths to
    **temp files**, render N days, assert on the output.
  - **Diff the real history files afterwards** to prove the harness didn't touch
    production state (`diff <(cat /tmp/bk_topic.json) outbox/<platform>/topic_history.json`).
  This gives the user today's correct content *and* tomorrow's improved content, with
  no duplicate delivery and no data corruption.
  ⚠️ Corollary: the harness must inject its history path, and the module under test
  must therefore accept one (`def _pick_micro_index(used_indices, history_path=None)`).
  A function that hardcodes a global path can only be tested against production data.

- **✅ Cheap proof that the script fired exactly once — check the crontab log + the
  outbox together (2026-11-05).** Two independent signals, both one-liners:
  ```bash
  grep "toutiao-article-daily" /var/log/syslog | grep "$(date +%Y-%m-%d)" | tail -3
  ls -t ~/.hermes/cron/outbox/<platform>/*.html | head -1 | xargs stat -c '%y %n'
  ```
  If syslog shows **one** `CRON[...] CMD (python3 .../toutiao-article-daily.py ...)`
  line dated today AND the newest outbox HTML is dated today, classic cron fired
  exactly once → **0 runs allowed for the reporting session** (Case R). A single
  `grep -c` on the log is enough to rule out a double-fire; don't guess.
  Pair it with the outbox filename check (`YYYYMMDD_HHMM_<direction>.html` — one file
  per night) to confirm no second product was generated.
  Note the log line shows the **redirect target** (`>> .../logs/<script>.log`), so the
  same log file is the place to read the night's stdout/stderr without re-running
  anything.
- **✅✅ The session's job is a REPORT, not a run — verify the four signals in one
  pass, then spend the remaining budget on the product (2026-11-08 实测有效).**
  For a classic-cron-fired content cron, the reporting session should open with a
  **single combined check** rather than one probe at a time. The 2026-11-08 session
  did exactly this and never re-ran the script:
  ```bash
  # ① 当晚是否已跑（syslog 只看今天这一行）+ 产物是否已落盘
  grep "toutiao-article-daily" /var/log/syslog | grep "$(date +%Y-%m-%d)"
  ls -la --time-style=full-iso ~/.hermes/cron/outbox/toutiao/ | grep "$(date +%Y%m%d)"
  # ② 脚本自己的日志尾部（一次看到「选题 + 失败原因 + 落盘路径 + message_id」）
  tail -40 ~/.hermes/cron/logs/toutiao-article-daily.log
  # ③ 备用通道是否真的送达（抠出 message_id 回查，不要重跑脚本去拿）
  python3 ~/.hermes/cron/scripts/_verify_feishu_msg.py <message_id>
  # ④ 产物本身过一遍审计（注意单独看退出码，别用管道吞掉）
  python3 ~/.hermes/skills/productivity/content-platforms/scripts/audit_rendered_article.py <html> --pool <pool>
  ```
  **信号①里的 `message_id` 已经出现在脚本日志尾部** —— 不用重跑脚本就能拿到它。
  把它回查确认（`msg_type` / `deleted` / `file_name` 三项）才算「送达」，
  然后才把剩余预算花在**通读 + 修复**上。
  ⚠️ 这套顺序的价值在于：把「跑没跑/送没送到」（便宜、确定）先钉死，
  剩下的额度全部用于「内容对不对」（贵、才是真正需要 agent 智力的部分）。
- **🆕 2026-11-11 实测：这条顺序再加一条 —— 「**产物已经落盘**」要同时用
  **产物文件数 + 两个 history 文件的 mtime** 交叉验证，不能只看其中一个**。
  当晚 `ls 20261111*.html | wc -l` = 1 且两个 history 文件 mtime 都停在
  `20:30:01` ⇒ 确认 classic cron 恰好触发 1 次、本会话 0 次执行许可（Case R）。
  只数产物文件可能被「上次残留 + 今晚失败」骗过；只看 mtime 则无法证明没有
  第二个产物。**两个信号一起看，结论才成立。**
- **🔴 2026-11-11 实测：即使 audit / lint / 脚本 exit 全绿 + 备用通道已回查
  送达，产物仍可能有三类「跨字段·跨夜失配」硬伤** —— 那晚 `audit exit 0` /
  `lint exit 0` / 脚本 exit 0 / 飞书 `message.get` 回查 `msg_type=file` +
  `file_name` 全部正常，仍抓到跨夜同故事碰撞、钩子整句复读、金句标签对不上
  实际出处 3 类读者可见缺陷。**根因是现有规则全都在查「单字段内的算式」或
  「同一条内容内部的重复」，查不到「这条内容与另一条内容（另一晚）的关系」。**
  通用教训：**审计工具全绿 ≠ 跨字段关系正确**；夜间内容 cron 的通读必须包含
  **跨夜比对**（今晚的微头条 == 前/后几晚的长文？）+ **整句复读扫描**（钩子/
  标题句在正文里逐字出现？）。检测与修复代码见
  `content-platforms/references/cross-field-defect-detection.md`。
- **🆕 2026-11-09/11-10/11-11/11-12/11-13 实测：这条顺序持续有效（连续 5 晚验证）**。
  当晚实测有效顺序（与 11-08 的差别只在第 ③ 步）：
  1. **一条命令同时取四个信号**（syslog 当日行数 + outbox 落盘 + 脚本日志尾部 + 飞书回查）。
     syslog `count=1` + outbox 当日只有一个产物 ⇒ **classic cron 恰好触发 1 次 ⇒ 本会话 0 次执行许可**（Case R）。
  2. **回查送达用脚本自己日志里的 `message_id`** —— 从 `STANDBY_<日期>.txt` 或日志尾部抠，
     再用 `_verify_feishu_msg.py` 回查 `msg_type=file` / `deleted=False` / `content.file_name=<今夜那份>`。
     **`file_name` 比 `msg_type` 可靠**（能确认送的是不是今夜这一份）。
  3. **立刻追加 README**（`## YYYY-MM-DD（持续中 — 第N天）`），并用 `grep -c "^## "` 核验标题数 +1。
     11-09 实测：33 → 34（delta=1），无乱码字符。**这一步必须在内容审计之前做**——
     内容修复最容易耗尽工具调用额度。
  4. 然后才跑 audit / lint（退出码**单独看**），做手工通读，改源码，最后剪 outbox。
  5. **README 追加完后再回填「修复后的复核」段落**（lint exit 0 / 假阳性检测 exit 0 /
     定点断言条数 / 金句复读自查命中数 / 微头条字数区间 / 假阳性人工核对结论），
     再核验一次标题数 —— **同一天不要新增第二个 `## ` 标题**，把复核写进当天段落里。
- **🔴 2026-11-13 实测：新增第 17 类缺陷「房产归属链 / 故事前提链」—— 工具全绿仍漏掉最严重的一处。**
  那晚头条号文章《69岁老人把房子过户给儿子后，儿媳说'这房子是我们的，你凭什么住'》
  `audit exit 0` + `lint exit 0` + `FP checker exit 0` + 脚本 exit 0 + 飞书已回查送达 —— **全程绿灯**，
  人工通读仍抓到 **7 处读者可见硬伤**，其中最严重的一处是**故事前提本身崩塌**：
  正文写「**房子写的是孙涛的名字**」—— 房本早就是儿子的了，那「过户」这一整个动作就是**空操作**，
  而标题、钩子、15 处「过户」、故事B 借条、观点、行动全建立在「过户」之上。
  **现有 16 类规则全部只查「单字段内的算式」和「同篇跨字段重复」，没有一类查「故事前提与标题/场景是否自洽」。**
  - **新增通读链 ⑪ 前提链**：故事的前提事实（**房本在谁名下 / 钱是谁出的 / 谁是 protagonists**）
    必须与标题、钩子、场景动作一致。**先问一句「这个故事要成立，前提是什么」，再核前提有没有被正文改掉。**
  - **同批抓到的其余 6 处**：地名链（房管所 vs 房管局）、时长链（三十年/三十六年/三十年 三处互斥）、
    借条链三方矛盾（房本在谁手里）、金句复读 **9 字**（差 1 字低于 linter 的 10 字阈值 → 漏报）、
    租房链断裂（儿子说租 1500 → 结局住 500 地下室，中间缺拒绝）、
    微头条数值链（一天 200 × 半个月 = 3000，原文写 2800）。
  - **🔑 关键方法论：`GOLDEN_ECHO` 的 10 字阈值是经验值不是真理** —— 那晚两处真实复读都恰好 **9 字**，
    **差一个字就全绿漏报**。通读时按 **8 字**手动扫一遍全字段，才抓到。
  - **🔧 修法优先级：改金句不改正文**（正文是故事，金句是提炼物）—— 与 11-11 的修法一致。
  - **📌 另一处发现：查历史产物时发现 11-08 微头条「兄妹摊牌」与 11-09 长文「兄弟姐妹」同故事。**
    回溯代码后确认 **11-08 跑的是 v1.2.5（影子守卫 11-11 才落地）** —— 用当晚 history 状态重放当前代码，
    守卫**正确排除**了该选题。**撞车是「修复前的历史事件」，不是现网缺陷** ——
    查历史撞车时**必须先核对当晚会话跑的是哪个版本**，否则会把已修好的问题当成新缺陷再修一遍。

- **⚠️ 2026-11-09 实测：改文案会顶出「字数约束」，改完必须立刻重量**。
  修一条微头条的逻辑矛盾时顺手加了一句，CJK 字数 **250 → 266**（上限 250）。
  `lint_content_consistency.py` **不报**（它查数值链，不查字数区间）；
  字数区间只有渲染后 `audit_rendered_article.py --pool` 才看得到 —— **但那要等下次跑脚本**。
  **规则：改任何池条目后，立刻重新量该条 CJK 字数**（微头条 150–250），别等渲染。
  同源纪律见 `content-platforms` 技能（同日新增的「锚点两个坑」条目）。
- **⚠️ 2026-11-10 实测：`lint_content_consistency.py --pool` 指向错文件会 exit 2（参数用错，不是内容有问题）**。
  `--pool` 必须指向**生成器脚本本身**（`toutiao-article-daily.py`），指向池数据文件
  （`toutiao_topics_extra.py` 或 JSON）→ **exit 2**。
  **exit 2 与 exit 1 语义完全相反**：exit 1 = 内容有问题（去改文案），
  exit 2 = 工具/参数用错（去看 stderr，**别去改文案**）。
  今晚差点因为 exit 2 去「修」本来正确的文案。先看 stderr 确认是哪一种再动手。
- **⚠️ 2026-11-10 实测：多批修复时，「已改源码但未复渲染验证」必须写进报告，不能当作已完成**。
  今晚 10 处内容硬伤分批修；最后一批（改掉「烧本子」在 `story_a_ending` 与 `ext_a` 的重复叙述）
  **源码已写入且 `py_compile` 通过，但最终 harness 复渲染与复核因工具额度到顶没跑完**。
  - **规则：会话里如果有**多批**修复，把第一批在会话早期就完整验证并落盘**；
    跨会话的批次**必须在报告里明确写「本批未复渲染验证，明晚首跑后确认」**，并附上确切的复核命令：
    ```bash
    python3 ~/.hermes/skills/productivity/content-platforms/scripts/audit_rendered_article.py \
      ~/.hermes/cron/outbox/toutiao/<明晚产物>.html \
      --pool ~/.hermes/cron/scripts/toutiao-article-daily.py
    ```
  - **不要让「改了但没验证」的状态被后续会话当成「已验证」** —— 下一晚会读 README/报告；
    如果它写「已修复」而实际未验证，缺陷会被当成已闭合而永远不再查。
  - ⚠️ 验证时**退出码要单独看**，别用管道吞掉（`audit_rendered_article.py` exit 0=干净 / 1=有问题）。

## Cross-reference: known recurring outage

For the `toutiao-article-daily.py` QQ SMTP outage (20+ nights as of 2026-09-13, identical `Connection unexpectedly closed` every night, auth code `<revoked auth code>` revoked), see `references/toutiao-cron-outage-2026-08.md`. It contains the verbatim QQ-web-UI fix steps, the outbox cleanup recipe, the terse-report pattern from Case H, and Cases I/J/L for refined probe recipes. **If you see a `Connection unexpectedly closed` on `smtp.qq.com:465` for `569545015@qq.com`, read that file first — the credential is almost certainly already revoked and the outbox already has today's content.**

For Cases S+ (failure #34 onwards, 2026-09-27+), see `references/toutiao-cron-outage-2026-09.md` — the continuation log. **At every cron-session start, read the relevant `references/` files AND the outbox README** before any diagnostic — together they cover the full outage history. The consolidated per-night narrative (Cases G–P) is in `references/case-log-chronic-outage.md`.

### Outbox pruning when accumulation gets unwieldy (Case W, 2026-10-16, failure #53)

The chronic-outage cron is at failure #53; `~/.hermes/cron/outbox/toutiao/` had accumulated ~117 HTML files (~3 MB) plus 14 PENDING symlinks plus 4 STANDBY files. At this size, `ls` becomes slow and the directory is unusable as a quick "is there a backup?" check.

Pruning recipe — keep the last N days, preserve README + PENDING + STANDBY untouched:

```bash
# Keep last 14 days of HTML backups; delete older ones
KEEP_FROM=$(date -d '14 days ago' +%Y%m%d)
cd ~/.hermes/cron/outbox/<platform>/
ls -1 *.html 2>/dev/null | while read f; do
  fname="${f%.html}"
  datestr="${fname:0:8}"
  if [[ "$datestr" < "$KEEP_FROM" ]]; then
    rm -f "$f"
  fi
done
# Also delete the corresponding PENDING symlinks and old STANDBY entries.
# ⚠️ Date-offset traps (verified 2026-10-27, CORRECTED 2026-10-29):
#   - "PENDING_20261027.html" → date starts at index 8  → "${f:8:8}"  ✅
#   - "STANDBY_20261027.txt" → date starts at index 8  → "${f:8:8}"  ✅
#   ⚠️ An earlier version of this recipe said STANDBY used index 9. That was
#   WRONG: both "PENDING" and "STANDBY" are 7 characters, so both dates start
#   at index 8. Using index 9 on a STANDBY file yields "0261029." — which is
#   lexicographically < "20261015", so **the recipe deleted every STANDBY file,
#   including today's** (observed 2026-10-29: STANDBY count went 3 → 0).
#   ⚠️ ALWAYS verify the slice before deleting:
#       echo "${f:8:8}"   # must print a bare 8-digit date like 20261029
#   If it prints anything else (dots, a shifted digit), the offset is wrong.
ls -1 PENDING_*.html 2>/dev/null | while read f; do
  datestr="${f:8:8}"
  if [[ "$datestr" < "$KEEP_FROM" ]]; then rm -f "$f"; fi
done
ls -1 STANDBY_*.txt 2>/dev/null | while read f; do
  datestr="${f:8:8}"     # ⚠️ index 8, NOT 9 — see the offset-trap note below
  if [[ "$datestr" < "$KEEP_FROM" ]]; then rm -f "$f"; fi
done

# ⚠️ Deleting a PENDING symlink's target HTML orphans the symlink → broken link.
# Always sweep broken symlinks after pruning:
find . -maxdepth 1 -name "PENDING_*.html" -xtype l -delete
```

**Verification after pruning (never skip):**

```bash
cd ~/.hermes/cron/outbox/<platform>/
echo "HTML: $(ls -1 2026*.html 2>/dev/null | wc -l)  PENDING: $(ls -1 PENDING_*.html 2>/dev/null | wc -l)  STANDBY: $(ls -1 STANDBY_*.txt 2>/dev/null | wc -l)"
# every PENDING symlink must resolve
for f in PENDING_*.html; do [ -e "$f" ] || echo "BROKEN: $f"; done
# today's content + today's STANDBY must still exist
ls -la PENDING_$(date +%Y%m%d).html STANDBY_$(date +%Y%m%d).txt
```

**Don't prune without preserving the README's history.** The README's "持续中 — 第N天" entries are the cross-session memory; the user may want to read them when they finally fix the auth code to see how long the outage ran. The recipe above leaves `README.md` untouched.

**⚠️ Add a post-prune restore check for STANDBY files (2026-10-29).** The STANDBY
files are regenerated only when the script runs, so a bad prune deletes them
permanently — there is no backup to restore from. After pruning, if the STANDBY
count dropped to 0 (or below what you expected), **reconstruct the missing files
by hand** from the script's own `main()` template rather than skipping ahead:

```python
# Reconstruct a STANDBY file for a date whose HTML backup still exists
standby = (
    f"📰 头条号今日文章（QQ SMTP 535 限频/授权码失效，已自动备份）\n"
    f"选题：{title}\n"
    f"方向：{direction}\n"
    f"时长：长文 + 2 条微头条\n"
    f"HTML：/home/ubuntu/.hermes/cron/outbox/toutiao/PENDING_{date}.html\n"
    f"原因：{reason}\n"
)
```
The `title`/`direction`/`reason` are all recoverable: title and direction are in
the backup HTML's banner, and the reason string is in the matching
`STANDBY_*.txt` reference inside the scheduler output log
(`~/.hermes/cron/output/<job_id>/*.md`) or in `~/.hermes/cron/logs/*.log`.

**Why 14 days:** enough to give the user a meaningful buffer of "I haven't read these yet" articles when they finally fix the credential and want to sweep history with `scripts/resend_outbox_html.py --all`, but small enough to keep `ls` instant. Tune by storage size: at ~27 KB per HTML, 14 days = ~380 KB per platform, very manageable.

**Anti-pattern: don't write a Python script to do this.** A bash one-liner is correct; a `.py` script over-engineers a 30-second cleanup. Case P warned against bespoke platform-specific scripts; same applies to one-off cleanup tools.

### The cleanup paradox at high N (Case W)

At failure #53 the cron-session agent did everything right — ran the script
once (agent-mode = one canonical run), delivered the terse report, pruned the
outbox — and still **skipped the README extension**, because the report
already felt "done". That is the trap at high N: the report is the visible
artifact, but the README is the durable one.

The rule, and the check that catches a skip, are in the **Escalation policy**
below. The full failure narrative is in
`references/case-log-chronic-outage.md` (Case W).


## Escalation policy — chronic-outage dispatch by failure count

A recurring failure is a *reporting* problem as much as a technical one. The
report must shrink as the failure count climbs: the user has already been told
N times, so each additional report should carry only what is new.

**Read the outbox README first** (`~/.hermes/cron/outbox/<platform>/README.md`).
It is the cross-session memory — it holds the outage history, the verbatim fix
steps, the blast radius, and the last "第N天" marker. Probes are *confirmation*,
not investigation. At N≥3 a README that still says "持续中" with no "已恢复"
entry means: skip the diagnostic loop entirely and dispatch.

| Failure count | Probe? | Article inline? | Report shape |
|---|---|---|---|
| 1–2 | Yes, full probe | Yes, full article | Full diagnostic + article |
| 3–9 | One confirmation probe | Title + hook only | Standard report + outbox-detection callout |
| 10–19 | Skip — README already says it | **No** | 4-line terse dispatch + outbox path |
| ≥20 | Skip — pure ceremony | No | Terse + `last_status=ok` masking warning |
| ≥25 | Skip | No | Terse + cross-script blast-radius count + one-line fix |
| ≥30 | Skip | No | Terse + scheduler-masking diagnosis + runbook entry |
| ≥50 | Skip | No | Terse + outbox pruning + **mandatory** README extension |

The 4-line terse dispatch (Case H shape):

```
📋 <pipeline>日报（N天连续失败）
✅ 内容生成成功 → outbox/<platform>/YYYYMMDD_HHMM_<direction>.html
❌ 邮件未送达：QQ SMTP 535 Login fail（auth code <code> 第N天）
🔧 修复：mail.qq.com → 账户 → SMTP服务 → 重新生成授权码 → 写回 ~/.hermes/cron/config/config.yaml
```

**Never inline the article after night 3.** The outbox already has it; pasting
1500+ words into a chat channel is token-burn on both sides.

**The README extension is a mandatory terminal action.** The cron report rides
the agent's `deliver` channel and scrolls past; the README persists. After every
session on a failing cron, append a `## YYYY-MM-DD（持续中 — 第N天）` block.
Verify with `grep -c "^## " ~/.hermes/cron/outbox/<platform>/README.md` — the
count must increase by 1. Skipping this breaks the cross-session memory chain
and is the single most common way a chronic outage loses its history.

**Run-count rule (agent-mode vs script-mode).** How many times you may run the
script depends on which scheduler fired:

| Scheduler mode | Pre-existing outbox backup? | Runs allowed |
|---|---|---|
| Classic cron (`crontab.txt`) | Yes | **0** |
| Hermes `no_agent` script-mode | Yes | **0** |
| Hermes agent-mode prompt | **No — you ARE the run** | **1, exactly** |

Each extra run generates a *different* random topic and a second outbox file.
Check `ls -t ~/.hermes/cron/outbox/<platform>/*.html | head -1` first: if the
newest backup is dated today, do not re-run.

**Outbox pruning when accumulation gets unwieldy.** Keep the last ~14 days of
HTML backups; preserve README + PENDING + STANDBY. Beware the date-offset trap:
`PENDING_YYYYMMDD.html` starts its date at index **8** (`${f:8:8}`) and so does
`STANDBY_YYYYMMDD.txt` (`${f:8:8}`) — both prefixes are 7 characters. Getting
this wrong deletes today's STANDBY file (observed 2026-10-29). Always sweep broken symlinks afterwards with
`find . -maxdepth 1 -name "PENDING_*.html" -xtype l -delete`, and verify every
PENDING symlink still resolves. Prefer a bash one-liner over a bespoke Python
script for this cleanup. Full recipe: `references/case-log-chronic-outage.md`.

**Where the per-night history lives.** The full case-by-case narrative (Case G,
H, I, J, R, M, N, O, P — one section per cron-run session, with its date, its
"Today's run" log, and the reasoning behind each rule above) is in
`references/case-log-chronic-outage.md`. That file also opens with a distilled
table of all 20 durable lessons from those sessions. Read it when you need the
*history* or the *reasoning*; do not read it as step 1 of a live outage.

Related case-detail references:
- `references/no-agent-false-error-reporting.md` — `no_agent` scripts that succeed (exit 0) but are reported as `last_status: error`; the mirror image of the `last_status=ok` masking case
- `references/duplicate-scheduled-task-detection.md` — duplicate deliveries: `jobs.json` vs `crontab.txt` overlap, same-purpose scripts under different names, stale brand/identity strings
- `references/toutiao-cron-outage-2026-08.md` — the original outage (Cases A–F)
- `references/toutiao-cron-outage-2026-09.md` — continuation log (Cases S+, failure #34+)
- `references/toutiao-cron-outage-2026-10-week4.md` — Cases X/Y/Z (failure #59+)
- `content-platforms/references/topic-pool-rotation-and-length-engineering.md` — **content-quality failures that stay green**: pool sizing, LRU rotation, length assertions, `str.format()` silent-drop check (companion to the delivery-side references above)
- `content-platforms/references/orphan-extensions-and-hand-arithmetic-audit.md` — **孤儿扩写 + 人工算账审计**：扩写段落整个换成另一个故事；自动化审计全绿但手工通读抓到 9 处硬伤。含 ORPHAN 检测规则的三次踩坑、通读要盯的 6 条链、批次替换原子性陷阱
- `content-platforms/references/audit-tool-death-and-prompt-language.md` — **审计工具自己死了**（linter 连坏 2 晚，退出码被管道吞掉 →「全绿」是假的；「写了函数 ≠ 规则生效」）+ 配图提示词混中文 + 周期频次 vs 年度汇总。**跑审计工具必须单独看退出码**
- `content-platforms/references/hook-promise-and-title-payoff-audit.md` — **钩子承诺不兑现（标题党翻车）**：钩子/标题承诺的画面、引语、数字正文一个字都没写 → 读者点进来想看的东西看不到。2026-11-06 实测 10/10 长文命中且全程绿灯。内容侧的「单字段自洽、跨字段失配查不到」盲区。**2026-11-07 已落地 `HOOK_PROMISE` 规则**（实测会 fire），并记录了规则自身「装配口径只认 story_* → 微头条池整池假阳性」的坑
- `content-platforms/references/character-lifecycle-and-timeline-chain-audit.md` — **缺陷十一「人物生死状态链断裂」+ 缺陷十二「时间线链打架」**：已故角色仍在对话里说话（死人复活）、同一事件两个时点（丧事当天 vs 三个月后）。2026-11-10 实测，audit/lint/脚本全绿 + 飞书已送达仍靠通读抓到 10 处硬伤。含**通读清单 8 条链 → 10 条链**（新增⑨角色生死状态链、⑩时间线链）、⚠️ **`lint --pool` 必须指向生成器脚本本身，指向池数据文件会 exit 2（参数用错 ≠ 内容有问题）**、按事件关键词全池回扫
- `content-platforms/references/golden-echo-and-label-provenance-audit.md` — **金句复读 + 金句标签对不上实际出处（第九类跨字段失配）**：同一句金句在 viewpoint/action/结局里被整句复读 → 读者在同一篇里看到同一段话连说两遍；且模板把 `golden1/2/3` 标成【故事A结尾】/【故事B结尾】/【文章结尾】，但金句是按**池槽位**写的、不是按**实际出处**写的 —— 14 条长文实测 0 条真落在标注位置。2026-11-08 实测命中 27 处，全程绿灯。**2026-11-08 已落地 `GOLDEN_ECHO` 规则**（实测会 fire）。通用教训：「摘要卡 + 正文」型结构天然产生复读缺陷，规则要按「跨字段重复」查而不是按「字段内自洽」查
- `content-platforms/references/cross-field-defect-detection.md` — **缺陷十三/十四/十五「跨字段·跨夜失配」**：跨夜同故事碰撞（`SHADOW_MAP` 只挡当晚，挡不住「前一晚的长文 == 今晚的微头条」，60 天模拟 20%）、钩子整句在正文里逐字复读（`HOOK_PROMISE` 只查「有没有兑现」）、金句出处标注对不上实际出处（9/20 不符）。含**守卫夜数调参表**（3/3 碰撞 0/60 且两池覆盖 10/10；5/5 会把微头条覆盖压到 4/10）、**检测与修复代码**、以及「必须调用真实生产函数而不是在测试脚本里复刻逻辑」的踩坑
- `productivity/content-platforms/scripts/check_pool_type_false_positives.py` — **跨池型假阳性检测器**：给 linter 加完新规则后跑它，逐池把「命中项 + 该池正文字段」并排打出来供人工核对。退出码 2 = 装配不出正文 = 该池字段结构不匹配 = 假阳性来源。⚠️ 不要只看汇总数
- `scripts/send_email_with_outbox.py` — **可直接 import 的发送封装**（`send_email_with_outbox`）：给裸 `smtplib.SMTP_SSL().login().sendmail()` 补上「瞬时故障重试一次（3s backoff）+ 最终失败落盘 outbox 并把绝对路径写进错误串」两段逻辑。cron 脚本里 `from send_email_with_outbox import send_email_with_outbox as send_email` 即可，行为与本技能 §6 的模板一致（2026-08-25 第三次 QQ 授权码失效后写的）
- `scripts/resend_outbox_html.py` — 授权码修复后补发 outbox 里的历史 HTML
- `scripts/probe_smtp.py` — SMTP 凭据探针（465-SSL + 587-STARTTLS，判别 535 / silent-reject / connect 失败三种形态）
- `references/smtp-credential-failure-case-study.md` — full SMTP transcripts
- `references/case-m-last-status-masking.md` — `last_status=ok` masking
- `references/feishu-stale-thread-id-delivery-failure.md` — stale `omt_` thread_id
- `references/outage-readme-template.md` — README entry template
- `references/qq-smtp-rate-limit-pitfall.md` — rate-limit variant
- `references/script-not-found-case-study.md` — path-resolution case study
- `productivity/content-platforms/scripts/audit_rendered_article.py` — **产物审计脚本**：测已渲染 HTML 的正文中文数、结构完整性、配图数与 `no text`、标签数、微头条 `content` 字数区间（`--pool` 核对选题池，`--json` 机器可读）。改生成器后跑它，别手写正则数字数
- `productivity/content-platforms/references/topic-pool-rotation-and-length-engineering.md` — 内容质量四缺陷（池子/LRU/`str.format()`/清单漂移）+ **两个测量陷阱**（要测装配后的产物；微头条字数测 `content` 而非渲染块）

## Recovery scripts (for after the credential is fixed)

```bash
# 1. Verify the new credential works before doing anything else
python3 ~/.hermes/skills/cron-job-debugging/scripts/probe_smtp.py

# 2. Push the latest outbox backup through the new credential
python3 ~/.hermes/skills/cron-job-debugging/scripts/resend_outbox_html.py toutiao

# 3. (Optional) sweep ALL accumulated backups for that platform
python3 ~/.hermes/skills/cron-job-debugging/scripts/resend_outbox_html.py toutiao --all

# 4. (Optional) re-send a specific file by name
python3 ~/.hermes/skills/cron-job-debugging/scripts/resend_outbox_html.py toutiao --file 20260920_2030_房产纠纷.html
```

`resend_outbox_html.py` is platform-agnostic — replace `toutiao` with `wechat`, `xhs`, `unified`, or `email` to target a different outbox subdir. The script reads the same `~/.hermes/cron/config/config.yaml` the cron scripts use; no edit needed when the auth code is rotated. Reference: Case P.

## Diagnostic commands cheatsheet

```bash
# Before ANY diagnostic on a known-recurring cron: read the outbox README
read_file ~/.hermes/cron/outbox/<platform>/README.md
# If it ends with "持续中" and no "已恢复", jump to Case H dispatch — skip everything below.
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
