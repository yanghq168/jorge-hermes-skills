---
name: cron-job-debugging
description: "Debug silently-failing Hermes cron jobs (no_agent script mode, scheduled prompt jobs, chained jobs). Diagnose 'Script not found', silent no-op, exit-code-without-output, path-resolution failures, AND credential/SMTP delivery failures by reading scheduler output logs in ~/.hermes/cron/output/. Applies the script-path resolution rule, the SMTP-credential deep-dive, and the local-fallback save pattern."
version: 1.1.0
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
  `ls -1 ~/.hermes/cron/outbox/<platform>/*.html 2>/dev/null | wc -l` is the
  fastest "is this the same SMTP outage I've already diagnosed?" check.
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
  and go straight to the user-fix instructions.

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

- **`crontab.txt` and Hermes `jobs.json` are independent schedulers.** Some
  deployments run the same script under both classic cron (`crontab -l` →
  `~/.hermes/cron/crontab.txt`) AND the Hermes cron scheduler (`jobs.json`).
  When debugging a "silent" cron, check both — `jobs.json` may show the job
  exists but not actually be the one firing, or vice versa. The log dir
  `~/.hermes/cron/output/<job_id>/` only exists for Hermes-scheduler runs.

- **`outbox/<platform>/README.md` is the durable outage log; extend it
  on every failed night, don't rewrite.** When a cron has been failing
  for ≥3 consecutive nights, append a `## YYYY-MM-DD（持续中 — 第N天）`
  entry to the outbox README — never overwrite the file. The README is
  the cross-session memory that lets a fresh cron-run agent reconstruct
  the full outage history without burning tokens re-diagnosing. See
  `references/outage-readme-template.md` for the full template and
  "what goes in vs out" rules.

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

## Cross-reference: known recurring outage

For the `toutiao-article-daily.py` QQ SMTP outage (10+ nights as of 2026-09-03, identical `Connection unexpectedly closed` every night, auth code `iylylmwnitbbbebi` revoked), see `references/toutiao-cron-outage-2026-08.md`. It contains the verbatim QQ-web-UI fix steps, the outbox cleanup recipe, and the terse-report pattern from Case H. **If you see a `Connection unexpectedly closed` on `smtp.qq.com:465` for `569545015@qq.com`, read that file first — the credential is almost certainly already revoked and the outbox already has today's content.**

## Case G — Agent-mode cron variant: 7th consecutive failure, outbox accumulation, importlib bypass (2026-09-02)

The `toutiao-article-daily.py` cron failed for the 7th consecutive night with the identical `Connection unexpectedly closed` symptom on the identical `iylylmwnitbbbebi` auth code. By this point the diagnostic is fully internalized. What was genuinely new this cycle:

### Agent-mode vs no_agent script-mode crons

The cron-job entry in `jobs.json` shows `no_agent: false` and `script: null` — meaning the cron triggers an **agent run with a prompt**, not direct script execution. The agent's prompt is `"运行 ~/.hermes/cron/scripts/toutiao-article-daily.py 生成当日头条文章..."`. Inside the agent, the script gets imported/run like any other Python. Two practical consequences:

1. **The agent can self-debug by re-invoking the script directly** — run `python3 ~/.hermes/cron/scripts/toutiao-article-daily.py` from the agent's terminal to reproduce the failure with full control.
2. **The cron-output → user-message pipeline IS the delivery surface.** When `deliver: origin` is set (e.g. to Feishu/Lark topic), the agent's final response auto-routes there. So the failure report rides that same channel — and it MUST contain the outbox path + the fix command verbatim, because the email channel is broken.

### Importlib bypass technique: regenerate content without burning SMTP

When you want to inspect what a cron script produces (for the report) without burning another failed SMTP attempt, use `importlib.util.spec_from_file_location` to import the script as a module and call `main()` directly. The script's SMTP will still run (Python's `__name__` guard fires only on direct execution, not on importlib), so wrap by stubbing `send_email` BEFORE `exec_module`:

```python
import importlib.util
spec = importlib.util.spec_from_file_location("toutiao_mod", "/home/ubuntu/.hermes/cron/scripts/toutiao-article-daily.py")
mod = importlib.util.module_from_spec(spec)
def fake_send_email(html, plain, topic, micro):
    print(f"[FAKE] subject={topic['title']}, html_len={len(html)}")
    return True, "FAKE"
mod.send_email = fake_send_email       # override BEFORE exec_module
spec.loader.exec_module(mod)            # NOW the top-level code's send_email reference resolves to fake
html, plain, topic, micro = mod.main()
```

**Pitfall:** the `if __name__ == "__main__": main()` guard does NOT fire when loaded via importlib. Top-level code (including decorators and immediate `main()` calls if any) WILL execute on import. If the script calls `main()` outside the guard, you will get a second content-generation + failed-SMTP cycle. Check the script's top level first; if it has the `if __name__ == "__main__":` guard, you're safe.

A cleaner alternative: **import the module, then call only the generation functions explicitly** without invoking `main()`:

```python
spec.loader.exec_module(mod)
# Don't call mod.main() — call the generators directly
html, plain, topic = mod.generate_article()
micro = mod.generate_micro_articles()
# Skip mod.send_email() entirely
```

This avoids the guard pitfall AND avoids the second SMTP attempt.

### Outbox accumulation pattern: 7+ days of identical failures

By day 7+, `~/.hermes/cron/outbox/toutiao/` has accumulated ~10 HTML files (one per night, all ~27 KB, all generated by the same script with different topic directions). This is **correct behavior** — the script does exactly what Case C designed it to do. But the user eventually needs to clean these up after the credential is fixed. The recommended cleanup recipe:

```bash
# After the user regenerates the QQ auth code and confirms a clean run:
mkdir -p ~/.hermes/cron/outbox/toutiao/$(date +%Y-%m)_archive
# Move all-but-the-most-recent into the archive
ls -t ~/.hermes/cron/outbox/toutiao/*.html | tail -n +2 | \
  xargs -I {} mv {} ~/.hermes/cron/outbox/toutiao/$(date +%Y-%m)_archive/
# Append a one-line outage summary to outbox/README.md so future sessions see it
cat >> ~/.hermes/cron/outbox/toutiao/README.md <<EOF
## Outage 2026-08-28 → 2026-09-02 (7 nights)
- Symptom: Connection unexpectedly closed on smtp.qq.com:465 (QQ silent-reject Case B)
- Root cause: SMTP authorization code iylylmwnitbbbebi revoked by QQ anti-spam
- Fix applied: user regenerated auth code in QQ web UI, updated ~/.hermes/cron/config/config.yaml
- Verified: cron at 20:30 next night returned ✅ 邮件发送成功
EOF
```

The README's outage log is the **durable memory** for "what happened during this stretch" — survives across cron-job-script edits and config changes. Future sessions encountering the same auth code + same failure can grep `~/.hermes/cron/outbox/<platform>/README.md` to confirm whether the current outage has been seen before.

### Outage detection via outbox age

A useful diagnostic shortcut for any future "is the SMTP broken right now?" question:

```bash
# How many nights has the outbox been growing without a successful cron?
ls -1 ~/.hermes/cron/outbox/toutiao/*.html | wc -l
# Count of consecutive failed nights = (today - oldest_outbox_file_date)
# If ≥3, switch immediately to user-fix mode per the Case F decision rule.
```

## Case H — 10th consecutive identical SMTP failure: terse runbook dispatch mode (2026-09-03)

The `toutiao-article-daily.py` cron failed for the 10th consecutive night (since 2026-08-25). Same auth code (`iylylmwnitbbbebi`), same `Connection unexpectedly closed`, same `535 Login fail` in the SMTP transcript. Every diagnostic step from Cases A–G has been confirmed multiple times. New lesson this cycle: **the report should shrink, not grow, as the failure count climbs.**

### What NOT to do at failure N≥10

- Re-run `probe_smtp.py` — confirms what we already know, burns tokens.
- Re-explain what `535 Login fail` means — user has seen it 9 times.
- Re-list the full SMTP deep-dive steps — they're in this skill, the user knows.
- Suggest "try port 587 instead" — already covered in Case A; the credential is binary dead, transport won't help.
- Paste the full article HTML inline — the outbox already has it.

### What to do at failure N≥10

Compress the failure report to four lines:

```
📋 头条文章日报（N天连续失败）
✅ 内容生成成功 → outbox/toutiao/20260903_2030_赡养义务.html
❌ 邮件未送达：QQ SMTP 535 Login fail（同 iylylmwnitbbbebi 第N天）
🔧 修复：mail.qq.com → 账户 → SMTP服务 → 重新生成授权码 → 写回 ~/.hermes/cron/config/config.yaml
```

That's it. No probe, no transcript dump, no alternative-transport suggestion. The user knows what to do; they're either (a) traveling / away from QQ web UI, (b) deferred it as low priority, or (c) genuinely forgot. The terse reminder with a concrete fix command is the highest-value response.

**Always append to `outbox/<platform>/README.md` as the durable action** — the cron-output report rides the `deliver: origin` channel and disappears from view after the user scrolls past it. The README entry is the cross-session memory that survives across cron runs. Use the format from `references/outage-readme-template.md`:

```bash
cat >> ~/.hermes/cron/outbox/toutiao/README.md <<EOF
## YYYY-MM-DD（持续中 — 第N天）
- Symptom: Connection unexpectedly closed on smtp.qq.com:465 (auth code iylylmwnitbbbebi)
- Generated content: outbox/toutiao/YYYYMMDD_HHMM_<direction>.html
- Fix: mail.qq.com → 账户 → SMTP服务 → 重新生成授权码 → 写回 ~/.hermes/cron/config/config.yaml
EOF
```

Skipping this step is the most common way a chronic outage loses its history — the agent that runs next week has no record of how long the credential has been dead, and will waste tokens re-running the full diagnostic loop instead of jumping to Case H.

### Outbox count = silent outage clock

`ls ~/.hermes/cron/outbox/<platform>/ | grep -c '\.html$'` is now the canonical "how broken is SMTP right now" indicator. The count grows by 1 per failed night, freezes when fixed. If the count is ≥7 and the README.md has no "Outage resolved" entry, the outage is live. Use this to skip Step 1 of the diagnostic loop entirely — go straight to report.

### Diagnostic sequence for a fresh agent on a chronic outage (2026-09-10, failure #16)

When a fresh session encounters a cron that prints `❌ 发送失败: Connection unexpectedly closed`, the optimal sequence is:

1. **Outbox count** (`ls -1 ~/.hermes/cron/outbox/<platform>/*.html 2>/dev/null | wc -l`) — if ≥3, jump straight to step 6.
2. **Re-run script directly** (`python3 ~/.hermes/cron/scripts/<script>.py`) to reproduce and confirm it's not an agent-mode wrapper artifact.
3. **Probe with `smtplib.SMTP_SSL` + `debuglevel=2`** to see if 535 surfaces — Case J confirmed `debuglevel=2` ALSO buries the 535 for this QQ deployment, so don't expect it.
4. **Manual AUTH LOGIN + `getreply()` per step** (Case I recipe) — this IS the deterministic 535-surfacer. Always prefer over `debuglevel` alone.
5. **Port sweep** (465 SSL → 587 STARTTLS → 25 plain) — if all three die in <1s with 535, credential is dead. If 25 is "Network is unreachable" but 465/587 die fast, credential is dead AND ISP blocks port 25 (orthogonal problem).
6. **DNS / IP check** (`socket.getaddrinfo('smtp.qq.com', 465)`) — useful to rule out CDN/routing issues. If TCP connect succeeds (already verified by `SMTP_SSL` opening), DNS is fine.
7. **Terse Case H report** — only after the count + 535 are confirmed. Include outbox path + one-line fix.
8. **README extension** — append the `## YYYY-MM-DD（持续中 — 第N天）` entry to `outbox/<platform>/README.md` (Case H pattern). This is the durable cross-session memory.

The whole sequence should complete in under 60 seconds for an experienced agent. If it's taking longer, you're debugging the wrong thing — the skill already covers it.

## Case I — 14th consecutive identical SMTP failure: low-level AUTH LOGIN probe reveals explicit 535 (2026-09-07)

The `toutiao-article-daily.py` cron failed for the **14th consecutive night** (since 2026-08-25). Same auth code, same symptom, same Case H terse-report pattern applied. What was genuinely new this cycle was a **cleaner diagnostic recipe** that surfaces the 535 more reliably than `smtplib.SMTP.debuglevel = 1`.

### The probe recipe that always surfaces the 535

`debuglevel=1` works most of the time but has a known failure mode (Case B silent-reject) where the server tears down the TLS socket mid-AUTH with **no `reply:` line printed**, and you get a bare `SMTPServerDisconnected`. When the server DOES send the 535 reply (the common case for this QQ deployment), `debuglevel=1` sometimes buries it inside the AUTH PLAIN framing because Python retries with AUTH LOGIN after the first 535 — the second AUTH closes abruptly and your terminal scrolls past the actual rejection.

A **deterministic** recipe: do AUTH LOGIN yourself and call `getreply()` after each step. The 535 always shows up as its own line:

```python
import smtplib, base64
server = smtplib.SMTP_SSL('smtp.qq.com', 465, timeout=15)
server.ehlo()
server.send(b"AUTH LOGIN\r\n")
code, msg = server.getreply()
assert code == 334, f"unexpected: {code} {msg!r}"
server.send(base64.b64encode(b'569545015@qq.com') + b'\r\n')
code, msg = server.getreply()
assert code == 334, f"unexpected: {code} {msg!r}"
server.send(base64.b64encode(b'iylylmwnitbbbebi') + b'\r\n')
code, msg = server.getreply()
print(f"FINAL: {code} {msg!r}")
# On this deployment prints: FINAL: 535 b'Login fail. Account is abnormal, ...'
```

What came out this session (2026-09-07):

```
EHLO: 250: b'newxmesmtplogicsvrszb51-0.qq.com\nPIPELINING\n... AUTH LOGIN PLAIN XOAUTH XOAUTH2\n...'
AUTH LOGIN -> 334: b'VXNlcm5hbWU6'                    # base64("Username:")
username -> 334: b'UGFzc3dvcmQ6'                       # base64("Password:")
password -> 535: b'Login fail. Account is abnormal, service is not open,
                  password is incorrect, login frequency limited, or system is busy.
                  More information at https://help.mail.qq.com/detail/108/1023'
```

This is the **canonical 535-in-transcript signature** (Case A), NOT the silent-close variant (Case B). Important distinction: the silent-close variant is rare for this deployment; the explicit-535 variant is the norm. The current skill's "QQ silent-reject variant" callout in §5 over-emphasizes the rare case — future sessions may waste time looking for "no reply line" patterns that aren't there.

### Decision rule refinement

| Transcript signature | Mode | Frequency on this deployment |
|---|---|---|
| EHLO 250 → AUTH 334 → AUTH 334 → **535 Login fail** (explicit) | Case A — credential revoked, polite SMTP reply | **Common** (this session, 2026-08-23, Case A) |
| EHLO 250 → AUTH... → bare `SMTPServerDisconnected` (no `reply:` line) | Case B — credential revoked, aggressive anti-spam | Rare (Case B 2026-08-24 only) |
| Connect-time failure (timeout / ConnectionRefusedError / SSLError) | Case C — real network/firewall | Rare |

**For this QQ deployment specifically, expect Case A — the explicit 535.** The Case B silent-reject warning still applies (don't dismiss it as "network" if you see it), but the default mental model should be "expect a 535 line in the transcript; the bug is the auth code, not the network".

### Outbox accumulation: 27 HTML files at failure N=14

`~/.hermes/cron/outbox/toutiao/` now contains 27 HTML files (was 17 at Case H, +10 across Cases I + intervening runs that hit the same outage). At ~27 KB each, the cumulative on-disk size is 764 KB. **This is correct behavior** — every night's content is preserved.

The `outbox/toutiao/README.md` was extended with a "## 2026-09-07（持续中 — 第14天）" entry following the Case C/G convention. The README now reads as a cumulative outage log: 2026-08-25 (initial), 2026-09-07 (still ongoing). Future sessions checking this directory will see the live outage timestamp and skip the diagnostic loop entirely.

### Cross-script exposure unchanged

Every daily-content cron in `~/.hermes/cron/scripts/` shares the same `config_loader.get_mail_config()` and would fail identically today: `wechat-article-daily.py`, `unified-content-daily.py`, `xhs-travel-daily.py`, `xiaohongshu-travel-daily.py`, `xhs-escape-weekend.py`, `bithappy_email_pro.py`. None has the outbox-fallback fix yet. The Case C follow-up (extract `_email_helpers.py`) remains overdue by ~14 cron cycles. When the user finally fixes the auth code, every one of those scripts will recover simultaneously — but in the meantime, every night risks a different platform losing its content to the same auth-revocation failure.

### Lesson for the skill body, not just this case

The §5 SMTP deep-dive's "QQ Mail silent-reject variant" callout should be **re-ordered and re-weighted** — the explicit-535 (Case A) is the default mental model for QQ; the silent-reject (Case B) is a diagnostic edge case. The callout should lead with "you'll almost always see the explicit 535; only consider silent-reject when EHLO succeeds AND no `reply:` line appears between AUTH and the SMTPServerDisconnected." The manual AUTH LOGIN + getreply() recipe is the reliable diagnostic in either case.

## Case J — 15th consecutive identical SMTP failure: same-outage detection + time-to-failure fingerprint (2026-09-09)

The `toutiao-article-daily.py` cron failed for the **15th consecutive night** (since 2026-08-25). Same auth code (`iylylmwnitbbbebi`), same `Connection unexpectedly closed` symptom. By Case H logic this should be a 4-line terse dispatch and nothing else — but a fresh cron-session agent that has no prior context will run the full diagnostic loop before realizing the outage is chronic. The new lessons this cycle are about **detection efficiency** at the start of the session.

### Same-outage detection: the 5-second rule

Before any SMTP work, run the outbox-count check:

```bash
ls -1 ~/.hermes/cron/outbox/toutiao/*.html 2>/dev/null | wc -l
```

If the count is ≥3 AND the platform's `outbox/toutiao/README.md` doesn't end with an "Outage resolved" entry, you are looking at a known chronic failure. **Skip Steps 1-5 of the diagnostic loop and jump to Case H.** On this deployment at 2026-09-09 the outbox had 27 HTML files, README ended with "持续中 — 第14天" → obvious same-outage, no probe needed.

If the count is 1-2 (could be a new outage), do ONE confirmation probe and decide. If ≥3, the diagnosis is already done by previous sessions; your job is to surface it tersely and not waste tokens.

### Time-to-failure fingerprint

A revoked QQ SMTP auth code returns `535 Login fail` in **~0.6-0.8 seconds** of wall-clock time. Measured on this deployment (2026-09-09):

```
SMTP_SSL('smtp.qq.com', 465, timeout=15)  # opens in ~0.2s
server.ehlo()                              # ~0.05s
server.login(user, pass)                   # ~0.05s
# 535 returned, server closes socket
# Total: 0.62s before SMTPServerDisconnected raises
```

A real network problem (firewall blackhole, port blocked) typically takes **10-15 seconds** before the socket timeout fires. So:

| Wall-clock to failure | Likely cause | Action |
|---|---|---|
| < 1 second | Credential rejected by server | Case A — 535 in transcript. Fix the auth code. |
| 10-15 seconds | Socket timeout / firewall | Case C — real network problem. Try port 587, check firewall. |
| 1-10 seconds | Borderline — could be either | Run the manual AUTH LOGIN recipe to see whether the server sent a reply before closing |

This fingerprint is useful for **deciding whether to retry** without burning another full SMTP cycle. Combined with the outbox-count check, it gives a "same outage, skip probe" verdict in under 2 seconds total.

### Verified recipe refinements

1. **`debuglevel=2` also buries the 535** (not just `debuglevel=1`). The behavior is identical: smtplib retries AUTH LOGIN after AUTH PLAIN fails, and the second AUTH closes abruptly mid-`reply:`. Confirmed 2026-09-09. Updated the SKILL.md pitfall accordingly.
2. **The manual AUTH LOGIN + `getreply()` recipe from Case I is the only deterministic way to surface the 535** when it IS being sent. Always prefer it over `debuglevel` for terminal-typed probes on this deployment.
3. **Port 465 (SSL) and port 587 (STARTTLS) both fail identically** with the same 535. Confirmed 2026-09-09: `SMTP_SSL` and `SMTP+STARTTLS` both raise `SMTPServerDisconnected` in <1s after `login()`. The transport doesn't matter; the credential is the problem.
4. **The `formataddr((Header('Name', 'utf-8'), SMTP_USER))` From-header pattern is stable** — the 2026-08-23 "550 From header invalid" failure has not recurred in 15 nights. No action needed there.

### What was correctly NOT done this cycle

- Did NOT re-run `probe_smtp.py` — Case H says skip it at N≥10.
- Did NOT re-explain what `535 Login fail` means — README covers it.
- Did NOT paste the full SMTP transcript into the user-facing failure report — only mentioned the error string.
- Did NOT suggest "try port 587" — Case A already ruled out transport as the variable.
- Did NOT re-extract `_email_helpers.py` — known-overdue refactor, not this cron run's problem.

### Failure report shape used (this session, failure #15)

Hybrid pattern from Case H: 4-line headline + cross-script blast-radius counts + today's generated-content summary (title, direction, hook). Did NOT include the SMTP transcript. Did NOT include the port-587 alt-transport suggestion. Did NOT re-explain the credential fix — pointed at the config.yaml field by path.

Result: the report fits in one screen, names the file the article is saved to, tells the user exactly which config line to edit, and doesn't waste tokens re-proving what the previous 14 sessions already proved.

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
