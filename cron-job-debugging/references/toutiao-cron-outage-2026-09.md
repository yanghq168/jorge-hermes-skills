# `toutiao-article-daily.py` recurring outage: 2026-08-25 → 2026-09-27 (Cases S+)

Continuation log of the recurring QQ SMTP outage captured in `references/toutiao-cron-outage-2026-08.md` (Cases A–R). When Cases S+ accumulate, this file gets appended; the SKILL.md itself holds only the durable cross-case decision rules.

**Current status (2026-09-27): 34 consecutive nights, credential `iylylmwnitbbbebi` revoked by QQ anti-spam, outbox has 74 HTML files, `jobs.json` shows `last_status: "ok"` (masked).**

## Outage history (continued)

| Date | Failure # | Notes |
|---|---|---|
| 2026-09-25 | 32 | Same symptom, same auth code. No new lesson — pure Case H dispatch. |
| 2026-09-26 | 33 | Same symptom, same auth code. No new lesson — pure Case H dispatch. |
| 2026-09-27 | 34 | **Case S** — agent loaded the full `cron-job-debugging` skill body (including Cases H, J, L, M, N, O, P, Q, R and the "first-three-actions-mandatory" pitfall) and **then committed every documented anti-pattern in sequence**. Anti-pattern timeline + lessons below. |

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