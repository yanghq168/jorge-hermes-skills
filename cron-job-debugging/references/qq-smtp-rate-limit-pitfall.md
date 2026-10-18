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
  so older days silently accumulate. Observed: 16 consecutive days of backlog
  (2026-10-03 → 2026-10-18) before anyone noticed — backlog count alone is
  your fastest tell for "this is persistent, not transient".

## Don't

- Don't spam retries on the same IP. Each attempt can deepen the rate-limit.
  Wait ≥ 1 hour between retry rounds; max 2 rounds per cron run.
- Don't just say "QQ SMTP 限频" and stop — the user needs backlog size,
  backup paths, and retry history to act on it.
- Don't manually open each backed-up HTML — let the SMTP path deliver once
  the cooldown releases.
- **Don't burn 30+ minutes in one cron run on blind retries.** This is the
  most common failure mode (seen in 2026-10-18 session): see 2-3 failures
  and think "just one more sleep + retry will work". It won't. Cap at:
  round 1 (immediate, 2 attempts SSL+TLS) → 90s wait → round 2 (2 attempts)
  → write report, **stop**. Total budget: 5 minutes. Past that is wasted
  runtime and deepens the rate-limit.

## Fast diagnostic sequence (do this BEFORE retrying)

Running `resend_toutiao_today.py` in a loop hides whether the failure is
transient or systemic. Run these three checks back-to-back first (~10s):

1. **Backlog count** — the strongest single signal:
   ```bash
   ls ~/.hermes/cron/outbox/toutiao/PENDING_*.html | wc -l
   ```
   - `0` → likely transient (single-day rate-limit or transient network)
   - `1` → today's rate-limit, wait 1h then retry
   - `≥ 2` consecutive days → **confirmed persistent rate-limit**, skip
     retries, go straight to "regenerate auth code / fallback relay" path
2. **Backlog date span** — shows how long the IP has been blocked:
   ```bash
   ls ~/.hermes/cron/outbox/toutiao/PENDING_*.html
   ```
3. **Probe creds** with the bundled `scripts/probe_smtp.py`:
   ```bash
   python3 ~/.hermes/skills/cron-job-debugging/scripts/probe_smtp.py
   ```
   Confirms credential vs rate-limit. Two probes 30s apart — if both fail
   identically, the IP is rate-limited (not the auth code).

In the 2026-10-18 session, after step 1 alone the answer was unambiguous
(16 days of PENDING accumulated 10/03→10/18) — retries were the wrong move.

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
✅ HTML 已备份: ~/.hermes/cron/outbox/toutiao/20261018_2030_晚年孤独.html
✅ STANDBY 日志: ~/.hermes/cron/outbox/toutiao/STANDBY_20261018.txt
📊 PENDING 待发积压: 16 个日期（10/03 – 10/18）— 持久限频，重试无效
🔁 本轮重试: 2 轮（SSL465×2 + TLS587×2），间隔 0/90s
💡 建议: 添加每日 22:30 的 PENDING drainer 定时任务；若 24h 后仍未恢复，
   重新生成 QQ 授权码或迁移阿里云邮件推送
```