# SMTP Credential Failure Case Study

Real session transcript (2026-08-23): daily toutiao article cron `~/.hermes/cron/scripts/toutiao-article-daily.py` failed with `Connection unexpectedly closed`. Root cause: QQ Mail SMTP auth code was revoked.

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
send: 'AUTH LOGIN NTY5NTQ1MDE1QHFxLmNvbQ==\r\n'
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
