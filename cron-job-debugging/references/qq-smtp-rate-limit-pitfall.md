# QQ SMTP rate-limit — Connection unexpectedly closed

Server-side rate-limit on `smtp.qq.com` hitting BOTH SSL465 and STARTTLS587 paths
with `SMTPServerDisconnected: Connection unexpectedly closed`. Not a credential
issue, not a script bug — the egress IP has been flagged by QQ's antispam
system and the cooldown can run into hours.

## Symptoms

- 4+ consecutive `SMTPServerDisconnected` errors across SSL465 and TLS587
- Retries at +5min / +15min / +30min all fail identically
- The script's local fallback path (`STANDBY_YYYYMMDD.txt` +
  `PENDING_YYYYMMDD.html` symlink under `~/.hermes/cron/outbox/toutiao/`)
  IS being written correctly — content is safe on disk
- `resend_toutiao_today.py` only handles the **most recent** date's PENDING,
  so older days silently accumulate. Observed: 8 consecutive days of backlog
  (2026-10-10 → 2026-10-17) before anyone noticed.

## Don't

- Don't spam retries on the same IP. Each attempt can deepen the rate-limit.
  Wait ≥ 1 hour between retry rounds; max 2 rounds per cron run.
- Don't just say "QQ SMTP 限频" and stop — the user needs backlog size,
  backup paths, and retry history to act on it.
- Don't manually open each backed-up HTML — let the SMTP path deliver once
  the cooldown releases.

## Recovery actions (in order)

1. **Wait for cooldown** — at least 1 hour, often longer. Check with a
   single probe send before committing to the full retry.
2. **Drain PENDING backlog** after cooldown releases:
   ```bash
   ls -la ~/.hermes/cron/outbox/toutiao/PENDING_*.html
   ```
   For each date, repoint the symlink and run:
   ```bash
   python ~/.hermes/cron/scripts/resend_toutiao_today.py
   ```
   Or patch `resend_toutiao_today.py` to iterate all `PENDING_*.html`
   symlinks instead of just today's.
3. **If persistent (>24h):** QQ account needs regenerated "special password"
   (授权码), or fall back to alternative SMTP relay:
   - Aliyun DirectMail (阿里云邮件推送)
   - Resend (resend.com)
   - AWS SES
4. **Prevention — add a drainer cron.** Schedule at ~22:30 daily:
   ```bash
   # crontab entry
   30 22 * * * cd ~/.hermes/cron/scripts && python drain_pending_outbox.py
   ```
   The drainer walks `~/.hermes/cron/outbox/<platform>/PENDING_*.html`
   symlinks and calls the per-platform resend script. Drains yesterday's
   failure once the rate-limit cools — no human in the loop.

## Failure report checklist

When this happens, the cron-output report should include:

- [ ] Title + direction of the article generated (content path worked)
- [ ] Full path to the HTML backup + STANDBY log (local-fallback path worked)
- [ ] Count of dates currently in PENDING backlog — `ls ~/.hermes/cron/outbox/toutiao/PENDING_*.html | wc -l`
- [ ] Retry rounds attempted + intervals between them
- [ ] Suggested next-step cron time (e.g. "drainer should run at 22:30")

## Sample cron report excerpt

```
❌ 邮件投递失败（QQ SMTP 限频）
✅ HTML 已备份: ~/.hermes/cron/outbox/toutiao/20261017_2030_亲戚恩怨.html
✅ STANDBY 日志: ~/.hermes/cron/outbox/toutiao/STANDBY_20261017.txt
📊 PENDING 待发积压: 8 个日期（10/10 – 10/17）
🔁 本轮重试: 4 轮（SSL465×2 + TLS587×2），间隔 0/5/15/30 分钟
💡 建议: 添加每日 22:30 的 PENDING drainer 定时任务
```