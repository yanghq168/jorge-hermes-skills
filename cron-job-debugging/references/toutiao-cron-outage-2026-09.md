# `toutiao-article-daily.py` recurring outage: 2026-08-25 → present (Cases S+)

Continuation log of the recurring QQ SMTP outage captured in `references/toutiao-cron-outage-2026-08.md` (Cases A–R). When Cases S+ accumulate, this file gets appended; the SKILL.md itself holds only the durable cross-case decision rules.

**Current status (2026-09-29): 36 consecutive nights, credential `iylylmwnitbbbebi` revoked by QQ anti-spam, outbox has 70+ HTML files, `jobs.json` shows `last_status: "ok"` (masked).**

## Outage history (continued)

| Date | Failure # | Notes |
|---|---|---|
| 2026-09-25 | 32 | Same symptom, same auth code. No new lesson — pure Case H dispatch. |
| 2026-09-26 | 33 | Same symptom, same auth code. No new lesson — pure Case H dispatch. |
| 2026-09-27 | 34 | **Case S** — agent loaded the full `cron-job-debugging` skill body (including Cases H, J, L, M, N, O, P, Q, R and the "first-three-actions-mandatory" pitfall) and **then committed every documented anti-pattern in sequence**. Anti-pattern timeline + lessons below. |
| 2026-09-29 | 36 | **Case T** — yet another fresh agent, again violated the "first-three-actions-mandatory" rule (no outbox-count check, no README-read, ran the script 3 times producing 3 different topics). The failure count now stretches 36 nights, the README is the only cross-session memory that has any chance of catching the next agent. Anti-pattern confirmation + escalation below. |

## Case S — 34th consecutive identical SMTP failure: the agent reloads the skill body, sees the rules, then commits every anti-pattern at once (2026-09-27)

The `toutiao-article-daily.py` cron failed for the **34th consecutive night** (since 2026-08-25). Same auth code (`iylylmwnitbbbebi`), same `Connection unexpectedly closed`, same Case H/R dispatch should apply. What made this cycle structurally significant is that **this time the agent loaded the `cron-job-debugging` skill body in full** — including Cases H, J, L, M, N, O, P, Q, R, the "first-three-actions-mandatory" pitfall from Case P/R, the "fresh agent anti-pattern" callout, and the entire "≥29" + "≥31" decision-rule rows — **and then committed every documented anti-pattern in sequence**.

### Anti-pattern timeline (failure #34, 2026-09-27)

| Step | What was done | Documented anti-pattern violated |
|---|---|---|
| 1 | Read the first 150 lines of the script to understand its structure | None — exploration is fine |
| 2 | Ran the script via `execute_code`: `subprocess.run(["python3", "toutiao-article-daily.py"])` → failed | Case Q / R violation: agent-mode cron → should be exactly one run, AFTER outbox-check + README-read |
| 3 | Did NOT first run `ls -1 ~/.hermes/cron/outbox/toutiao/*.html \| wc -l` | Case O / P / R violation: outbox-count check is mandatory first action |
| 4 | Did NOT `read_file ~/.hermes/cron/outbox/toutiao/README.md` | Case O / P violation: README is the load-bearing signal, read it FIRST |
| 5 | Re-ran the script after `time.sleep(15)` — produced second backup with different topic | Case Q / R violation: produces duplicate outbox file with random different direction |
| 6 | Re-ran the script after `time.sleep(120)` via `execute_code` — produced third backup | Case Q / R violation: same; also burned ~2 minutes of wall-clock |
| 7 | Wrote a bespoke re-send script via `execute_code` to read PENDING and retry | Case P violation: `scripts/resend_outbox_html.py` already exists for exactly this purpose |
| 8 | Re-ran the bespoke re-send → failed (still no auth code) | Pure noise — credential didn't change |
| 9 | Manually inspected outbox state, added README extension at the end | Good — Case H durable action eventually done |

Total waste: **~5 minutes of wall-clock, ~6 redundant tool calls**, **3 different outbox files for 20260927** (随礼人情, 晚年孤独, 亲戚恩怨), and one ad-hoc re-send script that duplicates `scripts/resend_outbox_html.py`. Zero new diagnostic information was produced.

### Lesson 1 — "Load the skill" is not the same as "follow the skill"

Cases O, P, R, and the Case P "fresh agent anti-pattern" callout all explicitly warn about this pattern: an agent that reads the diagnostic recipe, sees the rules, and then proceeds to violate them anyway. Three reasons this happens:

1. **The "I've already loaded the skill" reflex feels productive** — running the script and getting an error feels like diagnostic progress. It isn't — at N≥3, the error is identical to the one the skill already documented.
2. **Retry culture overrides the documented "skip retry" rule** — the agent sees "it failed once, let me try again" and burns one more rate-limit attempt. At N≥30, retry is pure ceremony.
3. **Each new failure feels novel** — the agent treats tonight as "a fresh diagnostic opportunity" instead of "the N-th iteration of a known recurring failure." The mental model should be "I am dispatching a runbook entry, not investigating."

### Lesson 2 — `time.sleep()` inside `execute_code` is doubly costly

The agent used `time.sleep(15)` and `time.sleep(120)` inside `execute_code` to "give QQ SMTP time to recover from greylisting." Two costs:

1. **Wall-clock** — the `execute_code` call itself blocks the agent loop for the sleep duration. A 120s sleep is 2 minutes where the agent could be doing zero-RAM work like reading the outbox README or extending it. The actual recovery from QQ's greylist takes 10-30 minutes — a 2-minute sleep accomplishes nothing.
2. **Token cost** — `execute_code` returns the script's output plus any print statements, which is fine, but the agent loop continues to count this as a tool call. Three sleep-then-retry cycles = three tool calls + three failed SMTP attempts + three more outbox files.

**The fix:** do NOT sleep-and-retry inside `execute_code`. If you want to give the SMTP rate-limit time to recover, set a wall-clock alarm via `terminal(background=True, notify_on_complete=True)` and continue with other work. Better: skip the retry entirely at N≥10 per Case H — the credential is binary dead, sleeping won't change it.

### Lesson 3 — Ad-hoc resend scripts duplicate the skill's helper

The Case P agent already shipped `scripts/resend_outbox_html.py`. The Case S agent, instead of using it, wrote a one-off inline Python via `execute_code -c` that:

- Read the PENDING symlink
- Parsed direction from filename
- Reconstructed subject from `<title>` tag
- Sent via `smtplib.SMTP_SSL`
- Caught `SMTPServerDisconnected`

This is a verbatim subset of `scripts/resend_outbox_html.py`. Worse, it had no retry handling, no platform-specific From-header pattern, no "stop at ≥2 consecutive failures" guard. The skill helper exists; use it.

**The fix:** if you find yourself about to write a `python3 -c "..."` SMTP-send block, **first check `~/.hermes/skills/cron-job-debugging/scripts/`** for an existing helper. If one exists (`resend_outbox_html.py`, `send_email_with_outbox.py`, `probe_smtp.py`), use it. If none fits, extend one of them rather than writing ad-hoc inline Python.

### Today's run (2026-09-27, failure #34)

- **Generated**: 3 different topics from 3 back-to-back runs:
  - Run #1: 长文《65岁老人随了20年份子钱，最后一场酒席没请他：人情薄如纸》（随礼人情）
  - Run #2: 长文《75岁独居老人，每天最期待的事，是去菜市场跟卖菜的大姐说两句话》（晚年孤独）
  - Run #3: 长文《63岁大伯给侄子出了20万学费，侄子毕业后第一件事是"断了联系"》（亲戚恩怨）
  - All 3 plus micro-articles. Only `亲戚恩怨` (run #3, 20:33) matches the user's prompt direction (`亲戚恩怨` is one of the four named prompt directions: 养老/遗产/赡养/亲戚恩怨).
- **HTML backup**: 3 files dated 20260927 at 2030 and 2033. The `PENDING_20260927.html` symlink (Case Q Lesson 2 convention) points at the last-written: `20260927_2033_亲戚恩怨.html`.
- **SMTP probe**: ran via `execute_code -c` (bespoke inline), failed in <1s, no new info.
- **Resend attempt**: ran via bespoke `execute_code -c`, failed identically.
- **README extension**: done at the end with the `## 2026-09-27（持续中 — 第34天）` entry. Good — Case H durable action completed even though the rest of the cycle violated the rules.
- **Failure report delivered**: hybrid Case L + Case R template (outbox path + generated title + cross-script blast radius + masking warning + one-line fix). Acceptable length for `deliver: origin` channel.

### New pitfalls (capture verbatim in SKILL.md Pitfalls section at next edit window)

> **"Loading the skill body" is necessary but not sufficient — the agent must also follow its decision rules at N≥3.** Cases O, P, R, and now S document the same anti-pattern across four consecutive cron sessions: an agent loads `cron-job-debugging`, sees the rules, then proceeds to violate the very rules it just read. The fix is structural: **the first THREE actions of any cron-session touching a documented recurring failure are mandatory and unconditional** — (1) `ls -1 ~/.hermes/cron/outbox/<platform>/*.html | wc -l`, (2) `read_file ~/.hermes/cron/outbox/<platform>/README.md`, (3) deliver the Case H dispatch. No "let me confirm with a probe first," no "let me try running it to see the current state." The skill is the source of truth at N≥3; the script run is just noise.

> **`time.sleep(N)` inside `execute_code` to wait out QQ's greylist is wasted budget at N≥10.** At failure counts ≥10, the credential is binary dead — sleeping 15s, 120s, or 600s won't change that. The wall-clock burn + token cost of sleep-then-retry is pure overhead. If you genuinely want to retry after a real network blip (N=1-2 only), use `terminal(background=True, notify_on_complete=True)` and continue other work — don't block the agent loop.

> **Before writing an ad-hoc inline SMTP-send script, check `~/.hermes/skills/cron-job-debugging/scripts/` for existing helpers.** `scripts/resend_outbox_html.py`, `scripts/send_email_with_outbox.py`, and `scripts/probe_smtp.py` cover the common patterns. If none fits, extend an existing helper rather than writing a one-off `python3 -c "..."` block — the helpers have retry guards, platform-specific From-headers, and "stop at ≥2 consecutive failures" logic that an inline script won't.

### Refined decision rule at N≥34

Combining Cases H, J, L, M, N, O, P, Q, R, S:

| Failure count | Action |
|---|---|
| 1-2 | Full Case F diagnostic + outbox-save confirmation |
| 3-9 | One confirmation probe + Case F report + outbox-detection callout |
| 10-19 | Skip probe (README already says it) + Case H terse + outbox path only |
| ≥20 | Skip probe + Case H terse + masking warning per Case M |
| ≥25 | Skip probe + terser still + blast-radius count + one-line fix |
| ≥26 | Same as ≥25, AND commit a `scripts/resend_outbox_html.py` for recovery (Case P) |
| ≥29 | Same as ≥26, AND (1) frequency-limit-detection patch (avoid rate-limit burn on retries), (2) `PENDING_<date>.html` symlink convention, (3) run at most once per cron cycle (Case Q lesson 3) |
| ≥31 | Same as ≥29, AND (1) read `config_loader.py` BEFORE `config.yaml` when hunting for the credential (Case R Lesson 2), (2) match the run count to the scheduler mode (Case R Lesson 1) |
| **≥34 (today)** | Same as ≥31, AND (1) the first THREE actions are mandatory: outbox-count, README-read, Case H dispatch — no diagnostic theater even after loading the skill body (Case S anti-pattern), (2) NEVER use `time.sleep()` inside `execute_code` to wait out a known-dead credential at N≥10 — it accomplishes nothing, (3) check `scripts/resend_outbox_html.py` BEFORE writing any ad-hoc SMTP-send inline block |

## SKILL.md size pressure (2026-09-27)

The `cron-job-debugging` SKILL.md has now crossed the 100,000-character `skill_manage patch` size limit (102,141 chars). Future Case S+ entries should be appended to **this reference file** (`references/toutiao-cron-outage-2026-09.md`), not the main SKILL.md body. The "Durable cross-case decision rules" should live in the SKILL.md; the case-specific transcripts should live here. The split:

- **SKILL.md** (~100k chars): §1-7 of the diagnostic loop, Pitfalls, Cross-reference, Recovery scripts, Diagnostic commands cheatsheet — i.e. the "how to debug" content
- **references/toutiao-cron-outage-2026-08.md** (~30k chars): Cases A, C, D, E, F, G, H, I, J, L, M, N, O, P, Q, R — the "worked example" of the recurring failure
- **references/toutiao-cron-outage-2026-09.md** (this file): Case S onwards — append-only continuation log
- **references/outage-readme-template.md**: README entry template

When the SKILL.md is refactored next, the Cases A-S content can be split into individual case files (e.g. `references/cases/case-S-34th-failure.md`) for easier navigation. Until then, this file is the canonical append target for new outage cycles on this deployment.

## Cross-references

- `references/toutiao-cron-outage-2026-08.md` — Cases A-R, the original worked example
- `references/smtp-credential-failure-case-study.md` — Case A 535 transcript, Case B silent-reject, Case K IP-block
- `references/outage-readme-template.md` — README entry template (used by Case H durable action)
- `scripts/resend_outbox_html.py` — recovery helper for after the user fixes the auth code
- `scripts/probe_smtp.py` — verify a fresh credential before resuming cron

## Case T — 36th consecutive identical SMTP failure: confirmation that the load-skill-but-don't-follow-skill anti-pattern recurs (2026-09-29)

The `toutiao-article-daily.py` cron failed for the **36th consecutive night** (since 2026-08-25). Same auth code (`iylylmwnitbbbebi`), same `Connection unexpectedly closed`, same Case H/R/S dispatch should apply. This cycle was a **confirmation**, not a new lesson — but the failure is significant enough to merit its own case entry because it shows the load-skill-but-don't-follow-skill anti-pattern (Cases O, P, R, S) **persists across cycles** even when the previous cycle's Case S was added to the reference file. The fix isn't another case entry; the fix is escalation.

### Anti-pattern timeline (failure #36, 2026-09-29)

| Step | What was done | Documented anti-pattern violated |
|---|---|---|
| 1 | Read the first 400 lines of the script via `read_file` | Mild — exploration, but wasted when README would have said "QQ auth revoked" in 1 line |
| 2 | Ran the script via `terminal`: produced backup 1 (赡养义务 direction) | Case Q / R violation: should be exactly one run AFTER outbox-check + README-read |
| 3 | Did NOT run `ls -1 ~/.hermes/cron/outbox/toutiao/*.html \| wc -l` | Case J / O / P / R violation: outbox-count check is mandatory first action |
| 4 | Did NOT `read_file ~/.hermes/cron/outbox/toutiao/README.md` | Case O / P / S violation: README is the load-bearing signal |
| 5 | Re-ran the script with `sleep 30` → produced backup 2 (遗产分配) | Case Q / R / S violation: duplicate outbox file with random different direction |
| 6 | Re-ran the script with `sleep 60` → produced backup 3 (房产纠纷) | Case Q / R / S violation: same; wall-clock burn ~60s + token cost |
| 7 | Re-ran the script immediately → produced backup 4 with same direction as #3 | Case Q / R / S violation: pure noise — re-running doesn't retry SMTP, just generates fresh random content |
| 8 | Confirmed SMTP failure with manual `smtplib.SMTP_SSL` probe → 535 in <1s | Pure ceremony at N=36 — README + Case I already documented this transcript verbatim |
| 9 | Reported the failure with generated article title + hook + micro-article titles + image-prompt count | Case H / O violation: at N≥10 reports should be 4-line terse, no inline content |

Total waste: **~4 minutes of wall-clock** (mostly sleeps), **~10 terminal calls**, **4 different outbox files for 20260929** (赡养义务, 遗产分配, 房产纠纷 × 2), one bespoke manual probe that confirmed what 35 previous sessions had already documented. Zero new diagnostic information produced.

The pattern from Case S **recurred verbatim** despite the Case S entry being present in the very reference file that should have been the FIRST file read. This confirms: **just adding more Case entries to the reference file does not stop the anti-pattern.** What stops it is the structural enforcement described in Lesson 1 below.

### Lesson 1 — Reference-file accumulation is not a control surface

Cases S+ have grown the reference file from "Cases A-R log" to "Cases A-T log" in roughly 2 weeks. Each new case captures the same anti-pattern with more timestamps. **The anti-pattern doesn't read more carefully because there are more cases.** A fresh agent loads the skill body, sees the size, and either (a) skips the reference file entirely, or (b) reads the body summary but treats the per-case detailed entries as "history" rather than "rules."

The structural fix is in the skill body, not the reference file. The skill body already has the "first-three-actions-mandatory" pitfall and the Case R "≥31" decision-rule row. **At N≥36, the next escalation step is to add the MANDATORY-FIRST-THREE-ACTIONS as a numbered step in §1-7 of the diagnostic loop, not as a pitfall buried in the bottom.** Pitfalls get skimmed; numbered steps force the order. Concretely: add a new step between §1 and §2 of the SKILL.md diagnostic loop, titled "Pre-flight check: read the outbox README first."

### Lesson 2 — The cron-prompt's framing should bias toward terse dispatch

The cron prompt that triggered this session was a 3-line user instruction:

```
每晚8点半运行 ~/.hermes/cron/scripts/toutiao-article-daily.py 生成当日头条文章，
发送HTML邮件到 569545015@qq.com。
发件人：围炉家常话（头条）
```

At N=36, the **cron-prompt itself is wrong.** It tells the agent to "run the script and send the email" — exactly the wrong actions at this failure count. The right cron-prompt at N=36 should be:

```
头条文章 cron 运行中。SMTP 自 2026-08-25 起失败 (QQ 授权码 iylylmwnitbbbebi 被吊销)，
outbox/toutiao/ 现有 70+ 备份，README 标记"持续中 第36天"。
不要运行脚本（除非今天还没有任何 outbox 文件）。
不要重试 SMTP。
只需追加 ## 2026-09-29（持续中 — 第36天）到 outbox/toutiao/README.md，
按 Case H 模板发出 4 行摘要，指向 outbox 备份路径。
```

A 4-line terse cron-prompt produces a 4-line terse cron-output. The current 3-line terse-but-action-instructive prompt produces a verbose runbook-violation cycle. **At N≥20, the cron prompt needs to be re-authored to bias toward terse dispatch.**

This lesson is action-relevant but not currently actionable from inside this cron session. It belongs in the user's `~/.hermes/cron/jobs.json` edit queue, not in this file. Captured here so the user (or a future config-edit session) sees the suggestion.

### Lesson 3 — `time.sleep()` inside cron sessions is even worse than `time.sleep()` in `execute_code`

Case S Lesson 2 documented `time.sleep()` inside `execute_code`. The 2026-09-29 session used `time.sleep()` in `terminal` instead. Same problem: blocks the agent loop for the sleep duration, accomplishes nothing at N≥10, costs both wall-clock and tokens. The fix is identical: at N≥10 do not sleep-and-retry; the credential is binary dead.

### Today's run (2026-09-29, failure #36)

- **Generated**: 4 different topics from 4 back-to-back runs:
  - Run #1 (20:30): 长文《67岁老人被三个儿子轮流养老，每家住四个月，第三家说"住够了"》（赡养义务） + 微头条《我儿子一年给我打5个电话...》+ 《我60岁，找了个老伴...》
  - Run #2 (20:31, after sleep 30): 长文《72岁老人存了40万，遗嘱写好两年，去世后三个子女差点打起来》（遗产分配） + 微头条《我60岁，找了个老伴...》+ 《随了20年份子钱...》
  - Run #3 (20:32, after sleep 60): 长文《69岁老人把房子过户给儿子后，儿媳说"这房子是我们的，你凭什么住"》（房产纠纷） + 微头条《婆婆来家里住了一个月...》+ 《我60岁，找了个老伴...》
  - Run #4 (20:32, immediate): Same as Run #3 — identical topic, identical micro-articles, same direction. Pure noise; demonstrated that re-running doesn't retry SMTP, it just produces duplicate content.
- **HTML backup**: 4 files dated 20260929 (2030, 2031, 2032, 2032). The `PENDING_20260929.html` symlink points at `20260929_2032_房产纠纷.html` (last written per the script's `pending.symlink_to(fname.name)` line).
- **SMTP probe**: ran via `terminal -c "smtplib.SMTP_SSL...login()"`, failed in <1s, 535 confirmed.
- **Failure report delivered**: inlined generated article title + hook + micro-article titles + image-prompt count. Violates Case H/O rule for N≥10.
- **README extension**: NOT done in this session. The README still ends with "## 2026-09-27（持续中 — 第34天）" entry — no entry for 2026-09-28 or 2026-09-29. **This is the durability gap**: each cycle that fails to append the README makes the next cycle more likely to repeat the anti-pattern (because the README under-reports the failure count, weakening the signal).
- **Cross-script blast radius unchanged**: wechat-article-daily.py, unified-content-daily.py, xhs-travel-daily.py, xiaohongshu-travel-daily.py, xhs-escape-weekend.py, bithappy_email_pro.py all share the credential.

### Refined decision rule at N≥36

Combining Cases H, J, L, M, N, O, P, Q, R, S, T:

| Failure count | Action |
|---|---|
| 1-2 | Full Case F diagnostic + outbox-save confirmation |
| 3-9 | One confirmation probe + Case F report + outbox-detection callout |
| 10-19 | Skip probe (README already says it) + Case H terse + outbox path only |
| ≥20 | Skip probe + Case H terse + masking warning per Case M |
| ≥25 | Skip probe + terser still + blast-radius count + one-line fix |
| ≥26 | Same as ≥25, AND commit a `scripts/resend_outbox_html.py` for recovery (Case P) |
| ≥29 | Same as ≥26, AND (1) frequency-limit-detection patch (avoid rate-limit burn on retries), (2) `PENDING_<date>.html` symlink convention, (3) run at most once per cron cycle (Case Q lesson 3) |
| ≥31 | Same as ≥29, AND (1) read `config_loader.py` BEFORE `config.yaml` when hunting for the credential (Case R Lesson 2), (2) match the run count to the scheduler mode (Case R Lesson 1) |
| ≥34 | Same as ≥31, AND (1) the first THREE actions are mandatory: outbox-count, README-read, Case H dispatch — no diagnostic theater even after loading the skill body (Case S anti-pattern), (2) NEVER use `time.sleep()` inside `execute_code` to wait out a known-dead credential at N≥10 — it accomplishes nothing, (3) check `scripts/resend_outbox_html.py` BEFORE writing any ad-hoc SMTP-send inline block |
| **≥36 (today)** | Same as ≥34, AND (1) **adding more Case entries does not stop the anti-pattern** — escalation must move to structural enforcement in the SKILL.md §1-7 diagnostic loop (not buried in pitfalls), so the next session is forced to outbox-count + README-read before any script execution (Case T Lesson 1), (2) at N≥20 the cron-prompt itself becomes part of the problem and should be re-authored to bias toward terse dispatch (Case T Lesson 2), (3) gaps in the README extension cadence are a structural durability problem — each cycle that fails to append the README weakens the signal for the next cycle |