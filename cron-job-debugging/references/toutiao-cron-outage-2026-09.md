## Case S — 32nd consecutive identical SMTP failure: the sleep-retry anti-pattern (2026-10-07)

The `toutiao-article-daily.py` cron failed for the **32nd consecutive night** (since 2026-08-25). Same auth code (`iylylmwnitbbbebi`), same `Connection unexpectedly closed` symptom. By Case H/L/O/P/R logic this should be a 4-line terse report and zero probes. The new lesson this cycle is about a **specific failure mode** the skill has warned against but not formally named: **sleep-retry escalation** — when a fresh agent, instead of doing the Case O README-first check, runs a probe, sees `Connection unexpectedly closed`, and starts progressively backing off with `time.sleep(N)` between more probes.

### What the agent did this cycle (READ FIRST, then NEVER DO)

Chronological terminal-call sequence observed this session:

1. Ran `python3 ~/.hermes/cron/scripts/toutiao-article-daily.py` — got `❌ 发送失败: Connection unexpectedly closed`. PENDING file written by the script's catch block. (Correct behavior — script saved to outbox.)
2. Ran `python3 ~/.hermes/cron/scripts/resend_toutiao_today.py` — got `SMTPServerDisconnected: Connection unexpectedly closed` × 4 (SSL465 x2, STARTTLS587 x2). (Correct fallback script — but at N=32, no resend attempt will succeed.)
3. **Started sleep-retry escalation**: `time.sleep(35)` then probe → fail → `time.sleep(90)` then probe → fail → `time.sleep(180)` then probe → fail → `time.sleep(300)` then probe → fail → `time.sleep(560)` then probe → fail.
4. Turned on `smtplib.SMTP.debuglevel = 2` — got the canonical 535 transcript (Case I pattern: AUTH PLAIN fails → smtplib retries with AUTH LOGIN → socket tears down). This DID surface the `535 Login fail` this time, but only after 6+ failed probe attempts.
5. Launched a background process with `time.sleep(900)` then 3 more probes — sat on `process(action='poll')` for the rest of the cron session, burning the entire token budget on waiting.

**Net result**: ~10 terminal calls + 1 background process + ~20 minutes of session time. Generated content: 1 HTML (correctly saved to outbox by the script's first run). Probe insight gained: **zero** — the `535 Login fail` was already documented in Cases I and J.

### Why sleep-retry is the wrong pattern at N≥30

| Step | What the agent hoped | What actually happened |
|------|---------------------|------------------------|
| `time.sleep(35)` then probe | "Maybe a transient blip will clear" | Server returned `535 Login fail` again. A revoked auth code stays revoked. |
| `time.sleep(90)` then probe | "Maybe 90s is enough for the rate limit to clear" | `535 Login fail`. The QQ rate-limit window is per-IP and per-account, not per-attempt — sleeping between attempts from the same client doesn't reset the limit. |
| `time.sleep(180)` then probe | "Let me double the backoff" | Same result. Doubling the sleep doesn't double the recovery probability for credential-class failures. |
| `time.sleep(300)`, `time.sleep(560)`, then `time.sleep(900)` backgrounded | "Eventually it will clear" | Same result every time. Sleep-retry treats a deterministic credential failure as if it were a transient network issue. |

The mental model error: **confusing "rate-limited" with "transient."** QQ's `535 Login fail` includes "login frequency limited" in its error string (it's right there in the message), which makes the error look like a rate limit. It isn't. The phrase "login frequency limited" in QQ's 535 message is the LAST item in a list of *all possible causes* (`Account is abnormal, service is not open, password is incorrect, login frequency limited, or system is busy`) — not a specific rate-limit signal. It's the generic catch-all that gets returned when ANY of those conditions is met, including a revoked auth code.

**Decisive rule**: if the first probe returns `535 Login fail` from QQ, no amount of sleep-retry will clear it. The credential is dead. Skip all further probes. Go straight to Case H dispatch.

### The README-first check that would have prevented all 10 calls

This session violated Case O's "READ README FIRST" rule. The outbox README at the start of this cron session would have shown:

- 70+ HTML files in `outbox/toutiao/` (chronic outage, no resolution)
- README ending with `## YYYY-MM-DD（持续中 — 第N天）` (not "已恢复")
- Same auth code (`iylylmwnitbbbebi`) flagged as revoked

A single `read_file ~/.hermes/cron/outbox/toutiao/README.md` (1 call) + `ls -1 ~/.hermes/cron/outbox/toutiao/*.html | wc -l` (1 call) would have triggered the Case O dispatch protocol: **skip all probes, deliver 4-line terse report, do nothing else.** The 8 calls the agent burned on probe-and-sleep escalation would have been saved.

### Refinement to the existing "fresh agent anti-pattern" pitfall

Case O already documents the "fresh agent anti-pattern" with the checklist:

> 1. `ls -1 ~/.hermes/cron/outbox/<platform>/*.html 2>/dev/null | wc -l` — if ≥3, chronic outage.
> 2. `read_file ~/.hermes/cron/outbox/<platform>/README.md` — if it ends with "持续中" and no "已恢复", the diagnosis is done; the user just hasn't fixed it.
> 3. `hermes cron list --all` (or read `~/.hermes/cron/jobs.json`) — confirm `last_status` is masked per Case M, then deliver Case H dispatch.

This Case S adds a new specific sub-pattern to that pitfall: **sleep-retry escalation**. If a fresh agent encounters `Connection unexpectedly closed` on `smtp.qq.com:465` for a documented-chronic-outage cron, the FIRST response after Case O's three calls must be a Case H dispatch — NOT a probe, NOT a sleep, NOT a `debuglevel=2` probe, NOT a 900-second background sleep process. The probe-and-sleep sequence produces zero new information at N=32+.

### What to do when sleep-retry has already started

If you (or a previous session) already burned 3+ sleep-retry cycles and the cron session is still running, recover by:
- Killing any pending `time.sleep()` background process (`process(action='kill', session_id=...)`)
- Skipping all remaining probes
- Delivering the Case H terse dispatch NOW
- Appending the `## YYYY-MM-DD（持续中 — 第N+1天）` entry to the outbox README

The total budget for a chronic-outage cron cycle should be: **3 README-check calls + 1 README-append call = 4 calls.** Everything above that is wasted.

### Failure count context table — Case S additions

| Failure count | Action | Sleep-retry allowed? |
|---|---|---|
| 1-2 | Full Case F diagnostic + outbox-save confirmation | Yes, 1 retry with 3s backoff is fine (Case G §6) |
| 3-9 | One confirmation probe + Case F report | Yes, 1 probe + 1 retry |
| 10-19 | Skip probe + Case H terse | **NO** — probes are ceremony |
| ≥20 | Skip probe + Case H terse + masking warning | **NO** |
| ≥25 | Skip probe + terser still + blast-radius | **NO** |
| ≥30 (Case R) | Read `config_loader.py` before `config.yaml` | **NO** |
| **≥32 (Case S, today)** | Skip probe + skip sleep-retry + skip debuglevel + Case H ONLY | **NEVER** — the credential is binary dead, sleep won't change it |

### Today's run (2026-10-07, failure #32)

- **Generated**: 长文《65岁老人随了20年份子钱，最后一场酒席没请他：人情薄如纸》（随礼人情方向）+ 微头条《大伯供我上大学，花了15万。我工作第一件事，是把他屏蔽》+ 《婆婆来家里住了一个月，我瘦了8斤。不是累的，是气的》
- **HTML backup**: `~/.hermes/cron/outbox/toutiao/20261007_2030_随礼人情.html` (~28 KB). PENDING file `PENDING_20261007.html` symlinked by the script's catch block.
- **SMTP probes**: ran unnecessarily (Case O detection rule should have skipped). 6 probes total + 1 backgrounded 9-min-sleep probe. All returned `Connection unexpectedly closed` after `535 Login fail`.
- **Recovery**: None attempted (auth code still revoked).
- **What should have been done**: 3 README-check calls + Case H dispatch + README append. ~75% of session time saved.
- **Lesson captured**: sleep-retry escalation is a distinct anti-pattern from "fresh agent ignores the skill" (Case O anti-pattern). Both result in wasted tokens; the new one specifically compounds by making the cron session busy-wait on `process.poll` for the entire remaining budget.

### Cross-script exposure (unchanged from prior cases)

The same `iylylmwnitbbbebi` auth code is shared by every daily-content cron in `~/.hermes/cron/scripts/`: `wechat-article-daily.py`, `unified-content-daily.py`, `xhs-travel-daily.py`, `xiaohongshu-travel-daily.py`, `xhs-escape-weekend.py`, `bithappy_email_pro.py`. The Case C `_email_helpers.py` extraction remains overdue. When the user finally fixes the auth code, every one of those scripts will recover simultaneously.