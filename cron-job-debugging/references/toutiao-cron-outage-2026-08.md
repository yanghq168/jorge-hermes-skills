# `toutiao-article-daily.py` recurring outage: 2026-08-25 → 2026-09-13 (20 nights, ongoing)

A real recurring failure on this Hermes deployment, captured for future sessions to recognize instantly.

## What's broken

The nightly `toutiao-article-daily.py` cron (scheduled via Hermes `jobs.json` at 20:30) cannot deliver its HTML email to `569545015@qq.com` because the QQ Mail SMTP authorization code in `~/.hermes/cron/config/config.yaml` was revoked by QQ's anti-spam system sometime before 2026-08-25.

## Symptom (every night, identical)

```
🏠 权权的HERMES · 头条号文章生成器 v1.1.0
...
❌ 发送失败：Connection unexpectedly closed (重试2次仍失败，HTML已备份: .../outbox/toutiao/20260913_2030_遗产分配.html)
```

The script's own stderr surfaces only the generic `SMTPServerDisconnected("Connection unexpectedly closed")`. The actual root cause (535 Login fail) is invisible until you re-run with `smtplib.SMTP.debuglevel = 2` or with the manual AUTH LOGIN recipe below.

## Diagnostic confirmation (SMTP transcript excerpt — manual AUTH recipe, 2026-09-07)

The most reliable way to surface the 535 is to drive the SMTP session yourself so each protocol reply is its own line. `debuglevel=1` works but smtplib retries AUTH after the first 535 and the second AUTH closes abruptly — the 535 can scroll past fast.

```python
import smtplib, base64
server = smtplib.SMTP_SSL('smtp.qq.com', 465, timeout=15)
server.ehlo()
server.send(b"AUTH LOGIN\r\n")
code, msg = server.getreply()       # 334 VXNlcm5hbWU6  (base64 "Username:")
server.send(base64.b64encode(b'569545015@qq.com') + b'\r\n')
code, msg = server.getreply()       # 334 UGFzc3dvcmQ6  (base64 "Password:")
server.send(base64.b64encode(b'iylylmwnitbbbebi') + b'\r\n')
code, msg = server.getreply()       # 535 Login fail. Account is abnormal, ...
```

Actual output (2026-09-07, deployment unchanged since 2026-08-25):

```
EHLO: 250: b'newxmesmtplogicsvrszb51-0.qq.com\nPIPELINING\n... AUTH LOGIN PLAIN XOAUTH XOAUTH2\n...'
AUTH LOGIN -> 334: b'VXNlcm5hbWU6'
username -> 334: b'UGFzc3dvcmQ6'
password -> 535: b'Login fail. Account is abnormal, service is not open, password is incorrect, login frequency limited, or system is busy. More information at https://help.mail.qq.com/detail/108/1023'
```

This matches **Case A** in the SKILL.md SMTP deep-dive (535-in-transcript, polite SMTP reply). The Case B silent-reject signature (no `reply:` line between AUTH and SMTPServerDisconnected) has been observed once on this deployment (2026-08-24) but is the exception, not the norm.

**Confirmed again on 2026-09-09 (failure #16)**: identical transcript, deterministic output. Manual recipe remains the only reliable surface.

**Confirmed again on 2026-09-13 (failure #20) on BOTH transports**: same explicit 535 reply on port 587 STARTTLS as on port 465 SSL — see Case L below.

## Outbox accumulation

`~/.hermes/cron/outbox/toutiao/` grows by 1-2 files per failed night (~27 KB each). As of 2026-09-13 it contains **36 HTML files** from this outage, plus earlier successful backups (~810 KB cumulative). This is **correct behavior** — the script's failure-path writeback is the only thing keeping the daily content from being lost. The `outbox/toutiao/README.md` is the durable outage log that survives across cron-job-script edits; see the README for the live status timestamp.

## Same-outage detection (added 2026-09-09, failure #16)

Two refinements that let a fresh cron-session agent skip the diagnostic loop when this outage recurs again:

1. **Outbox-count check at session start.** Before running any SMTP probe:
   ```bash
   ls -1 ~/.hermes/cron/outbox/toutiao/*.html 2>/dev/null | wc -l
   ```
   Count ≥3 + no "Outage resolved" in `outbox/toutiao/README.md` = known chronic failure. Jump straight to Case H dispatch pattern. Verified 2026-09-09: outbox had 29 files, README ended with "持续中 — 第14天" → obvious same-outage, no probe needed.

2. **Time-to-failure fingerprint.** Revoked QQ SMTP auth code returns `535` in **~0.6-0.8 seconds** of wall-clock time (measured 2026-09-09: 0.62s from `SMTP_SSL()` open to `SMTPServerDisconnected` raising). Real network problems take 10-15s before socket timeout fires. Useful as a "is this the same outage?" fingerprint without re-running the full transcript.

| Wall-clock to failure | Likely cause | Action |
|---|---|---|
| < 1 second | Credential rejected by server | Case A — 535 in transcript. Fix the auth code. |
| 10-15 seconds | Socket timeout / firewall | Case C — real network problem. Try port 587, check firewall. |
| 1-10 seconds | Borderline | Run manual AUTH LOGIN recipe to see whether the server sent a reply. |

## Outage history (cumulative failure count, days)

| Date | Failure # | Notes |
|---|---|---|
| 2026-08-25 | 1 | Initial detection. Outbox pattern shipped to script. |
| 2026-08-26 → 2026-08-31 | 2-7 | Same code, same symptom; "do not re-diagnose" rule established (Cases C/D/E). |
| 2026-09-02 | 8 | Case G — importlib bypass for content inspection without burning SMTP. |
| 2026-09-03 | 10 | Case H — terse runbook dispatch mode (no more probes, just point at outbox + fix). |
| 2026-09-04 → 2026-09-07 | 11-14 | Status quo. Manual AUTH LOGIN recipe added (Case I). |
| 2026-09-08 | 15 | Confirmed outage has spread across all content-platform scripts (cross-script triage grep below). No new diagnostic; pure Case H dispatch. |
| 2026-09-09 | 16 | Case J — outbox-count + 0.62s time-to-failure fingerprint for same-outage detection at session start. Refined pitfall: `debuglevel=2` ALSO buries the 535, not just `debuglevel=1`. |
| 2026-09-10 | 17 | Pure Case H dispatch — outbox grew, transcript unchanged. No new lesson. |
| 2026-09-11 | 18 | Pure Case H dispatch — same symptom, same auth code. No new lesson. |
| 2026-09-12 | 19 | Pure Case H dispatch — outbox 36 files. No new lesson. |
| 2026-09-13 | 20 | Case L — manual probe on BOTH transports (465 SSL and 587 STARTTLS) confirmed both surface the **same explicit 535 line** (not just disconnects). At N=20 the manual probe is purely ceremonial confirmation; the report can be the terse Case H template plus the day's generated title, nothing more. |

**Decision rule at N≥10:** skip the diagnostic loop entirely. The credential state has not changed in over a week. The outbox has today's content. Report = outbox path + the one-line fix. Don't re-run `probe_smtp.py`, don't paste transcripts, don't suggest port 587.

**Decision rule at session start, before any SMTP work:** run the outbox-count check (`ls -1 ~/.hermes/cron/outbox/<platform>/*.html | wc -l`) — if ≥3, you're looking at a known chronic outage, jump straight to the Case H dispatch pattern. Saves the user from another 30s of probe output for a problem that's already been diagnosed N times.

**Decision rule at N≥20:** the manual probe is now ceremonial. ONE line from the manual AUTH LOGIN recipe (the `password -> 535:` line) is enough to confirm the outage is unchanged. Don't paste the full transcript, don't run port 587 in parallel, don't list alternative transports — the user has seen all of that 19 times. The report should be: today's generated title + outbox path + the one-line fix command + failure count. That is the entire value-add at N=20.

## Cross-script triage grep (added 2026-09-08, failure #15)

At failure #15 the most useful diagnostic was NOT re-running SMTP probes — it was confirming *which* scripts share this credential. One-liner that sizes the entire outage in seconds:

```bash
grep -l "smtp_pass\|get_mail_config" ~/.hermes/cron/scripts/*.py | xargs -I {} \
  sh -c 'echo "=== {} ==="; tail -n 200 "$1" 2>/dev/null | grep -cE "(发送成功|邮件已发送|sent successfully|Login successful)" | xargs echo "  success:"; tail -n 200 "$1" 2>/dev/null | grep -cE "(发送失败|登录失败|Login fail|SMTPServerDisconnected|Connection unexpectedly)" | xargs echo "  fail:"' _ {}
```

Output on this deployment (2026-09-08):

```
=== /home/ubuntu/.hermes/cron/scripts/toutiao-article-daily.py ===
  success: 0   fail: 11
=== /home/ubuntu/.hermes/cron/scripts/wechat-article-daily.py ===
  success: 0   fail: 18
=== /home/ubuntu/.hermes/cron/scripts/xiaohongshu-travel-daily.py ===
  success: 0   fail: 19
```

**Lesson:** when one credential is revoked, every script that uses `config_loader.get_mail_config()` fails together. The user only sees the symptom for the most-talked-about cron (toutiao), but the failure count tells you the actual blast radius. Three crons are silently dropping content right now. This confirms the `_email_helpers.py` extraction is overdue — when the auth code is finally fixed, all three recover simultaneously with one config edit.

For daily content-platform cron logs that are NOT on this grep list (`daily_report.py`, `weekly_report.py`, `monthly_report.py`), the credential source is different — they read `email.password` from a different key and are correctly bypassing the broken SMTP. Don't conflate them.

## Hybrid report shape (added 2026-09-08, failure #15)

The SKILL.md Case H prescribes a 4-line terse dispatch for N≥10. That is the right template when the user is *waiting* on the report. But cron runs that deliver via the agent channel (this one is `deliver: origin` to the user's main chat) benefit from a slightly longer hybrid:

- **Headline** (4 lines, Case H style): success/fail status, outbox path, the one-line fix
- **One diagnostic data point**: the cross-script failure counts, to make blast radius concrete
- **Generated content summary**: title, direction, hook (so the user knows what they'd be reading today if email worked)
- **NO** full SMTP transcript, **NO** "try port 587" suggestion, **NO** re-explanation of what 535 means

The trigger for going *back* to the 4-line Case H shape (rather than this hybrid) is: cron is in `deliver: email` mode (so the report IS the email and a long report burns the user's inbox), OR failure count is ≥30 (user has been ignoring it for a month, terser is strictly better).

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
   python3 ~/.hermes/cron/scripts/probe_smtp.py
   # Expected: "✅ LOGIN OK — credential is valid"
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

## Scripts involved (all share the same `iylylmwnitbbbebi` credential — all fail together, only one update to recover them all)

- `~/.hermes/cron/scripts/toutiao-article-daily.py` — has working outbox-fallback pattern (Case C reference implementation)
- `~/.hermes/cron/scripts/config_loader.py` — `get_mail_config()` reads from `config.yaml`; YAML is the canonical source, not env vars
- `~/.hermes/cron/config/config.yaml` — line that needs editing: `smtp_pass`

**Other scripts that would fail identically today** (no outbox fix yet — content is lost when SMTP fails):

- `~/.hermes/cron/scripts/wechat-article-daily.py`
- `~/.hermes/cron/scripts/unified-content-daily.py`
- `~/.hermes/cron/scripts/xhs-travel-daily.py`
- `~/.hermes/cron/scripts/xiaohongshu-travel-daily.py`
- `~/.hermes/cron/scripts/xhs-escape-weekend.py`
- `~/.hermes/cron/scripts/bithappy_email_pro.py`

The shared `_email_helpers.py` extraction (proposed in Case C, repeated in E + F + G + H + I + J) remains the overdue refactor — until it lands, each script silently drops its content instead of saving to outbox when SMTP breaks. Per Case E, a third-party transactional mail relay (Resend / SMTP2GO / SendGrid) with a static API key is the migration that would permanently end this weekly revocation cycle.

## Today's run (2026-09-09, failure #16)

- **Generated**: 长文《63岁大伯给侄子出了20万学费，侄子毕业后第一件事是'断了联系'》（亲戚恩怨方向）+ 微头条《大伯供我上大学...屏蔽》+ 《我65岁，存款30万...不够养老》
- **HTML backup**: `~/.hermes/cron/outbox/toutiao/20260909_2030_亲戚恩怨.html` (27 KB)
- **SMTP attempt**: 535 at 0.62s wall-clock, identical transcript to failure #14
- **Failure report delivered to user chat (hybrid Case H shape)**.
- **No new diagnostic content** — this run was a pure Case H dispatch per the Case J session-start detection rule.

## Case L — 20th consecutive identical SMTP failure: both transports now confirmed to surface explicit 535 (2026-09-13)

The `toutiao-article-daily.py` cron failed for the **20th consecutive night** (since 2026-08-25). Same auth code (`iylylmwnitbbbebi`), same `Connection unexpectedly closed` symptom, same 535 root cause. The outage is now three full weeks old with no user action taken.

### Both transports surface the same explicit 535 — not a "transport issue"

Case J already noted "Port 465 and 587 both fail identically in <1s." The 2026-09-13 cycle went one step further and ran the manual AUTH LOGIN recipe on **port 587 STARTTLS** (in addition to the canonical 465 SSL recipe). Both produce the **same explicit `password -> 535: b'Login fail. Account is abnormal...'` line** — not a silent disconnect, not a different code, the exact same QQ rejection. This eliminates the last "maybe it's the transport" theory and confirms the credential is binary dead regardless of which port the script uses.

This is a refinement, not a contradiction of Case J. The practical implication: **do not recommend port 587 to the user as an alternative anymore.** Every cron script on this deployment that uses `config_loader.get_mail_config()` is hitting port 465 by default; switching to 587 would produce the identical failure with one extra `STARTTLS` round-trip. Don't burn the user's time on transport suggestions.

### Probe-at-N≥20 is purely ceremonial

By failure N=20, the manual probe's role is reduced to **one line of confirmation**, not a diagnostic exercise. Today's session produced:

```
password -> 535: b'Login fail. Account is abnormal, service is not open, password is incorrect, login frequency limited, or system is busy. ...'
```

That single line, plus the outbox-count check (`36` files in `~/.hermes/cron/outbox/toutiao/`), plus the README's "持续中" timestamp is the entire information needed to dispatch. No port sweep, no transcript dump, no DNS check, no `debuglevel=1` AND `debuglevel=2` comparison. Those were useful at N=10, informational at N=15, and pure token-burn at N=20.

### Today's report shape (failure #20, in this conversation)

The user delivered a 3-section report:

1. **Generate status** (✅) — title, direction, category, micro-articles, outbox path
2. **Delivery status** (❌) — single-line 535 mention + outbox backup confirmation
3. **User fix** — verbatim QQ-web-UI steps, copy-paste-ready

This is the canonical N=20 template. Skipped (correctly): SMTP transcript, port-587 alt-transport suggestion, `probe_smtp.py` re-run, full diagnostic loop enumeration, cross-script blast-radius tally (the Case J triage grep already covers that for any fresh agent).

### Today's run (2026-09-13, failure #20)

- **Generated**: 长文《72岁老人存了40万，遗嘱写好两年，去世后三个子女差点打起来》（遗产分配方向）+ 微头条《大伯供我上大学...屏蔽》+ 《我65岁，存款30万...不够养老》
- **HTML backup**: `~/.hermes/cron/outbox/toutiao/20260913_2030_遗产分配.html` (27 KB)
- **SMTP probe (ceremonial)**: manual AUTH LOGIN on both 465 and 587 → both surface the identical explicit 535 reply in ~0.6s. Credential state unchanged since 2026-08-25.
- **Outbox size**: 36 HTML files, ~810 KB cumulative
- **Failure report delivered**: 3-section Case L template (generate / deliver / fix). No new diagnostic content beyond Case J + Case L refinement.

### When the user finally fixes it — the consolidated post-outage checklist

When `iylylmwnitbbbebi` is finally replaced with a fresh authorization code (likely via QQ web UI per the verbatim steps in the "The fix" section above), the recovery is a single config edit that unblocks **all** the scripts listed in the "Other scripts that would fail identically today" section — six content-platform scripts total, not just `toutiao-article-daily.py`. The `_email_helpers.py` extraction remains the overdue refactor that would prevent future chronic outages by making credential rotation a single-file change.

Until that lands, the operating assumption for any cron session touching `smtp.qq.com:465` or `smtp.qq.com:587` with `569545015@qq.com` is: **the credential is dead, the outbox has today's content, the user has been told N times, the report should not re-explain.** Anything more is noise.