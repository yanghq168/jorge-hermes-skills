#!/usr/bin/env python3
"""
Probe SMTP credentials for a cron job that just failed with
"Connection unexpectedly closed". Tells you in one shot whether the
credential is dead (Case A: 535 visible) vs silently revoked (Case B:
EHLO ok, AUTH closes socket with no reply) vs actually unreachable
(case C: connect-time failure).

Usage:
    # Read default config used by the cron scripts
    python3 probe_smtp.py

    # Or pass credentials explicitly
    python3 probe_smtp.py --host smtp.qq.com --port 465 --user x@y.com --pass CODE

Exits 0 = auth dead (cron will keep failing until you regenerate),
exits 1 = network/transport problem (cron is fine, fix the network).
"""

import argparse
import os
import smtplib
import socket
import ssl
import sys
from pathlib import Path


def load_yaml_credential():
    """Best-effort read of ~/.hermes/cron/config/config.yaml + ~/.hermes/.env."""
    import re
    creds = {}
    cfg = Path.home() / ".hermes" / "cron" / "config" / "config.yaml"
    if cfg.exists():
        text = cfg.read_text(encoding="utf-8")
        for key in ("smtp_server", "smtp_port", "smtp_user", "smtp_pass", "to_email"):
            m = re.search(rf'^\s*{key}\s*:\s*"?([^"\n]+)"?', text, re.M)
            if m:
                creds[key] = m.group(1).strip()
    env_path = Path.home() / ".hermes" / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            creds.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return creds


def probe(host, port, user, password, use_starttls=False):
    """Run EHLO + AUTH, capture whether the server replied with a status."""
    smtplib.SMTP.debuglevel = 1
    socket.setdefaulttimeout(15)
    s = None
    ehlo_ok = False
    auth_dead_silent = False
    auth_dead_535 = False
    connect_failed = False
    try:
        if use_starttls:
            s = smtplib.SMTP(host, port, timeout=15)
            s.ehlo()
            s.starttls()
            s.ehlo()
        else:
            s = smtplib.SMTP_SSL(host, port, timeout=15)
            s.ehlo()
        ehlo_ok = True
        try:
            s.login(user, password)
            print("\n✅ LOGIN OK — credential is valid")
            return 0
        except smtplib.SMTPAuthenticationError as e:
            auth_dead_535 = True
            print(f"\n❌ AUTH DEAD (535 in transcript): {e.smtp_code} {e.smtp_error.decode(errors='replace') if isinstance(e.smtp_error, bytes) else e.smtp_error}")
            return 0
        except smtplib.SMTPServerDisconnected as e:
            auth_dead_silent = True
            print(f"\n❌ AUTH SILENT-REJECT (Case B): EHLO succeeded but server closed socket during AUTH with no reply — {e}")
            return 0
    except (socket.timeout, ConnectionRefusedError, OSError, ssl.SSLError) as e:
        connect_failed = True
        print(f"\n❌ CONNECT FAILED (case C — network/firewall): {type(e).__name__}: {e}")
        return 1
    finally:
        if s is not None:
            try:
                s.quit()
            except Exception:
                pass


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--host")
    p.add_argument("--port", type=int)
    p.add_argument("--user")
    p.add_argument("--pass", dest="password")
    p.add_argument("--starttls", action="store_true", help="Use port 587 STARTTLS instead of SSL")
    args = p.parse_args()

    creds = load_yaml_credential()
    host = args.host or creds.get("smtp_server", "smtp.qq.com")
    port = args.port or (587 if args.starttls else int(creds.get("smtp_port", "465")))
    user = args.user or creds.get("smtp_user") or creds.get("QQ_EMAIL_USER")
    password = args.password or creds.get("smtp_pass") or creds.get("QQ_EMAIL_AUTH_CODE")

    if not (user and password):
        print("ERROR: missing credentials. Pass --user/--pass or set QQ_EMAIL_AUTH_CODE in ~/.hermes/.env", file=sys.stderr)
        sys.exit(2)

    print(f"Probing {host}:{port} as {user} (use_starttls={args.starttls})")
    print(f"Credential sources tried: config.yaml + ~/.hermes/.env")
    sys.exit(probe(host, port, user, password, use_starttls=args.starttls))


if __name__ == "__main__":
    main()