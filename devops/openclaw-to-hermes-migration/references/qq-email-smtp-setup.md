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
| Chinese characters garbled | Missing charset | Use `MIMEText(html, 'html', 'utf-8')` |

## Multiple Sender Names

When sending for different platforms, use different `From` names:

```python
# 小红书
msg['From'] = "权权养的虾 <569545015@qq.com>"

# 公众号/抖音
msg['From'] = "权权管家 <569545015@qq.com>"
```

Both use the same SMTP credentials but display different sender names to the recipient.
