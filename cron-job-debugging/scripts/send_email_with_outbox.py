#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
send_email_with_outbox.py - drop-in replacement for the bare
`smtplib.SMTP_SSL(...).login().sendmail()` pattern used by the
Hermes cron scripts at ~/.hermes/cron/scripts/.

Adds the two failure modes the bare pattern silently swallows:
  1. One retry on transient SMTPServerDisconnected (3s backoff)
  2. Final-failure backup to ~/.hermes/cron/outbox/<platform>/
     with the absolute path embedded in the returned error

Use from any cron script that imports a `send_email()` function:

    from send_email_with_outbox import send_email_with_outbox as send_email
    # then call as before:
    success, msg = send_email(html, plain, topic, micros, platform='toutiao')

If `platform` is omitted it defaults to 'email'.

Reads SMTP credentials from config_loader.get_mail_config() at import time
(matches the existing pattern in this deployment). Override SMTP_* globals
in the caller if you need different credentials.

Reference: cron-job-debugging skill, SMTP deep-dive Step 6.
Author: Hermes Agent (2026-08-25, after third QQ auth revocation that week)
"""

import sys
import time
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.header import Header
from email.utils import formataddr
from pathlib import Path

try:
    from config_loader import get_mail_config
    _mail = get_mail_config()
    SMTP_SERVER = _mail.get('smtp_server', 'smtp.qq.com')
    SMTP_PORT = int(_mail.get('smtp_port', 465))
    SMTP_USER = _mail.get('smtp_user', '')
    SMTP_PASS = _mail.get('smtp_pass', '')
    TO_EMAIL = _mail.get('to_email', SMTP_USER)
except Exception:
    SMTP_SERVER = "smtp.qq.com"
    SMTP_PORT = 465
    SMTP_USER = ""
    SMTP_PASS = ""
    TO_EMAIL = ""

OUTBOX_ROOT = Path("/home/ubuntu/.hermes/cron/outbox")


def send_email_with_outbox(
    html_content: str,
    plain_text: str,
    topic: dict,
    micro_articles=None,
    sender_label: str = "围炉家常话",
    platform: str = "email",
):
    """Build, attempt-send (with retry), and back-up an HTML email.

    Args:
        html_content:  full HTML body of the main article
        plain_text:    plain-text alternative body
        topic:         dict with 'direction' and 'title' (used for subject + filename)
        micro_articles: optional list of dicts each with 'html' key — appended to body
        sender_label:  display name shown in the From: header
        platform:      subdir under OUTBOX_ROOT for backups ('toutiao', 'wechat', etc.)

    Returns:
        (success: bool, message: str) — message is human-readable, embeds the
        backup path on failure.
    """
    micro_html = ""
    if micro_articles:
        micro_html = "\n".join(m.get("html", "") for m in micro_articles)
    full_html = html_content + micro_html

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"【{platform}·{topic.get('direction', '')}】{topic.get('title', '')}"
    msg["From"] = formataddr((str(Header(sender_label, "utf-8")), SMTP_USER))
    msg["To"] = TO_EMAIL
    msg.attach(MIMEText(plain_text, "plain", "utf-8"))
    msg.attach(MIMEText(full_html, "html", "utf-8"))

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

    # Both attempts failed → back up HTML to outbox so today's content isn't lost
    try:
        outbox = OUTBOX_ROOT / platform
        outbox.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        fname = outbox / f"{ts}_{topic.get('direction', 'unknown')}.html"
        fname.write_text(full_html, encoding="utf-8")
        return False, f"{last_err} (重试2次仍失败，HTML已备份: {fname})"
    except Exception as ee:
        return False, f"{last_err} | backup_err={ee}"


if __name__ == "__main__":
    # Smoke test — only runs if executed directly
    print("This module is meant to be imported, not run directly.")
    print(f"SMTP target: {SMTP_USER}@{SMTP_SERVER}:{SMTP_PORT}")
    print(f"Outbox root: {OUTBOX_ROOT}")
    sys.exit(0)
