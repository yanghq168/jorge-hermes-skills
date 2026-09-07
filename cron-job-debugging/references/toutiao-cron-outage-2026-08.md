# `toutiao-article-daily.py` recurring outage: 2026-08-25 → 2026-09-07 (14 nights, ongoing)

A real recurring failure on this Hermes deployment, captured for future sessions to recognize instantly.

## What's broken

The nightly `toutiao-article-daily.py` cron (scheduled via Hermes `jobs.json` at 20:30) cannot deliver its HTML email to `569545015@qq.com` because the QQ Mail SMTP authorization code in `~/.hermes/cron/config/config.yaml` was revoked by QQ's anti-spam system sometime before 2026-08-25.

## Symptom (every night, identical)

```
🏠 权权的HERMES · 头条号文章生成器 v1.1.0
...
❌ 发送失败：Connection unexpectedly closed (重试2次仍失败，HTML已备份: .../outbox/toutiao/20260907_2030_赡养义务.html)
```

The script's own stderr surfaces only the generic `SMTPServerDisconnected("Connection unexpectedly closed")`. The actual root cause (535 Login fail) is invisible until you re-run with `smtplib.SMTP.debuglevel = 2` or with the manual AUTH LOGIN recipe below.

## Diagnostic confirmation (SMTP transcript excerpt — manual AUTH recipe, 2026-09-07)

The most reliable way to surface the 535 is to drive the SMTP session yourself so each protocol reply is its own line. `debuglevel=1` works but smtplib retries AUTH after the first 535 and the second AUTH closes abruptly — the 535 can scroll past fast.

```python
import smtplib, base64
server = smtplib.SMTP_SSL('smtp.qq.com', 465, timeout=15)
server.ehlo()
server.send(b"AUTH LOGIN\r\n")
code, msg = server.getreply()       # 334 VXNlcm5hbWU6  (base64 "Username:")
server.send(base64.b64encode(b'569545015@qq.com') + b'\r\n')
code, msg = server.getreply()       # 334 UGFzc3dvcmQ6  (base64 "Password:")
server.send(base64.b64encode(b'iylylmwnitbbbebi') + b'\r\n')
code, msg = server.getreply()       # 535 Login fail. Account is abnormal, ...
```

Actual output (2026-09-07, deployment unchanged since 2026-08-25):

```
EHLO: 250: b'newxmesmtplogicsvrszb51-0.qq.com\nPIPELINING\n... AUTH LOGIN PLAIN XOAUTH XOAUTH2\n...'
AUTH LOGIN -> 334: b'VXNlcm5hbWU6'
username -> 334: b'UGFzc3dvcmQ6'
password -> 535: b'Login fail. Account is abnormal, service is not open, password is incorrect, login frequency limited, or system is busy. More information at https://help.mail.qq.com/detail/108/1023'
```

This matches **Case A** in the SKILL.md SMTP deep-dive (535-in-transcript, polite SMTP reply). The Case B silent-reject signature (no `reply:` line between AUTH and SMTPServerDisconnected) has been observed once on this deployment (2026-08-24) but is the exception, not the norm.

## Outbox accumulation

`~/.hermes/cron/outbox/toutiao/` grows by 1-2 files per failed night (~27 KB each). As of 2026-09-07 it contains **27 HTML files** from this outage, plus earlier successful backups (~764 KB cumulative). This is **correct behavior** — the script's failure-path writeback is the only thing keeping the daily content from being lost. The `outbox/toutiao/README.md` was extended with a "## 2026-09-07（持续中 — 第14天）" entry following the Case C/G convention; the README is the durable outage log that survives across cron-job-script edits.

## Outage history (cumulative failure count, days)

| Date | Failure # | Notes |
|---|---|---|
| 2026-08-25 | 1 | Initial detection. Outbox pattern shipped to script. |
| 2026-08-26 → 2026-08-31 | 2-7 | Same code, same symptom; "do not re-diagnose" rule established (Cases C/D/E). |
| 2026-09-02 | 8 | Case G — importlib bypass for content inspection without burning SMTP. |
| 2026-09-03 | 10 | Case H — terse runbook dispatch mode (no more probes, just point at outbox + fix). |
| 2026-09-04 → 2026-09-07 | 11-14 | Status quo. Manual AUTH LOGIN recipe added (Case I, this session). |

**Decision rule at N≥10:** skip the diagnostic loop entirely. The credential state has not changed in over a week. The outbox has today's content. Report = outbox path + the one-line fix. Don't re-run `probe_smtp.py`, don't paste transcripts, don't suggest port 587.

## The fix (verbatim, for the user)

1. Open https://mail.qq.com/ in a browser, log in as `569545015@qq.com`
2. **设置** → **账户** → **POP3/IMAP/SMTP/Exchange/CardDAV/CalDAV服务**
3. Locate **SMTP发信服务** (or "SMTP service") — should show "已开启" with a generated 16-char auth code
4. Click **生成授权码** — QQ will send an SMS to the bound phone; enter the code
5. Copy the new 16-char string
6. Edit `~/.hermes/cron/config/config.yaml`:
   ```yaml
   mail:
     smtp_pass: "NEW_16_CHAR_AUTH_CODE"   # replace iylylmwnitbbbebi
   ```
7. Verify from this shell:
   ```bash
   python3 ~/.hermes/cron/scripts/probe_smtp.py
   # Expected: "✅ LOGIN OK — credential is valid"
   ```
8. Re-run the cron once: `hermes cron run <job_id>` (or wait for 20:30)
9. After 2 successful nights, archive the outbox:
   ```bash
   mkdir -p ~/.hermes/cron/outbox/toutiao/$(date +%Y-%m)_archive
   ls -t ~/.hermes/cron/outbox/toutiao/*.html | tail -n +2 | \
     xargs -I {} mv {} ~/.hermes/cron/outbox/toutiao/$(date +%Y-%m)_archive/
   ```

## Why the fix hasn't happened yet

Most likely: the user is either away from the QQ-registered phone (so step 4 SMS can't be received), or has deprioritized this cron relative to other work. The cron does its job (content is generated and backed up locally), so the failure is invisible to anyone not watching the destination mailbox.

## Scripts involved (all share the same `iylylmwnitbbbebi` credential — all fail together, only one update to recover them all)

- `~/.hermes/cron/scripts/toutiao-article-daily.py` — has working outbox-fallback pattern (Case C reference implementation)
- `~/.hermes/cron/scripts/config_loader.py` — `get_mail_config()` reads from `config.yaml`; YAML is the canonical source, not env vars
- `~/.hermes/cron/config/config.yaml` — line that needs editing: `smtp_pass`

**Other scripts that would fail identically today** (no outbox fix yet — content is lost when SMTP fails):

- `~/.hermes/cron/scripts/wechat-article-daily.py`
- `~/.hermes/cron/scripts/unified-content-daily.py`
- `~/.hermes/cron/scripts/xhs-travel-daily.py`
- `~/.hermes/cron/scripts/xiaohongshu-travel-daily.py`
- `~/.hermes/cron/scripts/xhs-escape-weekend.py`
- `~/.hermes/cron/scripts/bithappy_email_pro.py`

The shared `_email_helpers.py` extraction (proposed in Case C, repeated in E + F + G + H + I) remains the overdue refactor — until it lands, each script silently drops its content instead of saving to outbox when SMTP breaks. Per Case E, a third-party transactional mail relay (Resend / SMTP2GO / SendGrid) with a static API key is the migration that would permanently end this weekly revocation cycle.