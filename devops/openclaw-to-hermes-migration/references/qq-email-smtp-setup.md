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
QQ_EMAIL_AUTH_CODE=iylylmwnitbbbebi
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
msg['From'] = "权权管家 <569545015@qq.com>"
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

When a cron mail job suddenly starts failing, the error is almost always **shared infrastructure**, not the script. QQ auth codes can expire or get flagged by QQ's anti-abuse system without warning — this breaks every cron job that sends through that account at once.

**Diagnostic recipe (1 minute):**
```bash
# 1. Reproduce the failure outside the script
python3 -c "
import smtplib
with smtplib.SMTP_SSL('smtp.qq.com', 465, timeout=15) as s:
    s.login('YOUR_USER@qq.com', 'YOUR_AUTH_CODE')
    print('OK')
"

# 2. Check sibling cron logs to see if it's fleet-wide
tail -10 ~/.hermes/cron/logs/wechat-article-daily.log
tail -10 ~/.hermes/cron/logs/bithappy-email.log
tail -10 ~/.hermes/cron/logs/daily-report.log
tail -10 ~/.hermes/cron/logs/toutiao-article-daily.log
```

If **all** logs show the same `Connection unexpectedly closed` / `SMTPServerDisconnected`:
- It's the auth code, not the new job. Don't waste time debugging the new script.
- Regenerate at mail.qq.com → 设置 → 账户 → POP3/IMAP/SMTP/Exchange/CardDAV/CalDAV服务 → "生成授权码"
- Update `~/.hermes/cron/config/config.yaml` `mail.smtp_pass` (single source of truth used by `config_loader.py`)
- Re-test, then re-run failed jobs manually (HTML backups in `~/.hermes/cron/outbox/<job>/`)

If **only the new job's log** fails: it's the script. Check `From` header format, charset, retry logic.

**Why auth codes expire silently:** QQ rotates auth codes when the account has been idle, when security rules change, or after long periods without the user logging into mail.qq.com. There's no advance warning — the SMTP server just starts closing the connection mid-handshake.

**Backup safety net:** A well-built cron mail script writes the full HTML to `~/.hermes/cron/outbox/<job>/` when SMTP fails after retries. When you regenerate the auth code, you can re-send from the outbox directory without re-running the generator.

## Multiple Sender Names

When sending for different platforms, use different `From` names:

```python
# 小红书
msg['From'] = "权权养的虾 <569545015@qq.com>"

# 公众号/抖音
msg['From'] = "权权管家 <569545015@qq.com>"
```

Both use the same SMTP credentials but display different sender names to the recipient.
