# `toutiao-article-daily.py` recurring outage: 2026-08-25 → 2026-09-03 (10 nights)

A real recurring failure on this Hermes deployment, captured for future sessions to recognize instantly.

## What's broken

The nightly `toutiao-article-daily.py` cron (scheduled via Hermes `jobs.json` at 20:30) cannot deliver its HTML email to `569545015@qq.com` because the QQ Mail SMTP authorization code in `~/.hermes/cron/config/config.yaml` was revoked by QQ's anti-spam system sometime before 2026-08-25.

## Symptom (every night, identical)

```
🏠 权权的HERMES · 头条号文章生成器 v1.1.0
...
❌ 发送失败：Connection unexpectedly closed (重试2次仍失败，HTML已备份: .../outbox/toutiao/20260903_2030_赡养义务.html)
```

The script's own stderr surfaces only the generic `SMTPServerDisconnected("Connection unexpectedly closed")`. The actual root cause (535 Login fail) is invisible until you re-run with `smtplib.SMTP.debuglevel = 2`.

## Diagnostic confirmation (SMTP transcript excerpt)

```
send: 'AUTH PLAIN ADU2OTU0NTAxNUBxcS5jb20AaXlseWxtd25pdGJiYmViaQ==\r\n'
reply: b'535 Login fail. Account is abnormal, service is not open, password is incorrect,
        login frequency limited, or system is busy. ...\r\n'
reply: retcode (535); Msg: b'...'
send: 'AUTH LOGIN NTY5NTQ1MDE1QHFxLmNvbQ==\r\n'
Error: SMTPServerDisconnected: Connection unexpectedly closed
```

This matches **Case A** in the SKILL.md SMTP deep-dive (535-in-transcript) combined with **Case B** characteristics (the server closes the socket after the second AUTH LOGIN attempt with no further `reply:` line). The auth code is dead.

## Outbox accumulation

`~/.hermes/cron/outbox/toutiao/` grows by 1 file per failed night (~27 KB each). As of 2026-09-03 it contains ~17 HTML files from this outage, plus earlier successful backups. This is **correct behavior** — the script's failure-path writeback is the only thing keeping the daily content from being lost.

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
   python3 -c "
   import smtplib
   s = smtplib.SMTP_SSL('smtp.qq.com', 465, timeout=20)
   s.login('569545015@qq.com', 'NEW_16_CHAR_AUTH_CODE')
   print('OK')
   s.quit()"
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

## Scripts involved

- `~/.hermes/cron/scripts/toutiao-article-daily.py` — has working outbox-fallback pattern (Case C reference implementation)
- `~/.hermes/cron/scripts/config_loader.py` — `get_mail_config()` reads from `config.yaml`; YAML is the canonical source, not env vars
- `~/.hermes/cron/config/config.yaml` — line that needs editing: `smtp_pass`