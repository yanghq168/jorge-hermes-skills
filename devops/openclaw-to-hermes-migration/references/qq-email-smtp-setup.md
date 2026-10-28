# QQ Email SMTP Configuration for Cron Jobs

Many migrated OpenClaw cron jobs use QQ email (腾讯邮箱) for sending content. This reference documents the exact setup.

## Configuration

### config.yaml
```yaml
mail:
  smtp_server: "smtp.qq.com"
  smtp_port: 465          # SSL port (NOT 587)
  smtp_user: "569545015@qq.com"
  smtp_pass: "YOUR_AUTH_CODE"  # 16-char authorization code, NOT login password
  to_email: "569545015@qq.com"
```

### Environment variables (optional)
```bash
QQ_EMAIL_AUTH_CODE=<REVOKED_AUTH_CODE>
QQ_EMAIL_USER=569545015@qq.com
```

## Getting the Authorization Code

1. Login to QQ Mail web: https://mail.qq.com
2. Settings → Accounts
3. Find: POP3/IMAP/SMTP/Exchange/CardDAV/CalDAV Services
4. Enable **IMAP/SMTP Service**
5. Send verification SMS as prompted
6. Receive 16-character authorization code (e.g., `abcdxyz123456789`)

**Important:** This is NOT your QQ password. It's a separate app-specific password.

## Python Test Script

```python
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

SMTP_SERVER = "smtp.qq.com"
SMTP_PORT = 465
SMTP_USER = "569545015@qq.com"
SMTP_PASS = "YOUR_AUTH_CODE"

msg = MIMEMultipart('alternative')
msg['Subject'] = "Test Email"
msg['From'] = "权权的HERMES <569545015@qq.com>"
msg['To'] = "569545015@qq.com"

html = "<html><body><h2>Test</h2></body></html>"
msg.attach(MIMEText(html, 'html', 'utf-8'))

context = ssl.create_default_context()
with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, context=context) as server:
    server.login(SMTP_USER, SMTP_PASS)
    server.send_message(msg)
print("Email sent successfully")
```

## Common Issues

| Issue | Cause | Fix |
|-------|-------|-----|
| `Authentication failed` | Using QQ password instead of auth code | Use the 16-char authorization code |
| `Connection refused` on port 587 | QQ requires SSL on 465 | Use port 465 with `SMTP_SSL` |
| `smtplib.SMTPAuthenticationError` | Auth code expired or service not enabled | Re-enable SMTP in QQ Mail settings |
| `SMTPServerDisconnected: Connection unexpectedly closed` | QQ SMTP rate-limiting or anti-abuse triggered on stale auth code | Re-generate auth code at mail.qq.com → 设置 → 账户 → POP3/IMAP/SMTP服务. If many cron jobs fail simultaneously, see "Fleet-wide failure diagnostic" below. |
| Chinese characters garbled | Missing charset | Use `MIMEText(html, 'html', 'utf-8')` |

## Fleet-wide Failure Diagnostic

> **This section defers to the `cron-job-debugging` skill**, which owns the
> canonical diagnosis for QQ SMTP credential failures. That skill has the
> full evidence trail (Case A/B transcripts, the `scripts/probe_smtp.py`
> probe, the escalation policy by failure count, and the outbox recovery
> recipe). What follows is only the migration-specific starting point.

When a migrated cron mail job suddenly starts failing, the error is almost
always **shared infrastructure**, not the script: QQ auth codes get revoked by
QQ's anti-abuse system without warning, which breaks every cron job that sends
through that account at once.

**Start here (1 minute):**

```bash
# 1. Reproduce outside the script
python3 -c "
import smtplib
with smtplib.SMTP_SSL('smtp.qq.com', 465, timeout=15) as s:
    s.login('YOUR_USER@qq.com', 'YOUR_AUTH_CODE')
    print('OK')
"

# 2. Check sibling cron logs to see if it's fleet-wide
tail -10 ~/.hermes/cron/logs/wechat-article-daily.log
tail -10 ~/.hermes/cron/logs/toutiao-article-daily.log
```

If **all** logs show the same `Connection unexpectedly closed` /
`SMTPServerDisconnected`: it's the auth code, not your new job. Don't debug the
new script. Regenerate at mail.qq.com → 设置 → 账户 → POP3/IMAP/SMTP服务, update
`mail.smtp_pass` in `~/.hermes/cron/config/config.yaml` (the single source of
truth read by `config_loader.py`), then re-run the failed jobs — HTML backups in
`~/.hermes/cron/outbox/<job>/` let you re-send without re-generating content.

**Full diagnosis (535 vs silent-reject vs real network fault, blast-radius
across sibling scripts, outbox recovery, escalation policy):**
→ `cron-job-debugging` skill, §5 "SMTP / credential failure deep-dive" and
`references/smtp-credential-failure-case-study.md`.

**Backup safety net:** a well-built cron mail script writes the full HTML to
`~/.hermes/cron/outbox/<job>/` when SMTP fails after retries. When you
regenerate the auth code you can re-send from the outbox without re-running the
generator — `cron-job-debugging/scripts/resend_outbox_html.py` automates this.

## Multiple Sender Names

When sending for different platforms, use different `From` names:

```python
# 小红书
msg['From'] = "权权的HERMES（小红书） <569545015@qq.com>"

# 公众号
msg['From'] = "权权的HERMES（公众号） <569545015@qq.com>"

# 头条号
msg['From'] = "权权的HERMES（头条） <569545015@qq.com>"
```

Both use the same SMTP credentials but display different sender names to the recipient.

⚠️ **Brand-name warning.** `权权养的虾` and `权权管家` are **obsolete** sender
names — the current branding is `权权的HERMES（<平台>）`. Sending under an old
name is a symptom of a stale script still running (see the duplicate-task
reference). If you need to find and fix legacy senders:

```bash
grep -rn "权权养的虾\|权权管家" ~/.hermes/cron/scripts/
```

The canonical per-platform sender labels live in the `content-platforms` skill.
