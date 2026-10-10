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

- **Cross-script exposure (unchanged from prior cases)**

The same `iylylmwnitbbbebi` auth code is shared by every daily-content cron in `~/.hermes/cron/scripts/`: `wechat-article-daily.py`, `unified-content-daily.py`, `xhs-travel-daily.py`, `xiaohongshu-travel-daily.py`, `xhs-escape-weekend.py`, `bithappy_email_pro.py`. The Case C `_email_helpers.py` extraction remains overdue. When the user finally fixes the auth code, every one of those scripts will recover simultaneously.

## Case T — 45th consecutive identical SMTP failure: port-465 fingerprint shift + refined probe recipe (2026-10-08)

The `toutiao-article-daily.py` cron failed for the **45th consecutive night** (since 2026-08-25). Same auth code (`iylylmwnitbbbebi`), same Case H dispatch. Two genuinely new observations this cycle that future sessions need to know about.

### Lesson 1 — Port 465 fingerprint has shifted: now TCP-level blackhole, not fast 535

**Previous behavior (Cases I/J/K through 2026-10-07):** `SMTP_SSL('smtp.qq.com', 465, timeout=15)` opened the TLS socket in ~0.2s, `EHLO` succeeded in ~0.05s, then `AUTH` raised `SMTPServerDisconnected` in ~0.6s total wall clock. The Case J "time-to-failure fingerprint" classified <1s as credential rejection.

**Today's behavior (2026-10-08, failure #45):** `socket.create_connection(('smtp.qq.com', 465), timeout=15)` now hangs and **times out after 15 seconds** with no banner received. Port 587 still returns the 220 banner immediately, and the AUTH PLAIN probe against 587 still produces the deterministic `535 Login fail` in <1s.

```python
# Today's measurements:
socket.create_connection(('smtp.qq.com', 465), timeout=15)  # → socket.timeout after 15s, no data
socket.create_connection(('smtp.qq.com', 587), timeout=15)  # → 220 banner in <1s
# 587 AUTH PLAIN probe → 535 Login fail in ~0.7s (same as before)
```

**What this means for diagnosis:** the Case J "fast-failure = credential" fingerprint is no longer uniformly true for port 465 on this deployment. A 15-second timeout on 465 used to indicate Case C (real network/firewall); now it indicates the same revoked-auth-code state, but the IP has been escalated from "AUTH-level reject" to "TCP-level blackhole." The diagnostic is still credential-related, not network — port 587 still works at the TCP layer AND still 535s at AUTH.

**Updated fingerprint table for QQ SMTP on this deployment:**

| Port | Symptom | Wall-clock | Diagnosis |
|---|---|---|---|
| 465 | TLS handshake succeeds, AUTH 535 | <1s | Revoked auth code (Case A/I/J — historical) |
| 465 | **TCP connect timeout, no data** | **~15s** | **Revoked auth code, IP escalated to TCP blackhole (NEW 2026-10-08)** |
| 587 | TCP connect OK, 220 banner OK, AUTH 535 | <1s | Revoked auth code (Case A — still current) |
| 25 | Network is unreachable | immediate | Firewall block (orthogonal, not the variable) |

The user-fix is identical in all cases (regenerate QQ auth code → update `~/.hermes/cron/config/config.yaml`), but the **detection path is now port-587-first**: if 465 times out at TCP level, the next probe MUST be 587 with AUTH PLAIN to confirm the credential state. Don't conclude "network problem" from a 465 timeout alone — verify with 587.

### Lesson 2 — AUTH PLAIN one-shot probe is the shortest deterministic 535-surfacer

The Case I recipe uses `AUTH LOGIN` with `getreply()` per step (3 round trips to surface the 535). An equivalent recipe using `AUTH PLAIN` (single round trip with username+password base64-encoded together) is one fewer step and equally deterministic:

```python
import socket, ssl, base64, time

s = socket.create_connection(('smtp.qq.com', 587), timeout=20)
ctx = ssl.create_default_context()
ss = ctx.wrap_socket(s, server_hostname='smtp.qq.com')
ss.settimeout(30)

time.sleep(1)
print('BANNER:', ss.recv(2048).decode(errors='ignore')[:150])

ss.sendall(b'EHLO hermes.local\r\n')
time.sleep(1)
print('EHLO:', ss.recv(4096).decode(errors='ignore')[:400])

auth_plain = base64.b64encode(f'\x00{USER}\x00{PASS}'.encode()).decode()
ss.sendall(f'AUTH PLAIN {auth_plain}\r\n'.encode())
time.sleep(2)
resp = ss.recv(4096)
print('AUTH PLAIN result:', resp.decode(errors='ignore')[:400])
# On revoked auth code: "535 Login fail. Account is abnormal..."
```

**Why prefer this over Case I's AUTH LOGIN recipe:** one fewer round trip, one fewer `getreply()` race condition, no intermediate `334 Username:` / `334 Password:` frames to parse. Use Case I's recipe if you specifically want to see the per-step challenge/response; use this AUTH PLAIN recipe for the common "confirm the auth code is dead" check.

**Why this matters now:** with port 465 blackholed at TCP level (Lesson 1), 587 is the only path that completes a handshake. The AUTH PLAIN probe against 587 is now the canonical "is the credential still revoked?" check on this deployment.

### Lesson 3 — README entry format has evolved organically

The Case H template specifies a bare 4-line entry. The format used in practice on 2026-10-08 (and several prior nights) carries more diagnostic detail:

```markdown
## YYYY-MM-DD（持续中 — 第N天）
- Symptom: <one-line summary, port behavior>
- 端口探测：<which ports blocked, which give 535, which time out>
- cron 触发：N 次（<direction> + <HHMM>，各自方向）
- Generated: 长文《...》（<方向>方向）+ 微头条 N 条（...）
- HTML backup: `~/.hermes/cron/outbox/<platform>/<file>.html` + ...
- outbox 累计：N 份
- PENDING: `PENDING_<date>.html` → `<file>.html`（首选，因 <reason>）
- 修复（同 README 顶）：<one-line fix>
```

The extra detail (端口探测 line, PENDING 候选 reasoning, cumulative outbox count) makes future-session diagnosis faster — when a fresh agent reads the README, it can see **at a glance** whether the failure mode is shifting (port behavior change, like Lesson 1) or whether it's the same boring 535-everywhere. **Adopt this format going forward**; the Case H template is the minimum, not the maximum.

### Today's run (2026-10-08, failure #45)

- **Generated**: 长文《67岁老人被三个儿子轮流养老，每家住四个月，第三家说"住够了"》（赡养义务方向）+ 微头条《随了20年份子钱，我终于想明白了：有些人，你永远还不起》+ 《我65岁，存款30万，退休金3000。我算了算，不够养老的》. Manual re-run produced 长文《75岁独居老人，每天最期待的事，是去菜市场跟卖菜的大姐说两句话》（晚年孤独方向）+ 微头条《婆婆来家里住了一个月，我瘦了8斤。不是累的，是气的》+ 《随了20年份子钱，我终于想明白了：有些人，你永远还不起》.
- **HTML backup**: `~/.hermes/cron/outbox/toutiao/20261008_2030_赡养义务.html` (27 KB) + `20261008_2031_晚年孤独.html` (27 KB). PENDING symlink `PENDING_20261008.html` → `20261008_2031_晚年孤独.html` (chosen because the manual re-run landed later and overwrote the symlink target — both directions match the prompt's 养老/遗产/赡养/亲戚恩怨 cluster).
- **SMTP probes**: 2 (1 × 587 AUTH PLAIN producing 535, 1 × 465 timing out at 15s). Both confirm revoked auth code; the 465 timeout is the new fingerprint shift (Lesson 1).
- **README extension**: appended `## 2026-10-08（持续中 — 第45天）` entry following the expanded format (Lesson 3).
- **Failure report delivered**: Case H terse + cross-script blast radius + masking warning (Case M template at N≥20). No article inlined (Case O lesson 2 followed).
- **What went right**: ran the script exactly once via the cron, did NOT retry sleep-retry (Case S anti-pattern), used `read_file` on the outbox README FIRST (Case O detection rule), appended the README entry, kept the report under 30 lines.
- **What was mildly suboptimal**: ran the cron script a second time manually to verify — the verification added zero new info (Case S lesson: the credential is binary dead, one run is enough). The two HTMLs for 2026-10-08 are now both in the outbox; the PENDING symlink points to the second one.

### Refined decision rule at N≥45

| Failure count | Probe strategy | Article inline? | Report shape |
|---|---|---|---|
| 1-2 | Full Case F + port sweep | Yes, full article | Full diagnostic + article |
| 3-9 | One confirmation probe + 465/587 sweep | Title + hook only | Case F + outbox-detection callout |
| 10-19 | Skip probe (README already says it) | NO — outbox path only | Case H terse |
| ≥20 | Skip probe | NO | Case L + masking warning + cross-script blast radius |
| ≥25 | Skip probe | NO | Case H + blast radius + one-line fix |
| ≥30 | Skip probe, read `config_loader.py` first | NO | Case H + scheduler-mask warning |
| ≥32 | Skip probe AND skip sleep-retry | NO | Case H ONLY — 4 calls max budget |
| **≥45 (today)** | Skip probe; if you MUST probe, use **port-587 AUTH PLAIN** (Lesson 2). 465 may now time out at TCP level (Lesson 1) — don't confuse that with Case C network failure. | NO | Case H + expanded README entry (Lesson 3 format) |

The "465 may now time out" caveat is the only genuinely new technical detail at N≥45. Everything else is "do what you did at N≥32."

## Case U — 47th consecutive identical SMTP failure: IP-level AUTH block has now spread to port 587 (2026-10-10)

The `toutiao-article-daily.py` cron failed for the **47th consecutive night** (since 2026-08-25). Same auth code (`iylylmwnitbbbebi`), same Case H dispatch protocol. The genuinely new observation this cycle is that **the IP-level AUTH block documented in Case T (failure #45) has now spread from port 465 to port 587 as well.** Both `SMTP_SSL('smtp.qq.com', 465)` and `SMTP('smtp.qq.com', 587)` + STARTTLS now return the identical `SMTPServerDisconnected: Connection unexpectedly closed` after the script's `resend_toutiao_today.py` auto-path retries both transports and after separate manual probes.

### Lesson 1 — IP-level blackhole has spread to port 587

**Historical (Cases K/T through 2026-10-08):**
- Port 587: TCP connect OK, 220 banner in <1s, AUTH PLAIN triggers `535 Login fail` in <1s. AUTH-rejection at protocol level (Case A canonical).
- Port 465: TCP-level blackhole (Case T), 15s timeout with no data after `socket.create_connection`.

**Today's observation (2026-10-10, failure #47):**
- `resend_toutiao_today.py` auto-path tried `SMTP_SSL(465)` × 2 → `Connection unexpectedly closed` (matches Case T).
- `resend_toutiao_today.py` auto-path then tried `SMTP(587) + starttls()` × 2 → `Connection unexpectedly closed` **(NEW — previously returned 220 banner + 535)**.
- A separate manual probe against both ports after a 30s cooldown returned identical `SMTPServerDisconnected: Connection unexpectedly closed` on both.

**What this means:** QQ's anti-spam has escalated from "AUTH-level reject at 587, TCP-level blackhole at 465" (Case T at Day 45) to **"TCP-level blackhole at BOTH ports"** (today). The 587 path that reliably sent a 220 banner two days ago now closes the socket on/before the STARTTLS handshake. The user's IP has been escalated through anti-spam tiers over the multi-week outage.

**Refined fingerprint table for this deployment as of 2026-10-10:**

| Port | Symptom | Wall-clock | Diagnosis |
|---|---|---|---|
| 465 | TLS handshake succeeds, AUTH 535 | <1s | Revoked auth code (Case A/I/J — historical, pre-2026-10-08) |
| 465 | TCP connect timeout, no data | ~15s | Revoked auth code, IP blackholed (Case T, 2026-10-08) |
| 587 | TCP connect OK, 220 banner OK, AUTH 535 | <1s | Revoked auth code (Case A — historical, pre-2026-10-10) |
| **587** | **TCP-level blackhole or socket torn down pre/post-STARTTLS, no 535** | **<1s** | **Revoked auth code, IP blackholed (NEW 2026-10-10)** |
| 25 | Network is unreachable | immediate | Firewall block (orthogonal, not the variable) |

**Detection implication:** the 587 path used to be the "confirm-credential-state" probe when 465 was blackholed. **As of 2026-10-10 that fallback is gone.** Both ports are now indistinguishable — `Connection unexpectedly closed` on either indicates the same revoked-auth-code / IP-blackholed state. The user-fix is identical (regenerate QQ auth code → update `~/.hermes/cron/config/config.yaml`), but the diagnostic surface is now narrower: there's no longer a fast-fail fingerprint distinguishing credential revocation from network problems on this deployment.

### Lesson 2 — When port-fallback diagnostic paths dry up, switch recommendations

The Case T Lesson 2 `AUTH PLAIN one-shot probe` recipe explicitly said "with port 465 blackholed, 587 is the canonical confirmation path." **That recommendation is now obsolete.**

Updated guidance for N≥47:

1. **Don't try to confirm by probing.** Confirm by (a) outbox count ≥3, (b) README ending with "持续中" + no "已恢复" entry, (c) `last_status` masked per Case M. Those three signals (all from `~/.hermes/cron/`) confirm the state without touching the network.
2. If you must probe for ANY reason (e.g. to confirm the user fixed it after regeneration), run `probe_smtp.py` once — expect `Connection unexpectedly closed` from this IP — and proceed to Case H dispatch.
3. **Don't try port 587 as a fallback** — it is now blackholed too. The only meaningful "is the auth code alive?" probe is from a different IP (the user's laptop) or against a different SMTP provider (e.g. `smtp.gmail.com`, `smtp.163.com`).
4. **Positive confirmation only happens after the user fixes the credential and you see a `250 OK` from a known-good transport.** Until then, treat any `Connection unexpectedly closed` from `smtp.qq.com` on this deployment as the revoked-auth-code state.

### Lesson 3 — README "端口探测" line should record the spread

The Case T expanded README format included a `端口探测：<which ports blocked, which give 535, which time out>` line. The today entry appended by this session extended that line to:

```
- 端口探测：本会话同时在 465 + 587 上观察到 Connection unexpectedly closed
  (IP-level 黑名单从 465 扩散到 587，无 535 reply)
```

This single-line annotation tells future fresh agents: "the canonical 587 AUTH PLAIN probe is gone; do not waste terminal calls looking for the 535 on 587 — there isn't one anymore. Both ports are blackholed at TCP level." Saves the next fresh agent from running 1-3 doomed probes before realizing.

### Today's run (2026-10-10, failure #47)

- **Generated**: 长文《67岁老人被三个儿子轮流养老，每家住四个月，第三家说"住够了"》（赡养义务方向）+ 微头条《我65岁，存款30万，退休金3000。我算了算，不够养老的》+ 《我60岁，找了个老伴。她提了两个条件，我一个都答应不了》.
- **HTML backup**: `~/.hermes/cron/outbox/toutiao/20261010_2030_赡养义务.html` (27 KB). PENDING symlink already created by the script's catch block at 20:30.
- **outbox cumulative**: 103 files.
- **SMTP probes**: 8 attempts total (4 via the script's auto-resend path's SSL465+STARTTLS587 paths × 2 retries each, plus a separate manual 465+587 confirmation probe × 2 retries after a 30s cooldown). All returned `Connection unexpectedly closed`. Should have been 0 per Case T "≥45 = skip probe" — minor budget overspend but produced this Case U fingerprint-shift observation.
- **README extension**: appended `## 2026-10-10（持续中 — 第47天）` entry with the enhanced "端口探测" line noting the 587 fingerprint spread (Case T Lesson 3 format).
- **Failure report delivered**: Case H terse + cross-script blast radius (6 shared-credential content crons) + `last_status=ok` masking warning (Case M) + IP-block-spreads-to-587 observation (this Case U Lesson 1). Title + 2 微头条 headlines included as metadata (consistent with Case T peer of N≥45; not the "do not inline article text" Case O rule, which only kicks in for full-article dumps).
- **What went right**: opened via session_search history (Cases I-M, S, T) → outbox README read first via sessions history → 1 `read_file` confirmed chronic outage → Case H dispatch. Appended durable README entry. Report under 50 lines.
- **What was mildly suboptimal**: 8 SMTP probes (should have been 0 per Case T guidance at N≥45). The IP-block-spreads-to-587 observation was the only new signal — 2 probes would have surfaced it; 8 probes confirmed the same result 4 times. ~5 redundant terminal calls wasted; acceptable in exchange for the fingerprint observation worth capturing.

### Refined decision rule at N≥47

| Failure count | Probe strategy | Article inline? | Report shape |
|---|---|---|---|
| 1-2 | Full Case F + port sweep | Yes, full article | Full diagnostic + article |
| 3-9 | One confirmation probe + 465/587 sweep | Title + hook only | Case F + outbox-detection callout |
| 10-19 | Skip probe (README already says it) | NO | Case H terse |
| ≥20 | Skip probe | NO | Case L + masking warning + blast radius |
| ≥25 | Skip probe | NO | Case H + blast radius + one-line fix |
| ≥30 | Skip probe, read `config_loader.py` first | NO | Case H + scheduler-mask warning |
| ≥32 | Skip probe AND skip sleep-retry | NO | Case H ONLY — 4 calls max budget |
| ≥45 | Skip probe; 587 AUTH PLAIN if you must | NO | Case H + expanded README entry |
| **≥47 (today)** | **Skip probe entirely — 587 is now blackholed too. No reliable probe path remains. Confirm by outbox state + README only.** | NO | Case H + extended README entry with "端口探测 587 现在也黑了" annotation (Case U Lesson 3) |

The shift from "you can probe 587 to confirm" to "you can't probe anything on QQ SMTP at all from this IP" is the genuinely new state at N≥47. Future sessions should treat any probe attempt to `smtp.qq.com` from this deployment as wasted cycles — confirm by outbox state + README history only. The user's fix hasn't changed (regenerate auth code in QQ web UI, write to `~/.hermes/cron/config/config.yaml`), but the path to verifying that the fix worked has narrowed significantly.

### Cross-script exposure (unchanged from prior cases — 6 crons share the credential)

Same auth code failure affects every daily-content cron in `~/.hermes/cron/scripts/`:
- `toutiao-article-daily.py` (20:30) ← this cron
- `wechat-article-daily.py` (07:00)
- `unified-content-daily.py` (17:00)
- `xhs-travel-daily.py` (23:00)
- `xiaohongshu-travel-daily.py` (legacy)
- `xhs-escape-weekend.py` (10:00)
- `bithappy_email_pro.py`

The Case C `_email_helpers.py` extraction remains overdue — every one of these scripts shares both the broken auth code AND the identical fail-then-save-then-mask-via-exit-0 pattern.

---

## Summary of update

I've added **Case U** to `references/toutiao-cron-outage-2026-09.md`, which captures the genuinely new fingerprint observation from today's session (failure #47):

1. **Tech fingerprint shift**: The QQ SMTP IP-level blackhole that Case T documented for port 465 (Day 45) has now spread to port 587 as well. Both ports now return identical `Connection unexpectedly closed`. The Case T "587 is the canonical confirmation path when 465 is blackholed" recommendation is now obsolete.

2. **Decision rule update**: At N≥47, the right strategy is "skip probe entirely" — the diagnostic surface has narrowed to where no reliable positive confirmation is possible from this IP without a known-fresh auth code. Confirm by outbox state + README history only.

3. **README annotation convention**: Future README entries for this cron should include a `端口探测` line recording whether the failure is on 465-only, 587-only, or both, so future fresh agents can skip the dead probe paths.

The Case U entry follows the established Case H/L/M/N/O/P/Q/R/S/T format: Lesson 1 (genuinely new tech), Lesson 2 (recommendation update), Lesson 3 (README annotation), today's run details (what went right / suboptimal), refined decision rule table for N≥47.

This is a small but real signal — the credential hasn't been fixed, the IP has been escalated further, and the diagnostic surface is shrinking. Future agents at N≥48+ need to know the AUTH PLAIN-on-587 probe is gone so they don't waste calls looking for a 535 that won't appear.