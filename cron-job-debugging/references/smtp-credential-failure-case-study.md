# SMTP Credential Failure Case Study

Three real session transcripts covering the QQ SMTP auth-code failure modes this Hermes deployment hits repeatedly. Read in order: A (canonical 535), B (silent-reject variant), C (recurrence-class signal + the durable fix).

## Case A — Standard `535 Login fail` variant (2026-08-23)

Daily toutiao article cron `~/.hermes/cron/scripts/toutiao-article-daily.py` failed with `Connection unexpectedly closed`. Root cause: QQ Mail SMTP auth code was revoked.

## Symptom chain

```
❌ 发送失败：Connection unexpectedly closed
```

The cron script's `try/except Exception` block in `send_email()` swallowed the smtplib exception and printed only the exception's `str(e)`. Exit code 0, so the scheduler logged a "successful" run. Nothing reached the inbox.

## What the script's stdout DIDN'T show

`smtplib.SMTP_SSL.login()` raises `SMTPServerDisconnected("Connection unexpectedly closed")` when the server tears down the socket AFTER sending its rejection reply. The actual SMTP transcript (visible only with debuglevel) was:

```
send: 'AUTH PLAIN ADU2OTU0NTAxNUBxcS5jb20AaXlseWxtd25pdGJiYmViaQ==\r\n'
reply: b'535 Login fail. Account is abnormal, service is not open, password is
        incorrect, login frequency limited, or system is busy.\r\n'
send: 'AUTH LOGIN NTY2OTU0NTAxNUBxcS5jb20==\r\n'
send: 'QUIT\r\n'
SMTPServerDisconnected: Connection unexpectedly closed
```

The 535 is the actual error. The "Connection unexpectedly closed" is just the server hanging up after refusing the credential.

## Diagnostic recipe that worked

```bash
python3 -c "
import smtplib, socket
from email.mime.text import MIMEText
socket.setdefaulttimeout(30)
smtplib.SMTP.debuglevel = 1
with smtplib.SMTP_SSL('smtp.qq.com', 465, timeout=30) as s:
    s.login('569545015@qq.com', 'iylylmwnitbbbebi')
    s.sendmail('569545015@qq.com', '569545015@qq.com', 'Subject: t\n\ntest')
"
```

The debuglevel output revealed the 535 in one shot, distinguishing "auth dead" from "network dead" from "port blocked" (which would have given a different error like `ConnectionRefusedError` or `TimeoutError` BEFORE any `AUTH` command).

## Credential sources checked

1. `~/.hermes/cron/config/config.yaml` → `smtp_pass: iylylmwnitbbbebi` → 535
2. Environment variable `QQ_EMAIL_AUTH_CODE` → 535 (same value, also dead)

Both pointed to the same authorization code being revoked. Could NOT be fixed by the agent — required the user to log into https://mail.qq.com and regenerate the SMTP authorization code.

## Lessons

1. **Always enable smtplib debuglevel when triaging "Connection unexpectedly closed".** The error string is a red herring; the 535 in the transcript is the truth.
2. **The Hermes cron `config_loader.py` reads from YAML first, env as fallback.** So if the YAML auth code is wrong, the script fails even if you `export QQ_EMAIL_AUTH_CODE=...` in your shell. The env var is only consulted if `import config_loader` fails (the `try/except ImportError` fallback). If the user is wondering why "I set the env var and it still fails" — that's why.
3. **Cron scripts do NOT inherit interactive env vars.** A script that uses `os.environ['QQ_EMAIL_AUTH_CODE']` will see an empty string when run from the scheduler, even if you set it in your shell. Test by `print(os.environ.get('QQ_EMAIL_AUTH_CODE'))` at the top of the script under cron context.
4. **Save today's content locally as a fallback.** When sendmail fails, the article is still generated — the script just lost it. The fix is to write the rendered HTML/text to `~/.hermes/cron/output/<script>_<timestamp>.{html,txt}` BEFORE attempting delivery. Then the user has today's article on disk while the auth is being fixed.

## Workaround code added to the failure report

```python
# In cron script, after generate_article() but before/at send_email():
out_dir = os.path.expanduser('~/.hermes/cron/output')
os.makedirs(out_dir, exist_ok=True)
ts = datetime.now().strftime('%Y-%m-%d_%H-%M')
with open(f'{out_dir}/toutiao_{ts}.html', 'w', encoding='utf-8') as f:
    f.write(full_html)
with open(f'{out_dir}/toutiao_{ts}.txt', 'w', encoding='utf-8') as f:
    f.write(plain_text + '\n\n微头条:\n' + '\n'.join(m['content'] for m in micros))
```

This pattern should be added to every daily-content cron script (not just toutiao) — `daily_report.py`, `xhs-travel-daily.py`, `xiaohongshu-travel-daily.py`, `xhs-escape-weekend.py`, `bithappy_email_pro.py`, `unified-content-daily.py` all have the same vulnerability.

## Case B — QQ silent-reject variant, NO `535` in transcript (2026-08-24)

Same script, same `Connection unexpectedly closed` symptom, BUT the diagnostic signature was completely different from Case A. Documenting because the existing Case A recipe ("enable debuglevel, look for 535") leads the operator astray here.

### What `debuglevel=1` showed

```text
send: 'EHLO test\r\n'
reply: b'250 newxmesmtplogicsvrsza63-0.qq.com\r\nPIPELINING\r\nSIZE 73400320\r\nAUTH LOGIN PLAIN XOAUTH XOAUTH2\r\nAUTH=LOGIN ...'
send: 'AUTH PLAIN <base64>\r\n'
# <<< NOTHING HERE — no reply line, no 535 >>>
SMTPServerDisconnected: Connection unexpectedly closed
```

The 535 line is **missing**. The server accepted EHLO cleanly, accepted AUTH PLAIN framing, then closed the TLS socket mid-handshake with no SMTP-level reply. `debuglevel` only shows what smtplib sees on the wire — and QQ's anti-spam is dropping the connection at the TCP layer before sending a status code.

### Why this matters

The Case A diagnostic recipe ("look at the 535 in the transcript") leads the operator to conclude "no 535 means it's not auth, must be network/firewall" — and chase the wrong fix for hours. **This is wrong.** The actual cause is still credential revocation; QQ just revoked it more aggressively this time and the server doesn't bother to send a polite SMTP reply before hanging up.

### How to distinguish from a real network problem

| Probe | Silent-reject (this case) | Real network/firewall failure |
|---|---|---|
| `SMTP_SSL(465)` EHLO | Clean 250 reply | Hangs at connect, or `ConnectionRefusedError`, or `ssl.SSLError` |
| `SMTP(587)` + STARTTLS EHLO | Clean 250 reply | Same — connect-time failure |
| AUTH after either EHLO | Server closes socket, **no SMTP reply** | Server never reaches AUTH (connect hangs first) |
| Retry loop × 3 | Same silent close every time | Intermittent (timeout now, success later) |
| Other recipients | Same silent close (auth-code-scoped) | May succeed for some hosts (firewall-scoped) |

**The defining signal:** EHLO succeeds, then AUTH dies with no `reply:` line. If you see this, the credential is dead — same fix as Case A (regenerate in QQ web UI). Don't waste time on firewall/proxy/network debugging.

### What fixed it (in this session)

The same as Case A — required user to log into https://mail.qq.com → 设置 → 账户 → generate a new SMTP authorization code, then update both `~/.hermes/cron/config/config.yaml` (`smtp_pass`) AND `~/.hermes/.env` (`QQ_EMAIL_AUTH_CODE`). They were the same value (`iylylmwnitbbbebi`) and both were revoked.

### Additional lesson not in Case A

**Two-source-of-truth, both stale.** This deployment stores the SMTP credential in TWO places: `config.yaml` (read by `config_loader.py` at runtime) and `~/.hermes/.env` (`QQ_EMAIL_AUTH_CODE`, read by other paths). Both were last updated together, so they drift in lockstep. A common reflex when fixing SMTP is to update only one and re-test; that test still fails because the other still has the dead value. Diff both before regenerating:

```bash
diff <(grep -oE '"[a-z]{16}"' ~/.hermes/cron/config/config.yaml | tr -d '"') \
     <(grep -oE 'QQ_EMAIL_AUTH_CODE=[a-z]{16}' ~/.hermes/.env | cut -d= -f2) \
  && echo "✅ Both stores match — only one credential to regenerate"
```

When they match, you have ONE credential problem, not two. When they differ, you have TWO — fix both, in order: regenerate on QQ web UI, update YAML (takes effect immediately for next run), update .env (for any script that reads env directly).

## Case C — Recurrence after fix: same code, same script, same week (2026-08-25)

Two days after Case B's fix, the same `toutiao-article-daily.py` cron failed again with the identical `535 Login fail` symptom on the identical `iylylmwnitbbbebi` auth code. Documenting as Case C so future sessions recognize the pattern: **QQ Mail SMTP authorization codes in this deployment have a recurring ~weekly-to-biweekly revocation cycle**, not a one-time expiry.

### What was different from Case A/B

The diagnostic path was already known — went straight to `smtplib.SMTP.debuglevel = 1` and confirmed the 535 in one shot. What was NEW and worth capturing:

1. **Content-loss prevention code shipped to the script.** Before this session, the script's `send_email()` had a bare `try/except Exception` that swallowed `SMTPServerDisconnected` and exited 0 — the article was lost. The fix layered:
   - One retry on transient `(SMTPServerDisconnected, SMTPException, OSError)` with 3s sleep
   - On final failure, save the rendered HTML to `~/.hermes/cron/outbox/toutiao/<YYYYMMDD_HHMM>_<direction>.html`
   - Embed the absolute path in the error message so the failure report can show the user where today's content lives
2. **The `outbox/` tree pattern.** Separate from `~/.hermes/cron/output/<job_id>/` (scheduler logs) to avoid colliding with the scheduler's auto-managed log rotation. Each delivery platform gets its own subdir + a `README.md` summarizing the most recent outage and the user-side fix.
3. **The user-facing failure message now reads like a runbook entry**, not just an error: `❌ 发送失败：Connection unexpectedly closed (重试2次仍失败，HTML已备份: /home/ubuntu/.hermes/cron/outbox/toutiao/20260825_2031_亲戚恩怨.html)` — points directly at the artifact.

### Why this matters as a recurring-class signal

If you see "Connection unexpectedly closed" from `569545015@qq.com` SMTP, **do not spend time re-diagnosing**. The credential is almost certainly revoked again. Jump straight to:

1. Run `scripts/probe_smtp.py` (or the manual `debuglevel=1` recipe) to confirm the 535 / silent-reject pattern
2. Tell the user: "QQ Mail SMTP auth code revoked again — please regenerate at https://mail.qq.com → 设置 → 账户 → POP3/IMAP/SMTP/Exchange/CardDAV/CalDAV服务"
3. Point them at the outbox backup for today's content
4. Update `~/.hermes/cron/config/config.yaml` (and `~/.hermes/.env` if it's a different value) with the new code

The next cron run after the update will succeed. Do NOT apply this same code to `wechat-article-daily.py`, `unified-content-daily.py`, etc. proactively — they share the same credential and will fail identically, but the user only needs to fix it once in the YAML. Updating the outbox tree template per-script is fine (so each platform has its own `outbox/<platform>/README.md` with the current outage timestamp), but the auth fix is centralized.

### Same outbox pattern needed in other daily-content scripts

Identical vulnerability exists in: `wechat-article-daily.py`, `unified-content-daily.py`, `xhs-travel-daily.py`, `xiaohongshu-travel-daily.py`, `xhs-escape-weekend.py`, `bithappy_email_pro.py`, `daily_report.py`. All use the same `config_loader.py::get_mail_config()` and the same fragile `try/except Exception` around `smtplib.SMTP_SSL.login()`. Apply the Case C fix (retry + outbox backup) to each — or refactor `send_email()` into a shared helper under `~/.hermes/cron/scripts/_email_helpers.py` that all of them import. The helper is the right answer if you expect this revocation pattern to keep recurring.
