# Case M — `last_status=ok` masks delivery failure (2026-09-14, failure #21)

Full case text moved out of SKILL.md on 2026-10-20 to keep SKILL.md under the 100 KB
skill-size limit. Load this file when you need the full narrative.

---

## Case M — 21st consecutive identical SMTP failure: `last_status=ok` masks delivery failure (2026-09-14)

The `toutiao-article-daily.py` cron failed for the **21st consecutive night** (since 2026-08-25). Same auth code (`<revoked auth code>`), same `Connection unexpectedly closed` symptom, same outbox-fallback HTML saved to `~/.hermes/cron/outbox/toutiao/`. The Case L + Case J dispatch pattern worked perfectly: outbox-count was 38, README ended with "持续中 — 第20天", no probe needed, terse report delivered. **The genuinely new lesson this cycle is about a structural blind spot the skill has not previously surfaced: the scheduler's health view (`jobs.json` `last_status`) lies when the script exits 0 after a graceful-degradation fallback.**

### The `last_status=ok` cron-masking pitfall

When `toutiao-article-daily.py`'s `send_email()` fails, the catch block saves the HTML to outbox and `return False, "..."` — the `main()` function logs the failure message and exits 0. The Hermes scheduler reads exit code 0 as success and sets `last_status: "ok"` in `jobs.json`. The user inspecting `jobs.json` sees:

```json
{
  "id": "406529dd5f2e",
  "name": "头条号文章",
  "last_run_at": "2026-09-13T20:32:15.500940+08:00",
  "last_status": "ok",
  "repeat": { "completed": 109 }
}
```

A green `last_status: "ok"` for a cron that has not actually delivered anything in 21 nights. **The scheduler's view of cron health is decoupled from delivery success** when the script has a graceful-degradation fallback (which is the right design pattern for content-generation crons — see Case C/F). This is a classic observability gap: the failure has been logged, the content has been preserved, the report has been delivered, but the system's "did the cron work?" indicator says yes when the answer is no.

**Why this is dangerous:** the `last_status` field is what shows up in `hermes cron list`, in monitoring dashboards, and in any "is this cron healthy?" check an automated agent runs. A 21-night email-delivery outage with `last_status: "ok"` across all that time means a future agent that queries cron health will see "everything is fine, no action needed" — and may stop reporting, stop appending to the outbox README, or fail to escalate.

### Two correct fixes (pick whichever fits the deployment)

**Fix 1 (preferred for content crons): make `send_email()` failure propagate to a non-zero exit code.** The catch block's `return False, ...` should bubble up through `main()` and become `sys.exit(1)` (or `raise SystemExit(1)`):

```python
# In send_email():
if not success:
    sys.stderr.write(f"❌ 发送失败：{msg}\n")
    return False, msg   # preserves current behavior for any caller

# In main(), at the bottom:
success, msg = send_email(html_content, plain_text, topic, micro_articles)
if not success:
    sys.stderr.write(f"\n❌ 发送失败：{msg}\n")
    sys.exit(1)         # <-- THIS is what fixes the masking
print(f"\n✅ 邮件发送成功！")
return html_content, plain_text, topic, micro_articles
```

**Important:** the HTML-to-outbox save MUST happen *before* the `sys.exit(1)`, so the graceful-degradation content preservation still works. The outbox backup is independent of the exit code — save first, then exit non-zero.

**Fix 2 (preferred if you cannot modify the script): add an external health check.** A separate cron or monitoring check that runs the script in "report-only" mode and reports when `last_status: "ok"` doesn't match the actual outbox state. Concretely: a daily 21:00 cron that does

```bash
outbox_count=$(ls -1 ~/.hermes/cron/outbox/toutiao/*.html 2>/dev/null | wc -l)
last_status=$(python3 -c "import json; print(json.load(open('$HOME/.hermes/cron/jobs.json'))['jobs'][<job_idx>]['last_status'])")
if [ "$outbox_count" -ge 3 ] && [ "$last_status" = "ok" ]; then
    echo "⚠️ 头条 cron last_status=ok but outbox has $outbox_count files — likely masked failure"
fi
```

This is the lower-friction option — no script surgery — but it requires adding a second cron and the user to wire it up.

### Detection recipe for a fresh agent

When you encounter `last_status: "ok"` on a content cron, **don't trust it.** Cross-check against the outbox:

```bash
# What the scheduler says:
python3 -c "import json; j=json.load(open('$HOME/.hermes/cron/jobs.json')); print([x for x in j['jobs'] if 'toutiao' in x.get('name','')][0]['last_status'])"

# What the outbox says actually happened:
ls -1 ~/.hermes/cron/outbox/toutiao/*.html 2>/dev/null | wc -l
```

If `last_status: "ok"` but outbox has ≥3 files dated after the last successful run → masked failure. Treat as `last_status: "error"` for any escalation logic. Don't tell the user "the cron is healthy, no action needed" without checking this.

### This skill's pitfall list gets a new entry

Add to the Pitfalls section:

- **`last_status: "ok"` is misleading when graceful-degradation fallback is in place.** A content cron that fails email delivery, saves to outbox, and exits 0 will show `last_status: "ok"` in `jobs.json`. Always cross-check `last_status` against `ls -1 ~/.hermes/cron/outbox/<platform>/*.html | wc -l` — if outbox grew but `last_status` is "ok", the failure was masked. Either modify the script to `sys.exit(1)` on send failure (preferred), or add an external health check that reconciles scheduler view vs outbox state.

- **Sleep-retry escalation is a distinct anti-pattern on chronic-outage crons (2026-10-07, Case S).** A revoked auth code fails token-state, not transient-state. QQ's `535 Login fail` message includes "login frequency limited" as a generic catch-all phrase — it is NOT a per-attempt rate limit. After the FIRST probe returns `535 Login fail`, no amount of `time.sleep(N)` between probes will clear it. If you find yourself reaching for `time.sleep(35)` / `time.sleep(90)` / `time.sleep(300)` between probes on a documented-chronic-outage cron, STOP — that's a Case O anti-pattern plus a new sleep-compound error. Kill any backgrounded `time.sleep()` process, deliver Case H dispatch immediately, append to outbox README. Total budget for a chronic-outage cron cycle is **3 README-check calls + 1 README-append = 4 calls**; everything above that is wasted. See Case S in `references/toutiao-cron-outage-2026-09.md`.

- **`read_file ~/.hermes/cron/outbox/<platform>/README.md` is the FIRST action at N≥3, not the third or fourth.** The outbox README is the load-bearing cross-session memory (Cases O, P). Skipping it and re-running the diagnostic loop from scratch burns tokens re-proving what previous sessions already documented. If the README ends with "持续中" and no "已恢复" entry, jump straight to Case H dispatch. If it ends with "已恢复", verify the credential with `probe_smtp.py` before declaring the cron healthy — the README could be lying if the auth code was rotated again after the "已恢复" entry was written.

- **Don't write bespoke per-platform resend scripts when the user fixes the credential.** The skill ships `scripts/resend_outbox_html.py` for exactly this purpose — it's platform-agnostic, has a sensible "latest only" default, reads the same `config_loader.get_mail_config()` the cron scripts use, and stops at the first sign of trouble. Writing a custom `resend_toutiao_today.py` (Case P anti-pattern) duplicates the helper and locks it to one platform. Use the skill's script; extend it only if a platform genuinely needs different behavior.

- **Running the cron script multiple times in a row produces multiple random topics, not "retry until success."** Some cron scripts (e.g. `toutiao-article-daily.py`) randomly select a topic at module-import time. Re-running the script does not retry delivery — it generates fresh content with a fresh random topic, then fails identically on the same SMTP credential. The outbox accumulates multiple files per night, each with a different direction. Pick one backup file as "tonight's article" (the user-facing prompt usually hints at which — e.g. 养老/遗产/赡养/亲戚恩怨方向), do not present all of them as candidates. Case P observed 2 files dated 20260920 with different topics from the same cron run window.

- **When the outbox has multiple HTMLs for the same night, choose by filename direction first, then by HHMM.** The cron usually fires at 20:30 and runs once; if the cron-session-handler re-invokes the script (or the user does), a second file lands at 20:31 or later with a different random topic. Heuristic for picking "tonight's article" in the failure report: (1) prefer the direction named in the user's prompt (e.g. '遗产' > '赡养' if the prompt says 遗产), (2) on tie, prefer the earlier HHMM (the cron was scheduled for that time and the second run is the surprise), (3) only mention the other file as "备选" if the chosen one mis-matches the prompt direction. Found 2 files for 20260921 (`2030_遗产分配.html` and `2031_遗产分配.html`) — both happened to be 遗产分配 so the heuristic wasn't tested on a topic-flip night, but the rule still applies for future failures.

- **At N≥10 the failure report IS the troubleshooting report; budget its length accordingly.** A chronic-outage cron at N≥10 produces one report per night that serves as both the user-facing notification AND the only debugging signal for fresh agents next session. If the report inlines 1500 words of generated article + 6 image prompts + cross-script blast radius + masking diagnosis + fix instructions, it consumes both user attention and the next agent's `read_file` budget when they re-read the outbox README (Case O). Case H says 4 lines; at N≥25 (failure #26 case study in Case P) terse + blast radius was the right shape; at N≥28 (today) the entire report should fit on one screen — outbox path, count, config field, one-line fix. The detailed report shape exists to keep the agent honest about what it did; the user-facing report should be the absolute minimum that lets them fix it. Diff against an actual reporter too: extra sections like "verification commands the user can copy-paste" are useful at N=1–5 and pure noise at N≥25.

- **Port 465 fingerprint has shifted: now TCP-level blackhole, not fast 535 (2026-10-08, Case T).** The historical Case J "time-to-failure fingerprint" said <1s = credential rejection, 10–15s = network. As of failure #45, `socket.create_connection(('smtp.qq.com', 465), timeout=15)` now hangs and times out at 15 seconds with no banner received — but port 587 still returns 220 + 535 in <1s. Both still indicate the same revoked-auth-code state; the IP has been escalated from "AUTH-level reject" to "TCP-level blackhole." **Detection path is now port-587-first** if 465 times out — don't conclude "network problem" from a 465 timeout alone, verify with 587 AUTH PLAIN. The user-fix is unchanged.

- **The "fresh agent" anti-pattern: ignoring the skill itself and re-running the diagnostic loop from scratch (2026-09-22, failure #28).** This skill has Cases A through P documenting 27+ nights of identical failure on `toutiao-article-daily.py` for QQ SMTP auth code `<revoked auth code>`. A fresh cron-session agent loaded this skill, saw the body, and STILL:
  (1) ran `python3 ~/.hermes/cron/scripts/toutiao-article-daily.py` directly three times (each run produced a different random topic — three outbox files for the same night, none of them the "right" one per the user's prompt direction);
  (2) ran manual SMTP probes with `smtplib.SMTP_SSL` + `debuglevel=1`, then with a `socket.create_connection` + `ctx = ssl.create_default_context()` recipe, then a port-587 STARTTLS attempt — burning ~6 terminal calls and producing transcripts already documented in Case I;
  (3) never ran `ls -1 ~/.hermes/cron/outbox/toutiao/*.html | wc -l` to detect the chronic outage (would have shown ~50 files instantly);
  (4) never `read_file ~/.hermes/cron/outbox/toutiao/README.md` (Case O's "FIRST action");
  (5) delivered a verbose failure report with generated content title + hook + 2 微头条 headlines + 6 image prompts inline (Case O lesson 2: NO at N≥10);
  (6) never appended a "## YYYY-MM-DD（持续中 — 第N天）" entry to the outbox README (Case H durable action).

  **The fix is structural, not diagnostic:** when you load this skill and the cron is `toutiao-article-daily.py` (or any of the documented chronic-outage crons), the FIRST THREE actions are MANDATORY and UNCONDITIONAL — no "but maybe this time it's different," no "let me confirm with a probe":
  1. `ls -1 ~/.hermes/cron/outbox/<platform>/*.html 2>/dev/null | wc -l` — if ≥3, chronic outage.
  2. `read_file ~/.hermes/cron/outbox/<platform>/README.md` — if it ends with "持续中" and no "已恢复", the diagnosis is done; the user just hasn't fixed it.
  3. `hermes cron list --all` (or read `~/.hermes/cron/jobs.json`) — confirm `last_status` is masked per Case M, then deliver Case H dispatch.

  **Skip steps 1-5 of the §Diagnostic loop entirely** if the outbox count + README confirms a chronic outage. The probes and transcript dumps exist to teach the diagnostic technique; they are NOT required every night on a documented recurring failure. Reading the skill body is necessary but not sufficient — the agent must also FOLLOW the decision rules it documents. Add to the Case O "load-bearing signal" callout: if you find yourself about to run a probe, first ask "is this probe adding new information?" If the answer is "no, README/Case I already documented this exact 535 transcript," delete the probe.



- **Generated**: 长文《67岁老人被三个儿子轮流养老，每家住四个月，第三家说"住够了"》（赡养义务方向）+ 微头条《我65岁，存款30万...不够养老》+ 《我儿子一年给我打5个电话...喝多了》
- **HTML backup**: `~/.hermes/cron/outbox/toutiao/20260914_2031_赡养义务.html` (27 KB). Note: TWO files were written at 2030 and 2031 because the cron agent ran the script twice (once via the cron-scheduled prompt, once via direct invocation from this session — same content, different timestamps).
- **SMTP probe**: NOT run (outbox-count was 38 + README said "持续中 第20天" = known same-outage, Case J detection rule applied).
- **`jobs.json` masking confirmed**: `last_status: "ok"`, `repeat.completed: 109`, `last_delivery_error: "Feishu send failed: [99992402] field validation failed"` (the Feishu error is a separate channel, not email — but illustrates that the scheduler is reporting partial info correctly while the email channel's complete failure is invisible at the `last_status` level).
- **Failure report delivered**: Case L template (generate / deliver / fix) + cross-script blast-radius callout + new `last_status` masking warning. First report to explicitly flag the `last_status` discrepancy.

### Updated report template for chronic-outage + masked-failure cycles

When both conditions hold (chronic outage ≥10 nights AND `last_status` is masked), the report should include a **section flagging the masking** with the actual `jobs.json` `last_status` value quoted, plus the outbox count. This is the only way the user (or a future fresh agent) learns that the scheduler's green light is misleading.

Suggested template additions to the Case L 3-section report:

```
4. ⚠️ 监控盲区提示：cron jobs.json 显示 last_status=ok（第N天连续），
   但 outbox/toutiao/ 实际有 M 个备份文件。脚本优雅降级保存HTML后
   exit 0，导致调度器看不到失败。建议在 send_email() 失败时
   sys.exit(1)，让 last_status 真实反映送达状态。
```

Skip this section only at N<5 (the masking hasn't been going on long enough to be worth a section), or when the script has been patched to `sys.exit(1)` on send failure.

### Decision rule update

| Failure count | `last_status` value | Report sections |
|---|---|---|
| 1-2 | error (likely) | Case F standard |
| 3-9 | error | Case F + outbox-detection callout |
| 10-19 | ok (now masked) | Case H + masking warning |
| ≥20 | ok (definitely masked) | Case L + masking warning + cross-script blast radius |

The "report `last_status` mismatch" check is **mandatory** at N≥10 — that's when the masking has been going on long enough to mislead any fresh agent that doesn't know about it.

```
