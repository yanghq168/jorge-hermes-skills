# Chronic-outage case log — `toutiao-article-daily.py` QQ SMTP failure

**This is a session-detail reference.** The class-level playbook lives in
`../SKILL.md` (diagnostic loop, SMTP deep-dive, escalation policy). This file
holds the per-night narrative history from 2026-09-02 onward — each "Case X"
section is one cron-run session that added a lesson. Read it when you need the
*history* of a specific failure or the reasoning behind a rule; do NOT read it
as your first step on a live outage (the SKILL.md escalation policy covers that).

Companion references: `toutiao-cron-outage-2026-08.md` (original outage,
Cases A–F), `toutiao-cron-outage-2026-09.md` (Cases S+, failure #34 onward),
`toutiao-cron-outage-2026-10-week4.md` (Cases X/Y, failure #59+),
`smtp-credential-failure-case-study.md` (full SMTP transcripts),
`case-m-last-status-masking.md`, `feishu-stale-thread-id-delivery-failure.md`.

---

## Durable lessons distilled from these cases (read this first)

| # | Lesson | Where it lives now |
|---|--------|--------------------|
| 1 | **README-first rule** — at failure N≥3, `read_file ~/.hermes/cron/outbox/<platform>/README.md` before any probe. The README is the cross-session memory; probes are confirmation, not investigation. | SKILL.md Pitfalls |
| 2 | **Same-outage detection** — `ls -1 ~/.hermes/cron/outbox/<platform>/*.html \| wc -l` ≥3 with no "已恢复" in the README ⇒ known chronic failure, skip the diagnostic loop. | SKILL.md Pitfalls |
| 3 | **Time-to-failure fingerprint** — a revoked QQ auth code returns 535 in **<1s**; a real network fault takes 10–15s to time out. | SKILL.md Pitfalls |
| 4 | **Manual AUTH LOGIN + `getreply()` per step** is the only deterministic 535-surfacer. `debuglevel=1` AND `debuglevel=2` both bury it (smtplib retries AUTH PLAIN→AUTH LOGIN and the 2nd teardown scrolls past). | SKILL.md §5 |
| 5 | **Never conclude "IP-level AUTH block"** from `SMTPServerDisconnected` alone. Case K was *disproven* 2026-10-20 (failure #57) by a raw-socket control test that produced an explicit 535. TCP/TLS were healthy; the "block" was smtplib's retry logic. | SKILL.md Pitfalls |
| 6 | **Run-count rule** — agent-mode prompt crons: run the script **exactly once** (you ARE the canonical run, no backup exists yet). Classic-cron / no_agent script-mode crons: run **zero** times (the backup already exists). | SKILL.md Pitfalls |
| 7 | **Credential path** — read `config_loader.py` FIRST (it names the exact YAML key path); `config.yaml` may show `mail: null` and hide the value. | SKILL.md Pitfalls |
| 8 | **`last_status=ok` masks delivery failure** — the scheduler records ok when the *job* ran; delivery failure only shows in `last_delivery_error`. Preferred fix: `sys.exit(1)` when `send_email()` returns False. | `references/case-m-last-status-masking.md` |
| 9 | **Two schedulers, no shared observability** — `crontab.txt` and Hermes `jobs.json` both fire at 20:30 with overlapping coverage. The outbox is the only neutral ground. | SKILL.md Pitfalls |
| 10 | **README extension is independent of the report** — the cron report scrolls past in the chat; the README persists. `grep -c "^## " README.md` must increase by 1 every session. | SKILL.md Pitfalls (Case W) |
| 11 | **Escalate the report, don't repeat it** — the report should shrink as N climbs. N≥10 ⇒ terse 4-line dispatch; N≥20 ⇒ add the masking warning; N≥25 ⇒ add blast-radius count. | SKILL.md "Escalation policy" |
| 12 | **Do not inline the article** — after night 3, point at the outbox path. Pasting 1500+ words is token-burn. | SKILL.md Pitfalls |
| 13 | **One revoked credential fails N scripts** — grep all of `~/.hermes/cron/scripts/` for `smtp_pass` / `get_mail_config` to find the real blast radius. | SKILL.md Pitfalls |
| 14 | **Dedup must be asserted, not assumed** — a read-key ≠ write-key mismatch makes rotation a silent no-op. Assert the candidate set shrinks; simulate N days before shipping. | SKILL.md Pitfalls |
| 15 | **New rotation features need backfill** — a fresh history file starts empty ⇒ dedup is a no-op until the window fills. Backfill from ground truth and check the *frequency distribution*. | SKILL.md Pitfalls |
| 16 | **`str.format(**kwargs)` silently drops unreferenced kwargs** — "renders without error" does NOT prove the output is complete. Grep the rendered product for the key fields. | SKILL.md Pitfalls |
| 17 | **A dead mail channel is not a dead content channel** — push the HTML as a native file attachment on a healthy chat route instead of only reporting "email failed". | `references/toutiao-cron-outage-2026-10-week4.md` |
| 18 | **Don't write a bespoke script for a 30-second cleanup** — a bash one-liner is correct; over-engineering one-off tooling is an anti-pattern. | SKILL.md Pitfalls (Case P) |

---

## Per-night case narrative (chronological)

## Case G — Agent-mode cron variant: 7th consecutive failure, outbox accumulation, importlib bypass (2026-09-02)

The `toutiao-article-daily.py` cron failed for the 7th consecutive night with the identical `Connection unexpectedly closed` symptom on the identical `<revoked auth code>` auth code. By this point the diagnostic is fully internalized. What was genuinely new this cycle:

### Agent-mode vs no_agent script-mode crons

The cron-job entry in `jobs.json` shows `no_agent: false` and `script: null` — meaning the cron triggers an **agent run with a prompt**, not direct script execution. The agent's prompt is `"运行 ~/.hermes/cron/scripts/toutiao-article-daily.py 生成当日头条文章..."`. Inside the agent, the script gets imported/run like any other Python. Two practical consequences:

1. **The agent can self-debug by re-invoking the script directly** — run `python3 ~/.hermes/cron/scripts/toutiao-article-daily.py` from the agent's terminal to reproduce the failure with full control.
2. **The cron-output → user-message pipeline IS the delivery surface.** When `deliver: origin` is set (e.g. to Feishu/Lark topic), the agent's final response auto-routes there. So the failure report rides that same channel — and it MUST contain the outbox path + the fix command verbatim, because the email channel is broken.

### Importlib bypass technique: regenerate content without burning SMTP

When you want to inspect what a cron script produces (for the report) without burning another failed SMTP attempt, use `importlib.util.spec_from_file_location` to import the script as a module and call `main()` directly. The script's SMTP will still run (Python's `__name__` guard fires only on direct execution, not on importlib), so wrap by stubbing `send_email` BEFORE `exec_module`:

```python
import importlib.util
spec = importlib.util.spec_from_file_location("toutiao_mod", "/home/ubuntu/.hermes/cron/scripts/toutiao-article-daily.py")
mod = importlib.util.module_from_spec(spec)
def fake_send_email(html, plain, topic, micro):
    print(f"[FAKE] subject={topic['title']}, html_len={len(html)}")
    return True, "FAKE"
mod.send_email = fake_send_email       # override BEFORE exec_module
spec.loader.exec_module(mod)            # NOW the top-level code's send_email reference resolves to fake
html, plain, topic, micro = mod.main()
```

**Pitfall:** the `if __name__ == "__main__": main()` guard does NOT fire when loaded via importlib. Top-level code (including decorators and immediate `main()` calls if any) WILL execute on import. If the script calls `main()` outside the guard, you will get a second content-generation + failed-SMTP cycle. Check the script's top level first; if it has the `if __name__ == "__main__":` guard, you're safe.

A cleaner alternative: **import the module, then call only the generation functions explicitly** without invoking `main()`:

```python
spec.loader.exec_module(mod)
# Don't call mod.main() — call the generators directly
html, plain, topic = mod.generate_article()
micro = mod.generate_micro_articles()
# Skip mod.send_email() entirely
```

This avoids the guard pitfall AND avoids the second SMTP attempt.

### Outbox accumulation pattern: 7+ days of identical failures

By day 7+, `~/.hermes/cron/outbox/toutiao/` has accumulated ~10 HTML files (one per night, all ~27 KB, all generated by the same script with different topic directions). This is **correct behavior** — the script does exactly what Case C designed it to do. But the user eventually needs to clean these up after the credential is fixed. The recommended cleanup recipe:

```bash
# After the user regenerates the QQ auth code and confirms a clean run:
mkdir -p ~/.hermes/cron/outbox/toutiao/$(date +%Y-%m)_archive
# Move all-but-the-most-recent into the archive
ls -t ~/.hermes/cron/outbox/toutiao/*.html | tail -n +2 | \
  xargs -I {} mv {} ~/.hermes/cron/outbox/toutiao/$(date +%Y-%m)_archive/
# Append a one-line outage summary to outbox/README.md so future sessions see it
cat >> ~/.hermes/cron/outbox/toutiao/README.md <<EOF
## Outage 2026-08-28 → 2026-09-02 (7 nights)
- Symptom: Connection unexpectedly closed on smtp.qq.com:465 (QQ silent-reject Case B)
- Root cause: SMTP authorization code <revoked auth code> revoked by QQ anti-spam
- Fix applied: user regenerated auth code in QQ web UI, updated ~/.hermes/cron/config/config.yaml
- Verified: cron at 20:30 next night returned ✅ 邮件发送成功
EOF
```

The README's outage log is the **durable memory** for "what happened during this stretch" — survives across cron-job-script edits and config changes. Future sessions encountering the same auth code + same failure can grep `~/.hermes/cron/outbox/<platform>/README.md` to confirm whether the current outage has been seen before.

### Outage detection via outbox age

A useful diagnostic shortcut for any future "is the SMTP broken right now?" question:

```bash
# How many nights has the outbox been growing without a successful cron?
ls -1 ~/.hermes/cron/outbox/toutiao/*.html | wc -l
# Count of consecutive failed nights = (today - oldest_outbox_file_date)
# If ≥3, switch immediately to user-fix mode per the Case F decision rule.
```

## Case H — 10th consecutive identical SMTP failure: terse runbook dispatch mode (2026-09-03)

The `toutiao-article-daily.py` cron failed for the 10th consecutive night (since 2026-08-25). Same auth code (`<revoked auth code>`), same `Connection unexpectedly closed`, same `535 Login fail` in the SMTP transcript. Every diagnostic step from Cases A–G has been confirmed multiple times. New lesson this cycle: **the report should shrink, not grow, as the failure count climbs.**

### What NOT to do at failure N≥10

- Re-run `probe_smtp.py` — confirms what we already know, burns tokens.
- Re-explain what `535 Login fail` means — user has seen it 9 times.
- Re-list the full SMTP deep-dive steps — they're in this skill, the user knows.
- Suggest "try port 587 instead" — already covered in Case A; the credential is binary dead, transport won't help.
- Paste the full article HTML inline — the outbox already has it.

### What to do at failure N≥10

Compress the failure report to four lines:

```
📋 头条文章日报（N天连续失败）
✅ 内容生成成功 → outbox/toutiao/20260903_2030_赡养义务.html
❌ 邮件未送达：QQ SMTP 535 Login fail（同 <revoked auth code> 第N天）
🔧 修复：mail.qq.com → 账户 → SMTP服务 → 重新生成授权码 → 写回 ~/.hermes/cron/config/config.yaml
```

That's it. No probe, no transcript dump, no alternative-transport suggestion. The user knows what to do; they're either (a) traveling / away from QQ web UI, (b) deferred it as low priority, or (c) genuinely forgot. The terse reminder with a concrete fix command is the highest-value response.

**Always append to `outbox/<platform>/README.md` as the durable action** — the cron-output report rides the `deliver: origin` channel and disappears from view after the user scrolls past it. The README entry is the cross-session memory that survives across cron runs. Use the format from `references/outage-readme-template.md`:

```bash
cat >> ~/.hermes/cron/outbox/toutiao/README.md <<EOF
## YYYY-MM-DD（持续中 — 第N天）
- Symptom: Connection unexpectedly closed on smtp.qq.com:465 (auth code <revoked auth code>)
- Generated content: outbox/toutiao/YYYYMMDD_HHMM_<direction>.html
- Fix: mail.qq.com → 账户 → SMTP服务 → 重新生成授权码 → 写回 ~/.hermes/cron/config/config.yaml
EOF
```

Skipping this step is the most common way a chronic outage loses its history — the agent that runs next week has no record of how long the credential has been dead, and will waste tokens re-running the full diagnostic loop instead of jumping to Case H.

### Outbox count = silent outage clock

`ls ~/.hermes/cron/outbox/<platform>/ | grep -c '\.html$'` is now the canonical "how broken is SMTP right now" indicator. The count grows by 1 per failed night, freezes when fixed. If the count is ≥7 and the README.md has no "Outage resolved" entry, the outage is live. Use this to skip Step 1 of the diagnostic loop entirely — go straight to report.

### Diagnostic sequence for a fresh agent on a chronic outage (2026-09-10, failure #16)

When a fresh session encounters a cron that prints `❌ 发送失败: Connection unexpectedly closed`, the optimal sequence is:

1. **Outbox count** (`ls -1 ~/.hermes/cron/outbox/<platform>/*.html 2>/dev/null | wc -l`) — if ≥3, jump straight to step 6.
2. **Re-run script directly** (`python3 ~/.hermes/cron/scripts/<script>.py`) to reproduce and confirm it's not an agent-mode wrapper artifact.
3. **Probe with `smtplib.SMTP_SSL` + `debuglevel=2`** to see if 535 surfaces — Case J confirmed `debuglevel=2` ALSO buries the 535 for this QQ deployment, so don't expect it.
4. **Manual AUTH LOGIN + `getreply()` per step** (Case I recipe) — this IS the deterministic 535-surfacer. Always prefer over `debuglevel` alone.
5. **Port sweep** (465 SSL → 587 STARTTLS → 25 plain) — if all three die in <1s with 535, credential is dead. If 25 is "Network is unreachable" but 465/587 die fast, credential is dead AND ISP blocks port 25 (orthogonal problem).
6. **DNS / IP check** (`socket.getaddrinfo('smtp.qq.com', 465)`) — useful to rule out CDN/routing issues. If TCP connect succeeds (already verified by `SMTP_SSL` opening), DNS is fine.
7. **Terse Case H report** — only after the count + 535 are confirmed. Include outbox path + one-line fix.
8. **README extension** — append the `## YYYY-MM-DD（持续中 — 第N天）` entry to `outbox/<platform>/README.md` (Case H pattern). This is the durable cross-session memory.

The whole sequence should complete in under 60 seconds for an experienced agent. If it's taking longer, you're debugging the wrong thing — the skill already covers it.

## Case I — 14th consecutive identical SMTP failure: low-level AUTH LOGIN probe reveals explicit 535 (2026-09-07)

The `toutiao-article-daily.py` cron failed for the **14th consecutive night** (since 2026-08-25). Same auth code, same symptom, same Case H terse-report pattern applied. What was genuinely new this cycle was a **cleaner diagnostic recipe** that surfaces the 535 more reliably than `smtplib.SMTP.debuglevel = 1`.

### The probe recipe that always surfaces the 535

`debuglevel=1` works most of the time but has a known failure mode (Case B silent-reject) where the server tears down the TLS socket mid-AUTH with **no `reply:` line printed**, and you get a bare `SMTPServerDisconnected`. When the server DOES send the 535 reply (the common case for this QQ deployment), `debuglevel=1` sometimes buries it inside the AUTH PLAIN framing because Python retries with AUTH LOGIN after the first 535 — the second AUTH closes abruptly and your terminal scrolls past the actual rejection.

A **deterministic** recipe: do AUTH LOGIN yourself and call `getreply()` after each step. The 535 always shows up as its own line:

```python
import smtplib, base64
server = smtplib.SMTP_SSL('smtp.qq.com', 465, timeout=15)
server.ehlo()
server.send(b"AUTH LOGIN\r\n")
code, msg = server.getreply()
assert code == 334, f"unexpected: {code} {msg!r}"
server.send(base64.b64encode(b'569545015@qq.com') + b'\r\n')
code, msg = server.getreply()
assert code == 334, f"unexpected: {code} {msg!r}"
server.send(base64.b64encode(b'<AUTH_CODE>') + b'\r\n')
code, msg = server.getreply()
print(f"FINAL: {code} {msg!r}")
# On this deployment prints: FINAL: 535 b'Login fail. Account is abnormal, ...'
```

What came out this session (2026-09-07):

```
EHLO: 250: b'newxmesmtplogicsvrszb51-0.qq.com\nPIPELINING\n... AUTH LOGIN PLAIN XOAUTH XOAUTH2\n...'
AUTH LOGIN -> 334: b'VXNlcm5hbWU6'                    # base64("Username:")
username -> 334: b'UGFzc3dvcmQ6'                       # base64("Password:")
password -> 535: b'Login fail. Account is abnormal, service is not open,
                  password is incorrect, login frequency limited, or system is busy.
                  More information at https://help.mail.qq.com/detail/108/1023'
```

This is the **canonical 535-in-transcript signature** (Case A), NOT the silent-close variant (Case B). Important distinction: the silent-close variant is rare for this deployment; the explicit-535 variant is the norm. The current skill's "QQ silent-reject variant" callout in §5 over-emphasizes the rare case — future sessions may waste time looking for "no reply line" patterns that aren't there.

### Decision rule refinement

| Transcript signature | Mode | Frequency on this deployment |
|---|---|---|
| EHLO 250 → AUTH 334 → AUTH 334 → **535 Login fail** (explicit) | Case A — credential revoked, polite SMTP reply | **Common** (this session, 2026-08-23, Case A) |
| EHLO 250 → AUTH... → bare `SMTPServerDisconnected` (no `reply:` line) | Case B — credential revoked, aggressive anti-spam | Rare (Case B 2026-08-24 only) |
| Connect-time failure (timeout / ConnectionRefusedError / SSLError) | Case C — real network/firewall | Rare |

**For this QQ deployment specifically, expect Case A — the explicit 535.** The Case B silent-reject warning still applies (don't dismiss it as "network" if you see it), but the default mental model should be "expect a 535 line in the transcript; the bug is the auth code, not the network".

### Outbox accumulation: 27 HTML files at failure N=14

`~/.hermes/cron/outbox/toutiao/` now contains 27 HTML files (was 17 at Case H, +10 across Cases I + intervening runs that hit the same outage). At ~27 KB each, the cumulative on-disk size is 764 KB. **This is correct behavior** — every night's content is preserved.

The `outbox/toutiao/README.md` was extended with a "## 2026-09-07（持续中 — 第14天）" entry following the Case C/G convention. The README now reads as a cumulative outage log: 2026-08-25 (initial), 2026-09-07 (still ongoing). Future sessions checking this directory will see the live outage timestamp and skip the diagnostic loop entirely.

### Cross-script exposure unchanged

Every daily-content cron in `~/.hermes/cron/scripts/` shares the same `config_loader.get_mail_config()` and would fail identically today: `wechat-article-daily.py`, `unified-content-daily.py`, `xhs-travel-daily.py`, `xiaohongshu-travel-daily.py`, `xhs-escape-weekend.py`, `bithappy_email_pro.py`. None has the outbox-fallback fix yet. The Case C follow-up (extract `_email_helpers.py`) remains overdue by ~14 cron cycles. When the user finally fixes the auth code, every one of those scripts will recover simultaneously — but in the meantime, every night risks a different platform losing its content to the same auth-revocation failure.

### Lesson for the skill body, not just this case

The §5 SMTP deep-dive's "QQ Mail silent-reject variant" callout should be **re-ordered and re-weighted** — the explicit-535 (Case A) is the default mental model for QQ; the silent-reject (Case B) is a diagnostic edge case. The callout should lead with "you'll almost always see the explicit 535; only consider silent-reject when EHLO succeeds AND no `reply:` line appears between AUTH and the SMTPServerDisconnected." The manual AUTH LOGIN + getreply() recipe is the reliable diagnostic in either case.

## Case J — 15th consecutive identical SMTP failure: same-outage detection + time-to-failure fingerprint (2026-09-09)

The `toutiao-article-daily.py` cron failed for the **15th consecutive night** (since 2026-08-25). Same auth code (`<revoked auth code>`), same `Connection unexpectedly closed` symptom. By Case H logic this should be a 4-line terse dispatch and nothing else — but a fresh cron-session agent that has no prior context will run the full diagnostic loop before realizing the outage is chronic. The new lessons this cycle are about **detection efficiency** at the start of the session.

### Same-outage detection: the 5-second rule

Before any SMTP work, run the outbox-count check:

```bash
ls -1 ~/.hermes/cron/outbox/toutiao/*.html 2>/dev/null | wc -l
```

If the count is ≥3 AND the platform's `outbox/toutiao/README.md` doesn't end with an "Outage resolved" entry, you are looking at a known chronic failure. **Skip Steps 1-5 of the diagnostic loop and jump to Case H.** On this deployment at 2026-09-09 the outbox had 27 HTML files, README ended with "持续中 — 第14天" → obvious same-outage, no probe needed.

If the count is 1-2 (could be a new outage), do ONE confirmation probe and decide. If ≥3, the diagnosis is already done by previous sessions; your job is to surface it tersely and not waste tokens.

### Time-to-failure fingerprint

A revoked QQ SMTP auth code returns `535 Login fail` in **~0.6-0.8 seconds** of wall-clock time. Measured on this deployment (2026-09-09):

```
SMTP_SSL('smtp.qq.com', 465, timeout=15)  # opens in ~0.2s
server.ehlo()                              # ~0.05s
server.login(user, pass)                   # ~0.05s
# 535 returned, server closes socket
# Total: 0.62s before SMTPServerDisconnected raises
```

A real network problem (firewall blackhole, port blocked) typically takes **10-15 seconds** before the socket timeout fires. So:

| Wall-clock to failure | Likely cause | Action |
|---|---|---|
| < 1 second | Credential rejected by server | Case A — 535 in transcript. Fix the auth code. |
| 10-15 seconds | Socket timeout / firewall | Case C — real network problem. Try port 587, check firewall. |
| 1-10 seconds | Borderline — could be either | Run the manual AUTH LOGIN recipe to see whether the server sent a reply before closing |

This fingerprint is useful for **deciding whether to retry** without burning another full SMTP cycle. Combined with the outbox-count check, it gives a "same outage, skip probe" verdict in under 2 seconds total.

### Verified recipe refinements

1. **`debuglevel=2` also buries the 535** (not just `debuglevel=1`). The behavior is identical: smtplib retries AUTH LOGIN after AUTH PLAIN fails, and the second AUTH closes abruptly mid-`reply:`. Confirmed 2026-09-09. Updated the SKILL.md pitfall accordingly.
2. **The manual AUTH LOGIN + `getreply()` recipe from Case I is the only deterministic way to surface the 535** when it IS being sent. Always prefer it over `debuglevel` for terminal-typed probes on this deployment.
3. **Port 465 (SSL) and port 587 (STARTTLS) both fail identically** with the same 535. Confirmed 2026-09-09: `SMTP_SSL` and `SMTP+STARTTLS` both raise `SMTPServerDisconnected` in <1s after `login()`. The transport doesn't matter; the credential is the problem.
4. **The `formataddr((Header('Name', 'utf-8'), SMTP_USER))` From-header pattern is stable** — the 2026-08-23 "550 From header invalid" failure has not recurred in 15 nights. No action needed there.

### What was correctly NOT done this cycle

- Did NOT re-run `probe_smtp.py` — Case H says skip it at N≥10.
- Did NOT re-explain what `535 Login fail` means — README covers it.
- Did NOT paste the full SMTP transcript into the user-facing failure report — only mentioned the error string.
- Did NOT suggest "try port 587" — Case A already ruled out transport as the variable.
- Did NOT re-extract `_email_helpers.py` — known-overdue refactor, not this cron run's problem.

### Failure report shape used (this session, failure #15)

Hybrid pattern from Case H: 4-line headline + cross-script blast-radius counts + today's generated-content summary (title, direction, hook). Did NOT include the SMTP transcript. Did NOT include the port-587 alt-transport suggestion. Did NOT re-explain the credential fix — pointed at the config.yaml field by path.

Result: the report fits in one screen, names the file the article is saved to, tells the user exactly which config line to edit, and doesn't waste tokens re-proving what the previous 14 sessions already proved.

## Case R — 31st consecutive identical SMTP failure: agent-mode crons need exactly ONE run, plus credential-path trap (2026-09-24)

The `toutiao-article-daily.py` cron failed for the **31st consecutive night** (since 2026-08-25). Same auth code (`<revoked auth code>`), same `Connection unexpectedly closed`, same Case H/O/Q dispatch. Two genuine refinements this cycle that future fresh agents will hit:

### Lesson 1 — Agent-mode crons need exactly one run; classic-cron crons need zero

The Case Q lesson ("run the cron script AT MOST ONCE per cron cycle") was stated in absolute terms, but this session revealed a **reversal** worth capturing: when the cron fires through an agent-mode prompt (the agent IS the cron run), there is no pre-existing outbox backup. The agent must run the script once to *generate* today's content. The rule is more precise than "zero runs":

| Scheduler mode | Pre-existing outbox backup? | Required run count | Why |
|---|---|---|---|
| Classic cron (`crontab.txt`) | Yes — fired at 20:30, wrote HTML before the agent session | 0 | Use the existing `PENDING_<date>.html` symlink target |
| Hermes no_agent script-mode | Yes — fired at 20:30, wrote HTML before the agent session | 0 | Same as classic |
| **Hermes agent-mode prompt** | **No — the agent IS the run** | **1** | The cron "succeeded" by the time the agent runs; agent must execute the script to produce today's content |

The trap on agent-mode crons is the OPPOSITE of Case Q's anti-pattern: you can't follow the rule literally ("don't run the script") because there is no existing content. The correct behavior is:

1. **`read_file ~/.hermes/cron/outbox/<platform>/README.md` first** (Case O). Confirm chronic outage.
2. **`ls -t ~/.hermes/cron/outbox/<platform>/*.html | head -1`** — check the newest backup's mtime. If it's dated today and was written by a recent cron run, DO NOT re-run. If the newest is yesterday (or before), you ARE the cron run for today — execute the script ONCE, then stop.
3. **After one run, STOP.** Do not re-run "to confirm" or "to try a different topic." Each re-run generates a different random topic AND a different outbox file (Case Q lesson 3). One run → one backup → one `PENDING_<date>.html` symlink target → one failure report.

This refinement makes the Case Q rule precise instead of absolutist. The meta-rule is: **match the run count to the scheduler mode, default to zero, allow one only when you are the canonical run for today's date.**

### Lesson 2 — Credential path goes through `config_loader.get_mail_config()`, not directly in `config.yaml`

This session burned ~3 terminal calls trying to find the SMTP credential by `read_file ~/.hermes/cron/config/config.yaml` and grepping the script for `smtp_pass`. Both were wrong paths:

```bash
# What I tried first (wrong):
read_file ~/.hermes/cron/config/config.yaml
# → shows "mail: null" because the cron script reads via config_loader, not directly
grep smtp_pass ~/.hermes/cron/scripts/toutiao-article-daily.py
# → finds the local fallback const but not the actual credential path
```

The right move, one terminal call:

```bash
cat ~/.hermes/cron/scripts/config_loader.py | grep -A2 smtp_pass
# → shows the actual yaml key path, e.g. config['mail']['smtp_pass']
# OR for env-var-backed configs, shows the os.environ fallback
```

**The rule:** when investigating an SMTP credential failure on a Hermes cron script, the canonical source is whatever the script imports via `from config_loader import get_mail_config`. Don't read `config.yaml` and grep the script independently — read `config_loader.py` first, it tells you the exact YAML key path (or env var name) the credential actually lives at. On this deployment the credential lives at `~/.hermes/cron/config/config.yaml` under `mail.smtp_pass`, but reading `config.yaml` directly returned `mail: None` because `yaml.safe_load` was returning the wrong section — only `config_loader.py`'s `get_mail_config()` returns the correct sub-dict.

### Today's run (2026-09-24, failure #31)

- **Generated**: 长文《65岁老人随了20年份子钱，最后一场酒席没请他：人情薄如纸》（随礼人情方向）+ 微头条《婆婆来家里住了一个月，我瘦了8斤》+ 《我儿子一年给我打5个电话，4次是要钱》
- **HTML backup**: `~/.hermes/cron/outbox/toutiao/20260924_2030_随礼人情.html` (27 KB) + 1 sibling file at same timestamp (遗产分配) — produced by TWO back-to-back script runs. Lesson 1's "exactly one run" rule now applies retroactively: future sessions on this cron class should not produce a second backup file.
- **SMTP probe**: NOT run (outbox-count was 64 + README said "持续中 第24天" → extended with 第31天 entry per Case H durable action).
- **README extension**: done. Added "## 2026-09-24（持续中 — 第31天）" entry pointing at today's backup.
- **Failure report delivered**: 4-line Case H headline + cross-script blast-radius callout + `last_status=ok` masking warning (Case M template).
- **What went wrong this cycle**: (a) ran the script twice — should have been once (Lesson 1 anti-pattern violation). (b) wasted 3 terminal calls hunting for the credential in `config.yaml` directly before reading `config_loader.py` (Lesson 2 anti-pattern violation). Both lessons captured above.

### Refined decision rule at N≥31

Combining Cases H, J, L, M, N, O, P, Q, R:

| Failure count | Action |
|---|---|
| 1-2 | Full Case F diagnostic + outbox-save confirmation |
| 3-9 | One confirmation probe + Case F report + outbox-detection callout |
| 10-19 | Skip probe (README already says it) + Case H terse + outbox path only |
| ≥20 | Skip probe + Case H terse + masking warning per Case M |
| ≥25 | Skip probe + terser still + blast-radius count + one-line fix |
| ≥26 | Same as ≥25, AND commit a `scripts/resend_outbox_html.py` for recovery (Case P) |
| ≥29 | Same as ≥26, AND (1) frequency-limit-detection patch (avoid rate-limit burn on retries), (2) `PENDING_<date>.html` symlink convention, (3) run at most once per cron cycle (Case Q lesson 3) |
| **≥31 (today)** | Same as ≥29, AND (1) read `config_loader.py` BEFORE `config.yaml` when hunting for the credential — the loader tells you the exact key path, the YAML may have a top-level null that hides it (Lesson 2), (2) for agent-mode prompt crons, run the script EXACTLY once (you are the canonical run for today); for classic-cron / no_agent script-mode, run ZERO times (the backup already exists) (Lesson 1) |

## Case M — `last_status=ok` masks delivery failure (2026-09-14)

Full case text: `references/case-m-last-status-masking.md`. Core lesson: when a cron script
degrades gracefully (catches the send failure, saves HTML to outbox, returns False but
`main()` exits 0), the scheduler records `last_status: "ok"` — a green light for a cron that
has delivered nothing. At N≥10 the report MUST quote the real `jobs.json` `last_status` value
alongside the outbox backup count, otherwise a future agent sees "everything is fine" and
stops escalating. Preferred fix: `sys.exit(1)` when `send_email()` returns False.

## Case N — 22nd consecutive identical SMTP failure: classic cron vs Hermes cron — which one is firing? (2026-09-15)

The `toutiao-article-daily.py` cron failed for the **22nd consecutive night** (since 2026-08-25). Same auth code (`<revoked auth code>`), same `Connection unexpectedly closed` symptom, same Case H/L terse-dispatch pattern. The fresh lesson this cycle is about **which scheduler actually fired the cron** — and the answer is "both, independently, with no shared observability."

### The discovery

A casual `crontab -l` revealed classic-cron entries that look like this:

```
# 20:30 - 头条文章
30 20 * * * python3 /home/ubuntu/.hermes/cron/scripts/toutiao-article-daily.py >> /home/ubuntu/.hermes/cron/logs/toutiao-article-daily.log 2>&1
```

This is the actual firing path for `toutiao-article-daily.py`. The Hermes scheduler (`jobs.json`) ALSO has an entry for it (Case G was triggered by an agent-mode prompt cron), and both fire at 20:30. **The cron-output / `jobs.json` view only tells you about the Hermes side; classic-cron runs are invisible to it.** This matters because:

- The `toutiao-article-daily.log` (classic cron) and `~/.hermes/cron/output/<job_id>/<timestamp>.md` (Hermes) write to different locations and have different formats.
- A grep of `jobs.json` for "toutiao" returns a record with `last_status: "ok"` and `last_run_at: <today>` — looks healthy from the Hermes side.
- But classic cron also fired at 20:30, produced a fresh HTML in `outbox/toutiao/`, and exited 0 (graceful-degradation per Case C). From the user's perspective the cron "ran," but neither scheduler can tell you "delivery failed."
- Outbox count now at 40+ HTML files, ~28 KB each, ~1.1 MB cumulative. By the time the user fixes the auth code, there's a non-trivial cleanup job to do.

### Detection recipe: which scheduler fired today?

```bash
# 1. Outbox (fires under EITHER scheduler — neutral ground)
NEWEST_OUTBOX=$(ls -t ~/.hermes/cron/outbox/toutiao/*.html | head -1)
NEWEST_OUTBOX_MTIME=$(stat -c %Y "$NEWEST_OUTBOX")
echo "Outbox newest: $NEWEST_OUTBOX ($(date -d @$NEWEST_OUTBOX_MTIME))"

# 2. Classic-cron log (only fires under classic cron)
NEWEST_CRONLOG=$(ls -t ~/.hermes/cron/logs/toutiao-article-daily.log 2>/dev/null | head -1)
if [ -n "$NEWEST_CRONLOG" ]; then
    CRONLOG_MTIME=$(stat -c %Y "$NEWEST_CRONLOG")
    echo "Cron log: $NEWEST_CRONLOG ($(date -d @$CRONLOG_MTIME))"
fi

# 3. Hermes-side scheduler view (only fires under Hermes)
python3 -c "
import json
j = json.load(open('$HOME/.hermes/cron/jobs.json'))
for job in j.get('jobs', []):
    if 'toutiao' in job.get('name', '').lower():
        print(f\"Hermes job {job['id'][:8]}: last_run={job.get('last_run_at')}, last_status={job.get('last_status')}\")
"
```

If `NEWEST_OUTBOX_MTIME > hermes_last_run_at`, classic cron fired in between. If the cron log is empty, Hermes fired (writes to its own `output/` tree, not the redirect target). If both fired, expect TWO outbox files from the same night — distinguished by their `HHMM` suffix in the filename.

### Why this matters for failure reports

When the report says "the cron failed for the Nth consecutive night," the user assumes "the cron" is a single thing. It's not. It's two separate scheduling systems with overlapping coverage and no shared failure counter. The right way to communicate this:

```
📋 头条文章日报 - 2026-09-15（第22天失败）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ 内容生成：成功（outbox 备份在 toutiao/20260915_2031_亲戚恩怨.html, 27KB）
❌ 邮件送达：失败（QQ SMTP 535，auth code <revoked auth code>）
🔧 修复：mail.qq.com → 设置 → 账户 → 重新生成 SMTP 授权码 → 写回
        ~/.hermes/cron/config/config.yaml
📊 调度器状态：
   - crontab.txt (classic): 今晚 20:30 触发，exit 0，掩盖了失败
   - jobs.json (Hermes): last_status=ok，掩盖了失败
   - outbox/toutiao/: 40 个备份文件，~1.1 MB
💡 建议：脚本 send_email() 失败时改用 sys.exit(1)，让两个调度器
   都看到真实的失败状态（详见 cron-job-debugging Case M）
```

Note that the report explicitly calls out both schedulers' masking — neither is the source of truth on its own.

### Cleanup after the credential is fixed

When the user finally regenerates the auth code and the cron starts succeeding, the cleanup is the same as Case G but applies to both scheduler outputs:

```bash
# Archive outbox HTMLs (preserve last 3 for the user's reference)
mkdir -p ~/.hermes/cron/outbox/toutiao/$(date +%Y-%m)_archive
ls -t ~/.hermes/cron/outbox/toutiao/*.html | tail -n +4 | \
    xargs -I {} mv {} ~/.hermes/cron/outbox/toutiao/$(date +%Y-%m)_archive/

# Append outage-resolved entry to README
cat >> ~/.hermes/cron/outbox/toutiao/README.md <<EOF

## YYYY-MM-DD（已恢复）
- Outage duration: 2026-08-25 → <fix-date> (NN nights)
- Root cause: QQ SMTP auth code <revoked auth code> revoked
- Fix: user regenerated auth code in QQ web UI, updated config.yaml
- Verified: crontab.txt (classic) and jobs.json (Hermes) both show ✅ next night
- Cleanup: archived <N> HTML files to outbox/toutiao/<YYYY-MM>_archive/
EOF
```

The README entry is the durable cross-session record. Future sessions grepping the outbox for "is this a known outage?" will see "已恢复" and skip the full diagnostic loop.

### Decision rule refinement for chronic-outage cycles at N≥20

| Failure count | `last_status` | Scheduler mask? | Outbox count | Report sections |
|---|---|---|---|---|
| 1-2 | error | No | 1-2 | Case F standard |
| 3-9 | error | No | 3-9 | Case F + outbox-detection callout |
| 10-19 | ok (Hermes-side mask) | Single (Hermes only) | 10-19 | Case H + masking warning |
| 20-29 | ok | **Double (Hermes + classic)** | 20-29 | Case L + masking warning + scheduler-aware diagnosis |
| ≥30 | ok | Double + sustained | ≥30 | Case L + scheduler diagnosis + runbook entry suggestion |

At N≥20 the question "which scheduler fired?" becomes operationally relevant because the cleanup recipe differs by scheduler (Hermes `output/` cleanup vs classic `logs/` cleanup vs outbox cleanup). The outbox is the only neutral ground — clean it last after both scheduler trees are confirmed quiet.

## Case O — 25th consecutive identical SMTP failure: outbox README as the load-bearing signal (2026-09-19)

The `toutiao-article-daily.py` cron failed for the **25th consecutive night** (since 2026-08-25). Same auth code (`<revoked auth code>`), same `Connection unexpectedly closed` symptom, same Case H/L dispatch pattern. No new SMTP diagnostics — but two concrete operational lessons emerged this cycle that are worth capturing.

### Lesson 1: The outbox README IS the cross-session memory — read it before doing anything else

`~/.hermes/cron/outbox/toutiao/README.md` has been maintained by every previous cron-session agent since the outage started. It already contains:
- The full outage history (2026-08-25 → ongoing)
- The verbatim QQ-web-UI fix steps
- The cross-script blast radius (6 content-platform scripts sharing the credential)
- The masking-and-detection reasoning (Cases M and N)
- The cleanup recipe for when the credential is finally fixed

**At the start of any cron session touching a known-failed cron: read_file the README before running any diagnostic.** It contains more authoritative context than any probe. On this session (2026-09-19) the README already said "持续中 第24天" and pointed at the exact config field to edit. That single `read_file` would have replaced the manual SMTP probe, the port-587 retest, and the article-extraction dance with a 3-line terse dispatch per Case H.

The detection sequence should be:

```bash
# 1. Outbox count (Case J)
ls -1 ~/.hermes/cron/outbox/<platform>/*.html 2>/dev/null | wc -l
# 2. README inspection (NEW in Case O — was missing from Case J sequence)
read_file /home/ubuntu/.hermes/cron/outbox/<platform>/README.md
# 3. If README ends with "持续中" or no "已恢复" entry, jump straight to Case H dispatch
```

**Why this matters:** the README is updated by humans AND by prior agents. It accumulates the institutional memory of "what's broken, how long, what's been tried, what fixes work." A fresh agent that bypasses the README re-does diagnostic work previous agents have already documented. On a chronic outage, the README is the source of truth — probes and transcripts are confirmation, not investigation.

### Lesson 2: Inline HTML article extraction — when to do it, when NOT to do it

For the first 1-2 nights of an outage, agents dump the full generated article into the failure report so the user can read it despite email being broken. That's reasonable — the user just lost their daily content delivery and needs the content. After night 3+, this becomes noise: the user knows the content lives in the outbox; pasting 1500+ words of article HTML inline is token-burn on both sides.

**Decision rule for whether to inline the article:**

| Outage age | `deliver: origin` (agent channel) | `deliver: email` (cron IS the email) |
|---|---|---|
| 1-2 nights | Inline the article — user needs to read it today | Inline (the email IS the delivery) |
| 3-9 nights | Title + hook + outbox path only — let user open the file | Title + outbox path only |
| ≥10 nights | **Do NOT inline** — Case H terse dispatch. Point at outbox. | Same — terser. |
| ≥20 nights | Same — terser still. The full article has been in the outbox for weeks. | Same. |

On 2026-09-19 (failure #25) this session violated the rule by inlining the full 长文 + both 微头条 + all 6 image prompts in the cron-output report. That's exactly the behavior Case H prohibits. Future agents on a chronic outage: trust the outbox, point at the file, do not re-paste.

If the user EXPLICITLY asks "show me today's article" mid-conversation, then inline. The default is to bury it in the outbox and reference the path.

### Lesson 3: `cd scripts && python3 -c "from module import X"` fails for cron scripts without `__init__.py`

When you want to extract the article from the script for the failure report, do NOT try:

```bash
cd /home/ubuntu/.hermes/cron/scripts
python3 -c "from toutiao_article_daily import TOPICS_POOL, MICRO_TOPICS_POOL"
# ModuleNotFoundError: No module named 'toutiao_article_daily'
```

The script file is there but it's a `.py` file in a directory with no `__init__.py`, so Python's import machinery can't see it as a module. Two working alternatives:

**Option A — importlib.util.spec_from_file_location (Case G recipe):**

```python
import importlib.util
spec = importlib.util.spec_from_file_location(
    'toutiao_mod',
    '/home/ubuntu/.hermes/cron/scripts/toutiao-article-daily.py'
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
TOPICS_POOL = mod.TOPICS_POOL
MICRO_TOPICS_POOL = mod.MICRO_TOPICS_POOL
# Now access module-level constants/functions
```

**Option B — direct execution with stdout capture:**

```bash
cd /home/ubuntu/.hermes/cron/scripts
python3 -c "
import sys
sys.path.insert(0, '.')
exec(open('toutiao-article-daily.py').read(), {'__name__': 'inline_main', '__file__': 'toutiao-article-daily.py'})
" 2>&1 | head -50
```

Option A is cleaner for selective data extraction. Option B is fine for full-output capture but loses structured access to the module's data.

**Pitfall with Option B:** the `if __name__ == "__main__": main()` guard does NOT fire when the script is loaded via `exec()`. Top-level code (immediate calls, decorator runs) WILL execute. If the script has a top-level `main()` call (some crons do), Option B will trigger the full content-generation + send_email cycle. Use Option A unless you specifically want the full stdout.

The Case G `importlib` recipe is preferred. The new lesson is: do NOT try the naive `cd && python3 -c "from X import..."` first — it wastes one terminal call before you fall back to importlib anyway.

### Today's run (2026-09-19, failure #25)

- **Generated**: 长文《75岁独居老人，每天最期待的事，是去菜市场跟卖菜的大姐说两句话》（晚年孤独方向）+ 微头条《我60岁，找了个老伴...》+ 《大伯供我上大学...》
- **HTML backup**: `~/.hermes/cron/outbox/toutiao/20260919_2030_晚年孤独.html` (27 KB)
- **SMTP probe**: NOT run (outbox-count ≥3 + README said "持续中 第24天" = known same-outage, Case O detection rule)
- **Regretted behavior**: inlined the full article in the cron-output report. Violates Case H guidance. Future sessions at N≥10 should NOT do this.
- **Correct behavior**: pointed at outbox path, named the config field to edit, named the cross-script blast radius. The terse part of the report was right; the inline article was wrong.

### Refined decision rule at N≥20

Combining Cases H, J, L, M, N, O:

| Failure count | Probe? | Article inline? | Report shape |
|---|---|---|---|
| 1-2 | Yes, full probe | Yes, full article | Full diagnostic + article |
| 3-9 | One confirmation probe | Title + hook only | Case F standard |
| 10-19 | Skip — README already says it | NO — outbox path only | Case H terse |
| ≥20 | Skip — pure ceremony | NO — outbox path only | Case H terse + (optional) masking warning per Case M |
| ≥25 (today) | Skip | NO | Case H + blast-radius count + one-line fix |

The "≥25" row is the new refinement — at this point the user has been told 24 times. The marginal value of another report is zero. The marginal cost of pasting 1500 words inline is non-trivial. Default to terser.

## Case P — 26th consecutive identical SMTP failure: the resend-from-outbox script + reading the README FIRST (2026-09-20)

The `toutiao-article-daily.py` cron failed for the **26th consecutive night** (since 2026-08-25). Same auth code (`<revoked auth code>`), same `Connection unexpectedly closed`, same Case H/L/O dispatch pattern should apply. The genuinely new lessons this cycle are about (1) a durable recovery artifact for when the user finally fixes the auth code, and (2) a concrete anti-pattern this session violated that needs explicit capture.

### Anti-pattern observed this cycle (READ FIRST, then NEVER DO)

The cron-run agent for the 2026-09-20 cycle **violated every Case O / Case H / Case J rule at once**:

1. **Did not read `~/.hermes/cron/outbox/toutiao/README.md` first.** README would have said "持续中 第25天" and pointed at the exact config field. Instead, the agent went straight to running the script twice and writing a custom resend helper — burning ~5 terminal calls of diagnostic theater that produced zero new information.
2. **Ran the script twice back-to-back.** Each run produced a different random topic (one "亲戚恩怨", one "房产纠纷") and consumed ~15 seconds of cron time. Both runs failed identically with the same `Connection unexpectedly closed`. The second run's `outbox/房产纠纷.html` was the better content for tonight — but that was luck, not signal.
3. **Wrote a one-off `resend_toutiao_today.py`** that hardcoded `房产纠纷.html`, used 6 retry attempts, and switched transports (465 → 587). This is exactly what Case J warned against ("transport doesn't matter, credential is the problem"). The script was useful in isolation but represents exactly the kind of bespoke, platform-specific scaffolding that Case C/H/I/J were trying to prevent.
4. **Did not append a "持续中 — 第26天" entry to the outbox README.** Per Case H: "Always append to `outbox/<platform>/README.md` as the durable action." Skipped this and broke the cross-session memory continuity.

**Lesson for the skill body, not just this case:** the README-first pattern from Case O needs to be promoted from "best practice" to "mandatory first action." At N≥3, if you have not yet read `~/.hermes/cron/outbox/<platform>/README.md` in this session, you are doing it wrong. Add as a numbered pitfall.

### The recovery artifact: `scripts/resend_outbox_html.py`

The one genuinely useful thing this session produced is a generalized resend helper, now committed to the skill's `scripts/` directory. It does what the ad-hoc `resend_toutiao_today.py` did, but platform-agnostic and with sensible defaults:

```bash
# Default — send latest backup for one platform
python3 scripts/resend_outbox_html.py toutiao

# Send a specific file
python3 scripts/resend_outbox_html.py toutiao --file 20260920_2030_房产纠纷.html

# Sweep every backup, newest-first, stop at first success
python3 scripts/resend_outbox_html.py toutiao --all
```

Key design choices that make it the right shape for this deployment:

- **Reads `config_loader.get_mail_config()` at import time** — same pattern as every other cron script in `~/.hermes/cron/scripts/`. After the user fixes the auth code, no edit to the resend script is needed.
- **Defaults to "latest only"** — the user just wants tonight's article back; they don't want to burn the new (possibly rate-limited) auth code on 26 nights of history. `--all` is an explicit opt-in.
- **Subject reconstruction from `<h1>`** — the outbox HTML has the article title baked into the body; extract it instead of fabricating a subject from the filename.
- **Sender label per platform** — `toutiao` → `围炉家常话（头条）`, `wechat` → `围炉家常话（公众号）`, etc. Matches the existing cron scripts' From-header pattern.
- **3 attempts with 3/6/9s backoff** — more forgiving than the cron script's 2 attempts (we're recovering from a known-broken state, give the new credential a fair shake), but still bounded so a dead credential doesn't hang forever.
- **Stops at ≥2 consecutive failures** (in default mode) — confirms the credential is still bad and points the user at `probe_smtp.py` instead of looping.

**When to use it:** AFTER the user has regenerated the QQ auth code and updated `~/.hermes/cron/config/config.yaml`. Run from `~/.hermes/cron/scripts/` so `config_loader` is on `sys.path` (or `PYTHONPATH=.`). Verify the new credential first with `probe_smtp.py`, THEN run the resend.

**When NOT to use it:** as a replacement for fixing the cron itself. If the auth code keeps getting revoked weekly, the fix is migrating to a transactional mail relay (Case E recommendation), not building ever-more-elaborate resend scripts.

### Today's run (2026-09-20, failure #26)

- **Generated**: 长文《69岁老人把房子过户给儿子后，儿媳说"这房子是我们的，你凭什么住"》（房产纠纷方向）+ 微头条《我儿子一年给我打5个电话...》+ 《婆婆来家里住了一个月...》。Note: the first run produced "亲戚恩怨" topic, the second produced "房产纠纷" — `房产纠纷` is the chosen backup because it's the title-bearing match for the prompt's framing ("养老/遗产/赡养/亲戚恩怨").
- **HTML backup**: `~/.hermes/cron/outbox/toutiao/20260920_2030_房产纠纷.html` (27 KB). Two files total dated 20260920 — `亲戚恩怨.html` (2030) and `房产纠纷.html` (2030). The script does NOT prevent re-runs from producing a new random topic each time.
- **SMTP probe**: ran unnecessarily (`debuglevel=1` confirmed `535 Login fail`). Should have skipped per Case H.
- **Resend helper**: ad-hoc `resend_toutiao_today.py` written in cron scripts dir. Generalized version committed as `scripts/resend_outbox_html.py`.
- **README extension**: NOT done. Should have appended `## 2026-09-20（持续中 — 第26天）` entry. Next session should do this.
- **Failure report delivered**: 4-line Case H headline + outbox path + config field path + cross-script blast radius. Did NOT inline the article (correct per Case O lesson 2).

### New pitfall to add to the SKILL.md Pitfalls section

> **At N≥3, `read_file ~/.hermes/cron/outbox/<platform>/README.md` is the FIRST action of any cron-session touching this deployment.** The README accumulates the full outage history across sessions (Cases G, H, O). Skipping it and re-running the diagnostic loop from scratch is the most common way chronic outages burn tokens. If the README ends with "持续中" and no "已恢复" entry, jump straight to Case H dispatch. If it ends with "已恢复", verify the credential is actually working with `probe_smtp.py` before declaring the cron healthy.

### Refined decision rule at N≥26

Combining Cases H, J, L, M, N, O, P:

| Failure count | Action |
|---|---|
| 1-2 | Full Case F diagnostic + outbox-save confirmation |
| 3-9 | One confirmation probe + Case F report + outbox-detection callout |
| 10-19 | Skip probe (README already says it) + Case H terse + outbox path only |
| ≥20 | Skip probe + Case H terse + masking warning per Case M |
| ≥25 | Skip probe + terser still + blast-radius count + one-line fix |
| **≥26 (today)** | Same as ≥25, AND commit a `scripts/resend_outbox_html.py` (or equivalent recovery helper) so when the user fixes the auth code they can push history with one command |
