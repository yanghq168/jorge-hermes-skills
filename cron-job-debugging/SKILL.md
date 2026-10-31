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

- **The README extension is independent of the failure report — and it is the
  step agents skip at high N.** At failure count ≥30 the terse dispatch report
  already "feels complete", so agents skip the `## YYYY-MM-DD（持续中 — 第N天）`
  README append. But the report rides the `deliver` channel and scrolls past;
  the README persists and is what lets the *next* session reconstruct the
  outage. Treat it as a terminal action, not cleanup. Verify with
  `grep -c "^## " ~/.hermes/cron/outbox/<platform>/README.md` — the count must
  increase by 1 per session. See the Escalation policy below and Case W in
  `references/case-log-chronic-outage.md`.

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
  That exception is a *symptom of smtplib's retry logic*, not evidence of an IP block.
  **Operational rule:** never conclude "IP-level block" from `SMTPServerDisconnected`
  alone. Drive the session yourself — `socket.create_connection()` + `ssl.wrap_socket()`,
  then send `AUTH LOGIN`, base64 username, base64 password, printing every server line. If a
  `535` appears, the credential is dead; the fix is regenerating the auth code, full stop.
  Also keep `references/smtp-credential-failure-case-study.md` in sync with this correction.

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

- **⚠️ A checklist that is RENDERED into the product must be audited against the code it describes (2026-10-30).**
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
table of all 18 durable lessons from those sessions. Read it when you need the
*history* or the *reasoning*; do not read it as step 1 of a live outage.

Related case-detail references:
- `references/no-agent-false-error-reporting.md` — `no_agent` scripts that succeed (exit 0) but are reported as `last_status: error`; the mirror image of the `last_status=ok` masking case
- `references/duplicate-scheduled-task-detection.md` — duplicate deliveries: `jobs.json` vs `crontab.txt` overlap, same-purpose scripts under different names, stale brand/identity strings
- `references/toutiao-cron-outage-2026-08.md` — the original outage (Cases A–F)
- `references/toutiao-cron-outage-2026-09.md` — continuation log (Cases S+, failure #34+)
- `references/toutiao-cron-outage-2026-10-week4.md` — Cases X/Y/Z (failure #59+)
- `content-platforms/references/topic-pool-rotation-and-length-engineering.md` — **content-quality failures that stay green**: pool sizing, LRU rotation, length assertions, `str.format()` silent-drop check (companion to the delivery-side references above)
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
