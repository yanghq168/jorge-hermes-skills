## Case X — Failure #59 (2026-10-19): chronic outage continues, content pipeline healthy, credential diagnosis confirmed

The `toutiao-article-daily.py` cron failed for the **59th consecutive night** since 2026-08-25. Same auth code (`iylylmwnitbbbebi`), same `Connection unexpectedly closed` from `smtp.qq.com:465`. Today's session added three things worth recording:

### Lesson 1 — Direct 535 capture via debug-level probe (Case K companion)

The `scripts/probe_smtp.py` Case K test uses correct vs. wrong password to disambiguate IP-block vs. credential. This session ran `smtplib.SMTP_SSL` with `set_debuglevel(2)` to capture the full transcript, which revealed QQ's actual 535 message verbatim:

```
535 Login fail. Account is abnormal, service is not open, password is incorrect,
   login frequency limited, or system is busy. More information at
   https://help.mail.qq.com/detail/108/1023
```

This is **5 enumerated possibilities** QQ returns with a single code, which makes blind recovery harder. Two heuristics to narrow:

1. **"password is incorrect"** vs **"login frequency limited"**: If the auth code worked within the past 30 days (check `git log -p ~/.hermes/cron/config/config.yaml`), it's *probably not* password — it's rate-limit / service-not-open / abnormal-account. If the auth code is older than 30 days, regenerate first (QQ授权码 typically expires after ~30 days for some configurations).
2. **"system is busy"** vs **"service is not open"**: If probe works on port 25 (often more lenient), the 465/587 ports are throttled, not the credential.

The `probe_smtp.py` script does NOT extract this 535 message text — future patch should `print(e.smtp_error.decode())` when `SMTPAuthenticationError` fires, so the agent can pattern-match against the 5 reasons.

### Lesson 2 — 30-byte minimal email test = a free credential liveness check

A 30-byte email (`MIMEText('hermes cron test <timestamp>', 'plain', 'utf-8')`) sent through the same `SMTP_SSL` flow as the full HTML is essentially free (sub-second), and proves the credential is alive *regardless of message size or content*. If the minimal email also fails 535, the credential is dead — no need to retry the full HTML. This is faster than `probe_smtp.py` because it goes through `sendmail()` rather than stopping at `login()`.

Add to `scripts/probe_smtp.py` as a `--send-canary` flag that sends a 1-byte Subject email after successful login, to prove end-to-end credential liveness.

### Lesson 3 — Cron prompt is authoritative for content direction (not the skill)

The cron prompt sent each night states:
- 选题方向：养老、遗产、赡养、亲戚恩怨（头条中老年男性用户最爱）
- 长文吃流量，故事要完整，观点要犀利

These are **already encoded** in `references/toutiao-article-daily.md` (选题库特征 + 检查清单) and in the `TOPICS_POOL` / `MICRO_TOPICS_POOL` of the script. But agents reading the cron prompt afresh might be tempted to "improve" by adding hot-search-driven topics (unified-style) or expanding to other demographics. **Don't.** The Toutiao pipeline is deliberately **not** part of the hot-search pipeline — it's a fixed-topic rotation optimized for an audience the user has explicitly carved out. The cron prompt re-asserts this every night; treat it as load-bearing, not ignorable.

### Today's run (2026-10-19, failure #59)

- **Generated**: 长文《69岁老人把房子过户给儿子后，儿媳说"这房子是我们的，你凭什么住"》（房产纠纷方向）+ 微头条《我65岁，存款30万，退休金3000……》《我60岁，找了个老伴……》
- **HTML backup**: `~/.hermes/cron/outbox/toutiao/20261019_2030_房产纠纷.html` (27 KB, 331 行, 21 段正文). 标题、钩子、长文结构完整 — 内容生成100%正常
- **STANDBY log**: `~/.hermes/cron/outbox/toutiao/STANDBY_20261019.txt` (~500 B)
- **Resend script**: ran `resend_toutiao_today.py` which tries SSL465 + STARTTLS587 — both returned `SMTPServerDisconnected`
- **Direct probe**: `smtplib.SMTP_SSL` with debuglevel=2 → captured 535 verbatim
- **Minimal email probe**: 30-byte email → also 535, confirming credential is the failure mode
- **PENDING backlog**: still 16+ dates (Sept 10/03 → 2026-10/19), chronic outage unchanged
- **Outbox pruning**: NOT done today (Case W prune already done at N=53; size hasn't crossed the next prune threshold)
- **README extension**: REQUIRED per Case W Lesson 2 — append `## 2026-10-19（持续中 — 第59天）` block

### Updated decision rule (N=59)

| Failure count | Probe? | Article inline? | Outbox pruning? | README extension? | Report shape |
|---|---|---|---|---|---|
| 1-2 | Full probe | Yes | No | Yes | Full Case F + article |
| 3-9 | One confirmation | Title + hook only | No | Yes | Case F + outbox-detection callout |
| 10-19 | Skip | NO — outbox path only | No | Yes | Case H terse |
| 20-29 | Skip | NO | No | Yes | Case H + masking warning |
| 30-49 | Skip | NO | No | Yes | Case L + blast radius |
| 50-52 | Skip | NO | No | Yes | Case L + outbox prune warning |
| ≥53 | Skip | NO | Yes (one-time, 14-day keep) | **Yes — mandatory** | Case H terse + pruning confirmation |
| **59 (today)** | Skip (just probe 1× for transcript) | NO | No (already pruned at 53) | **Yes — mandatory** | Case H terse + 535 verbatim + credential status |

### Open question

The user (system) explicitly stated topic preferences in the cron prompt every night. This is **load-bearing** — the Toutiao script deliberately does NOT participate in the hot-search-driven content pipeline that the unified script uses. Future agents who see a "drop" in topic diversity should NOT add hot-search topics to the toutiao rotation; that's a different product for a different audience. The cron prompt is the authoritative spec; the script's `TOPICS_POOL` is the canonical implementation.