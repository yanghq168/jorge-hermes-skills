#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
resend_outbox_html.py - re-deliver an HTML backup that was saved to
~/.hermes/cron/outbox/<platform>/ when SMTP delivery failed.

Use case: after a chronic SMTP outage ends (the user regenerates the
QQ auth code in mail.qq.com and updates config.yaml), the cron will
start succeeding again from the NEXT scheduled run, but the user has
N days of accumulated HTML in the outbox that never reached the
inbox. Run this script to push them.

Two modes:

1. Default — send the latest backup for a platform:
       python3 resend_outbox_html.py toutiao
       python3 resend_outbox_html.py wechat
       python3 resend_outbox_html.py email

2. With --file — send a specific backup:
       python3 resend_outbox_html.py toutiao --file 20260920_2030_房产纠纷.html

3. With --all — sweep every backup in the platform's outbox, newest-first,
   stopping at the first success (don't burn the new auth code on history):
       python3 resend_outbox_html.py toutiao --all

Reads SMTP credentials from config_loader.get_mail_config() at import
time (matches the convention in this deployment).

Subject reconstruction: the script extracts <h1>...</h1> from the HTML
body to use as the email subject; if not found, falls back to the
filename. This is best-effort — the outbox HTML is the source of
truth, the subject is derived.

Reference: cron-job-debugging skill, Case P (2026-09-20) +
references/toutiao-cron-outage-2026-08.md "When the user finally fixes
it" recovery section.
"""

import argparse
import re
import sys
import time
import smtplib
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
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
except Exception as e:
    print(f"❌ Failed to load mail config: {e}", file=sys.stderr)
    print("   Check ~/.hermes/cron/config/config.yaml exists and has a 'mail:' section.", file=sys.stderr)
    sys.exit(2)

OUTBOX_ROOT = Path("/home/ubuntu/.hermes/cron/outbox")

# Maps platform -> sender display name in the From: header.
# Falls back to the platform name itself if not listed.
SENDER_LABEL = {
    "toutiao": "围炉家常话（头条）",
    "wechat": "围炉家常话（公众号）",
    "xhs": "围炉家常话（小红书）",
    "unified": "围炉家常话",
    "email": "Hermes Agent",
}


def extract_subject(html, fallback):
    """Extract <h1>...</h1> from HTML, strip tags, cap at 80 chars."""
    m = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.S)
    if not m:
        m = re.search(r'<title>(.*?)</title>', html, re.S)
    if m:
        title = re.sub(r'<[^>]+>', '', m.group(1)).strip()
        return title[:80] if title else fallback
    return fallback


def send_one(html_path, sender_label, platform):
    """Read HTML from html_path and try to send it. Returns (success, msg)."""
    html = html_path.read_text(encoding='utf-8')
    title = extract_subject(html, fallback=html_path.stem)
    subject = f'【{platform}·重发】{title}'

    msg = MIMEMultipart('alternative')
    msg['Subject'] = Header(subject, 'utf-8')
    msg['From'] = formataddr((str(Header(sender_label, 'utf-8')), SMTP_USER))
    msg['To'] = TO_EMAIL
    msg.attach(MIMEText(f'重发自 {html_path}（重发于 SMTP 恢复后）', 'plain', 'utf-8'))
    msg.attach(MIMEText(html, 'html', 'utf-8'))

    last_err = None
    # 3 attempts with backoff — we're recovering from a known-broken state
    # and want to give the new credential a fair shake before declaring failure.
    for attempt in range(3):
        try:
            print(f'  attempt {attempt+1}/3 → {TO_EMAIL}', flush=True)
            with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=30) as s:
                s.login(SMTP_USER, SMTP_PASS)
                s.sendmail(SMTP_USER, [TO_EMAIL], msg.as_string())
            return True, f'✅ 发送成功: {subject}'
        except (smtplib.SMTPServerDisconnected, smtplib.SMTPException, OSError) as e:
            last_err = e
            wait = 3 * (attempt + 1)
            print(f'  ⚠️ {type(e).__name__}: {e} → 等待 {wait}s 后重试', flush=True)
            time.sleep(wait)
    return False, f'❌ 重发失败 (3 次重试): {last_err}'


def main():
    parser = argparse.ArgumentParser(
        description='Resend a saved HTML backup from the cron outbox.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('platform', help='outbox subdirectory name (toutiao, wechat, etc.)')
    parser.add_argument('--file', help='specific backup filename (default: latest)', default=None)
    parser.add_argument('--all', action='store_true', help='send every backup, newest first')
    args = parser.parse_args()

    outbox_dir = OUTBOX_ROOT / args.platform
    if not outbox_dir.exists():
        print(f'❌ Outbox directory not found: {outbox_dir}', file=sys.stderr)
        print(f'   Has the cron ever failed for platform={args.platform}?', file=sys.stderr)
        sys.exit(1)

    backups = sorted(outbox_dir.glob('*.html'), key=lambda p: p.stat().st_mtime, reverse=True)
    if not backups:
        print(f'❌ No HTML backups in {outbox_dir}', file=sys.stderr)
        sys.exit(1)

    if args.file:
        targets = [outbox_dir / args.file]
        if not targets[0].exists():
            print(f'❌ File not found: {targets[0]}', file=sys.stderr)
            sys.exit(1)
    elif args.all:
        targets = backups
        print(f'📤 Will attempt to resend all {len(targets)} backups, newest first')
    else:
        targets = [backups[0]]
        print(f'📤 Will attempt to resend latest: {targets[0].name}')
        print(f'   ({len(backups)-1} older backups in outbox — pass --all to attempt them too)')

    sender_label = SENDER_LABEL.get(args.platform, args.platform)
    print(f'📧 SMTP: {SMTP_USER}@{SMTP_SERVER}:{SMTP_PORT} → {TO_EMAIL}')
    print(f'✉️ From: {sender_label}')
    print()

    successes, failures = 0, 0
    for path in targets:
        print(f'[{successes+failures+1}/{len(targets)}] {path.name}')
        ok, msg = send_one(path, sender_label, args.platform)
        print(f'  {msg}')
        if ok:
            successes += 1
            if not args.all:
                # Default mode: stop after first success — the user only
                # asked for the latest one. --all explicitly opts in to
                # burning the (new, possibly rate-limited) auth code on history.
                print()
                print(f'✅ 最新一份已发送。剩余 {len(targets)-1} 份历史备份未重发，')
                print(f'   如需全部重发请加 --all 参数。')
                break
        else:
            failures += 1
            if failures >= 2 and not args.all:
                print()
                print('⚠️ 连续失败 ≥2 次，停止。可能是凭据问题：')
                print('   1. python3 ~/.hermes/skills/cron-job-debugging/scripts/probe_smtp.py')
                print('   2. 检查 ~/.hermes/cron/config/config.yaml 的 smtp_pass 是否是最新的')
                break

    print()
    print(f'📊 结果: {successes} 成功, {failures} 失败, {len(targets)-successes-failures} 未尝试')
    return 0 if failures == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
