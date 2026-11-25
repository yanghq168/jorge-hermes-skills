# Pitfalls 案例叙事归档（从 SKILL.md 下沉）

本文件保存 `cron-job-debugging/SKILL.md` 的 `## Pitfalls` 一节中因体积超限而移出的**完整案例叙事**（原始逐字内容，未删改）。

SKILL.md 正文只保留**可执行规则**（每条 Pitfall 的粗体标题 + 关键动作），叙事细节与完整转录在本文件按 `§标签` 索引。

规则：**SKILL.md 必须 ≤ 75k 字符**（`skill_manage` 上限 100,000，接近上限时任何追加都会被拒 → 反复重试 → 会话迭代预算耗尽 → cron 报告会话被 `max_iterations_reached` 掐断）。

## 🔧 压缩 SKILL.md 的可执行流程（2026-11-25 实测，90,840 → 71,862 字符）

当 SKILL.md 逼近上限时，**先压缩、再追加**，顺序反了就会被拒。
这个流程是**一次性**做完的（写脚本改文件，不要手敲 20 次）：

1. **量现状**：`python3 -c "print(len(open('SKILL.md',encoding='utf-8').read()))"`,
   并量出最大的一节（通常是 `## Pitfalls`）占比 ——
   实测 `## Pitfalls` 占 **56,182 / 90,840 = 62%**。
2. **定位可下沉的块**：`## Pitfalls` 下的顶层条目（以 `- **` 开头的行）按长度排序，
   找出 > 900 字符的条目 —— 实测 **20 条**合计 31,963 字符。
3. **逐条改写成三行式**（**规则留在正文，叙事下沉**）：
   ```
   - **<原粗体标题>**
     - <前 ~420 字符的可执行规则>
     - 📄 完整案例叙事已下沉 → `references/pitfalls-compression-archive.md`（§<标签>）
   ```
   ⚠️ **标题必须逐字保留**（它是检索锚点）—— 只压缩正文，不动标题。
4. **归档原文**：把每条被下沉的**逐字原文**追加到本文件，用 `## §<标签>` 分节，
   标签取自标题。**归档文件必须追加写入，不能覆盖**（它也是日志性质的文件）。
5. **⚠️ 压缩脚本本身有个陷阱：拼接后要把下一个 `## ` 标题保持在独立行。**
   实测踩中：把最后一条的归档指针行和 `## Cross-reference` 粘在了同一行
   （`…（§Tag）## Cross-reference`）⇒ 该标题不再被 markdown 识别，
   `skill_view` 里整节内容塌进上一节。**修法**：拼接时在指针行后补 `\n\n`，
   改完必须核对 `## ` 标题清单：
   ```python
   heads = [l for l in new.splitlines() if l.startswith("## ")]
   print(len(heads)); print("\n".join(heads))
   ```
6. **改完立刻回读验证**：frontmatter 完整、无乱码（`�` 计数为 0）、
   每个被下沉的标题仍能在 SKILL.md 里搜到、**最终字符数 ≤ 75k**。
7. **顺带补两件事**（否则下次还会撞）：把新归档文件登记进 SKILL.md 的
   「相关 reference」列表（一条指针即可），并 bump frontmatter 的 `version:`。

**压缩后的实测结果**：90,840 → **71,862** 字符（省 19,121），归档文件 34,412 字符，
`## ` 标题从 6 个变回 7 个（`## Cross-reference` 恢复独立），乱码 0。

---

## §2026-11-23-THIS-skill-file-s

**🔴 2026-11-23: THIS skill file's own size is a live hazard — keep it under ~75k chars.**

原始 SKILL.md 条目（逐字）：

**🔴 2026-11-23: THIS skill file's own size is a live hazard — keep it under ~75k chars.**
  On 2026-11-22 the reporting agent burned its entire iteration budget on
  `skill_manage` retries because `SKILL.md content is 100,314 characters
  (limit: 100,000)`. The session ended with `Turn ended:
  reason=max_iterations_reached(60/60)` — **the report was marked
  `last_status=error` even though the article had been generated and
  delivered successfully.** Root cause chain:
  1. `skill_manage` refuses writes to a SKILL.md at/over 100,000 chars.
  2. A near-limit skill (this one was **96,668 chars**) leaves no headroom, so
     any append fails and the agent retries the same call repeatedly.
  3. Each retry costs an iteration. The agent's final response is then never
     finalized ⇒ the scheduler records `error` and puts the **report body**
     into `last_error` (instead of an exception summary).
  - **Symptom to recognize**: `jobs.json` shows `last_status: error` but
    `last_error` starts with `RuntimeError: ## 📰 …` (a markdown heading)
    rather than a traceback ⇒ **the agent session ran out of budget, not the
    script**. Check `~/.hermes/logs/agent.log` for
    `Turn ended: reason=max_iterations_reached`.
  - **Prevention**: keep this SKILL.md **≤ 75k chars**. Measure with
    `python3 -c "print(len(open('SKILL.md',encoding='utf-8').read()))"`.
    The `## Pitfalls` section is the usual offender — long case narratives
    (measured 2026-11-23: **62,010 chars = 64% of the whole file**).
  - **The fix when it's over**: move the long narrative blocks into
    `references/case-log-chronic-outage.md` (or a new `references/` file) and
    leave a **one-line rule + a pointer** in SKILL.md. Keep the *actionable*
    rule inline; move the *narrative* down. Don't delete history — the
    reference files are the durable record.
  - **Corollary for any skill, not just this one**: if a `skill_manage` write
    is rejected for size, **do not retry the same write**. Shrink the target
    file first, or write the detail to a `references/` support file instead
    (`skill_manage(action='write_file', file_path='references/...')`).

---

## §Fixing-a-no-agent-job-s-path

**⚠️ Fixing a `no_agent` job's path can UNCOVER duplicate scheduling.**

原始 SKILL.md 条目（逐字）：

**⚠️ Fixing a `no_agent` job's path can UNCOVER duplicate scheduling.** A
  job that never ran was harmless; once it runs, it may collide with classic
  crontab. Check `crontab -l` against `jobs.json` schedules for the same
  script BEFORE declaring victory. Two distinct failure modes to separate:
  - *agent-mode* + classic cron on the same script ⇒ usually fine (the agent
    audits rather than regenerates; check artifact counts to confirm).
  - *no_agent* + classic cron on the same script ⇒ **real double-fire** — two
    products, two emails, two pushes. On 2026-11-18 this applied to
    `wechat-article-daily.py` (classic 22:00 vs Hermes 07:00) and
    `skill-backup.sh` (classic 03:00 vs Hermes 03:00 — same minute).
  **Back up the crontab before editing it** (`crontab -l > /tmp/crontab_backup_$(date +%Y%m%d_%H%M).txt`)
  and ask the user which scheduler to keep rather than deleting unilaterally —
  the classic cron entries also drive scripts with NO Hermes job.

---

## §Before-any-SMTP-work-check-t

**Before any SMTP work, check the outbox age to detect a same-outage repeat.**

原始 SKILL.md 条目（逐字）：

**Before any SMTP work, check the outbox age to detect a same-outage repeat.**
    `ls -1 ~/.hermes/cron/outbox/<platform>/*.html 2>/dev/null | wc -l` is the fastest "is this the same SMTP outage I've already diagnosed?" check.
    If the count is ≥3 AND the platform's `outbox/<platform>/README.md` has no
    "Outage resolved" entry, you are looking at a known chronic failure —
    skip Steps 1-5 of the diagnostic loop and jump to the Case H terse-report
    pattern (outbox path + one-line fix). Saves the user from another 30s of
    SMTP probe output for a problem they've been ignoring for ≥3 nights.
    Pair with the **time-to-failure fingerprint**: a revoked QQ SMTP auth
    code returns 535 in ~0.6-0.8 seconds (measured 2026-09-09: 0.62s wall
    clock from `SMTP_SSL()` open to the `SMTPServerDisconnected`). If your
    probe completes in under 1s and prints `Connection unexpectedly closed`,
    it's a credential problem, not a network one — skip the port-587 retry
    and go straight to the user-fix instructions. At N≥20 the probe is purely
    ceremonial; one line of AUTH LOGIN output (the `password -> 535:` line)
    is the entire diagnostic value, the rest is noise.
    The full 8-step diagnostic sequence for a *fresh* agent on a chronic outage
    (outbox count → README → probe → port sweep → DNS → terse report → README
    extension) lives in `references/case-log-chronic-outage.md` Case J — read it
    there, not here.

---

## §Three-outbox-resident-artifa

**Three outbox-resident artifact types, three purposes (Case V, 2026-10-12).**

原始 SKILL.md 条目（逐字）：

**Three outbox-resident artifact types, three purposes (Case V, 2026-10-12).** Chronic-outage crons should maintain three sibling artifacts under `outbox/<platform>/`: (1) the rendered `YYYYMMDD_HHMM_<direction>.html` (full content), (2) the `PENDING_<date>.html` symlink to one canonical content file, (3) a `STANDBY_<date>.txt` plain-text dispatch metadata file (title / direction / HTML path / ≤200-char reason). The STANDBY file is for crons whose primary delivery channel is broken AND whose report rides a secondary channel (e.g. Feishu / Lark / Slack) that doesn't render file paths — that secondary consumer can quote the STANDBY as a low-bandwidth pickup notification. Worked implementation lives in `toutiao-article-daily.py::main()` (block added 2026-10-12 — preserve it on future edits). Don't move the STANDBY write out of the `if not success:` branch, and don't store STANDBY files in `~/.hermes/cron/output/<job_id>/` (that's scheduler log territory, see §5/Case C). Full lessons + porting guide in `references/toutiao-cron-outage-2026-09.md` Case V.

---

## §Do-the-README-append-EARLY-n

**🔴 Do the README append EARLY, not last (2026-11-05, a session got cut off).**

原始 SKILL.md 条目（逐字）：

**🔴 Do the README append EARLY, not last (2026-11-05, a session got cut off).**
  A cron session hit its tool-call limit *after* the content fixes and verification
  but *before* the README append and the outbox prune — the two terminal actions.
  The fixes landed in the source (good), but the cross-session outage log skipped
  a night, so the next session's "第N天" counter was wrong and the README had no
  record of the linter repair.
  **Rule: for a chronic-outage cron, append the README entry and prune the outbox
  EARLY in the session** (right after confirming delivery), not as cleanup at the end.
  The audit/fix work is the part that can be cut off; the persistence step must not be.
  If you suspect you're near a limit, write the README entry first and treat any
  remaining analysis as a bonus.
  Also note the README heading count is the verification: `grep -c "^## "` must go up
  by exactly 1 per session — if it didn't, the entry was never written.
  - **🔴 「读-改-写」追加 README 会截断日志 —— `read_file` 默认只读前 500 行且静默截断，
    `write_file` 全量覆盖 ⇒ 一次追加就把 14 段历史日志删掉了（2026-11-16 实测，822 行 → 513 行）。**
    - **规则：只增不减的日志文件（outbox README / `topic_history.json` / `jobs.json`）只追加，绝不读改写。**
      用 `cat >> file <<'EOF'` 或 `Path(p).open('a')`。若非要用 `read_file`，
      必须显式给足 `limit` 并**比较 `r['total_lines']`**——不比较就会静默截断。
    - **恢复方法：`~/.hermes/state.db` 的 `messages.tool_calls` 保存了每次工具调用的完整入参**，
      逐段还原、重建、去重即可重建被截断的 README。
    - **预防清单**：追加后必须 ① `grep -c "^## "` 比对追加前（须 **+1**）② `grep -n "^## " | tail -3`
      看最后三个标题是否连续 ③ 乱码扫描为 0。
    - **补记时的取数纪律**：事实**必须从产物取**，不能凭记忆 —— 标题/方向从 outbox HTML 的 banner 取，
      失败原因从 `STANDBY_YYYYMMDD.txt` 取，`message_id` 从 scheduler 输出日志抠
      —— **不要重跑脚本去「重新拿一个 ID」**（会产生第二份产物）。**补记不等于抄旧结论，要重新回查。**
    - 完整事故记录、还原代码、三个坑（JSON 转义层 / 取值方式 / 同夜多候选）→ `references/readme-append-truncation-disaster.md`

---

## §A-backfilled-outage-log-must

**⚠️ A backfilled outage log must cover EVERY missed night, not just tonight (2026-11-06).**

原始 SKILL.md 条目（逐字）：

**⚠️ A backfilled outage log must cover EVERY missed night, not just tonight (2026-11-06).**
  The "append README early" rule fires per *session*, but sessions can be cut off before
  they append — so the log develops **holes**, not just a missing tail. On 2026-11-06 the
  README's last entry was 11-03 (day 71) even though 11-04 and 11-05 had both run and
  been delivered; the 11-04 session was truncated mid-work and the 11-05 session ran out
  of tool-call budget before its append.
  - **Fix on the next session: backfill EVERY gap night**, not only the current one. Each
    backfilled entry needs the same fields as a live one: symptom, cron trigger count,
    generated article + direction, HTML backup path + size, PENDING/STANDBY presence,
    Feishu `message_id` (readable from the scheduler output log at
    `~/.hermes/cron/output/<job_id>/*.md` — **don't re-run the script to get one**, that
    makes a second artifact), and what was fixed.
  - **Source the facts from the artifacts, not from memory**: `outbox/<platform>/YYYYMMDD_HHMM_<direction>.html`
    for title/direction, the `STANDBY_YYYYMMDD.txt` file for the failure reason, and the
    scheduler output log for the `message_id`.
  - **Verify the backfill with the heading count**, not by eyeballing:
    `grep -n '^## ' outbox/<platform>/README.md` — the count of `## YYYY-MM-DD` headings
    must increase by the number of nights backfilled (not by 1).
  - **Corollary:** the "count must increase by exactly 1 per session" check is for a
    *single-night* session. When you discover holes, the expected delta is
    *1 + (number of missing nights)*.

---

## §A-dead-mail-channel-is-not-a

**⚠️ A dead mail channel is not a dead content channel (2026-10-25, failure #62).**

原始 SKILL.md 条目（逐字）：

**⚠️ A dead mail channel is not a dead content channel (2026-10-25, failure #62).**
  When the email/SMTP channel has been down for weeks but the cron also has a healthy
  chat-platform `deliver` route, **push the content as a native file attachment on that
  route** instead of only writing a report that says "email failed". Working recipe:
  `tools.send_message_tool._send_to_platform(Platform.FEISHU, pconfig, chat_id, caption,
  thread_id=None, media_files=[(abs_html_path, False)])` → returns
  `{'success': True, 'message_id': 'om_...'}`. Verify by reading the message back
  (`lark.im.v1.GetMessageRequest` → confirm `msg_type == 'file'`, `deleted == False`).
  Caveats: `.html` is NOT in the `MEDIA:` regex whitelist but IS in `extract_local_files`'s
  `_LOCAL_MEDIA_EXTS`, and Feishu `file_type=stream` accepts arbitrary files; the SDK class
  is `lark.im.v1.GetMessageRequest` (top-level, not `lark.im.v1.message.*`); delete any
  superseded duplicate message so the user doesn't get two files. Be explicit in the report
  that this is a **channel substitution, not a mailbox fix** — the QQ auth code still needs
  regenerating if `569545015@qq.com` is the destination that matters.
  See `references/toutiao-cron-outage-2026-10-week4.md` Case Y.

---

## §A-dedup-helper-whose-read-ke

**⚠️ A dedup helper whose read key ≠ write key fails SILENTLY and forever (2026-10-27).**

原始 SKILL.md 条目（逐字）：

**⚠️ A dedup helper whose read key ≠ write key fails SILENTLY and forever (2026-10-27).**
  A content-generator can look like it has working cross-day topic rotation while
  never actually deduplicating. The failure mode: `_record_topic()` appends
  `{'key': ..., 'title': ..., 'date': ...}` but `_pick_topic()` reads
  `h.get('direction')` → every lookup returns `None` → `recent` becomes
  `['None','None',...]` → the "not recently used" candidate set is always the
  FULL pool → `random.choice(fresh)` degenerates to uniform random over the pool.
  No exception, no warning, no visible symptom other than repeated titles.
  **Detection recipe:** compare the key the writer emits against the key the
  reader looks up, then assert the candidate set is actually smaller than the pool:
  ```python
  recent = [mod._hist_key(h) for h in hist[-mod.MAX_RECENT:]]
  fresh = [t for t in POOL if t['direction'] not in recent]
  assert len(fresh) < len(POOL), "dedup is a no-op!"
  ```
  **Rule: whenever you add cross-day rotation, write an assertion that the
  candidate set SHRINKS, and simulate N future days before shipping.**
  A 12-day simulation should show 0 consecutive repeats and even distribution
  across the pool. "It generates different things" is not evidence of dedup.

---

## §A-brand-new-history-file-sta

**⚠️ A brand-new history file starts EMPTY → dedup silently does nothing until backfilled (2026-10-27).**

原始 SKILL.md 条目（逐字）：

**⚠️ A brand-new history file starts EMPTY → dedup silently does nothing until backfilled (2026-10-27).**
  When you introduce a rotation feature and seed its history file with *only
  today's picks*, the dedup window has no prior data to compare against, so the
  feature is a no-op on day 1 and stays a no-op until the window fills (~5 days).
  Real damage measured here: micro-topic history created 10-26 with only 2
  entries → near-8-day observed distribution was 婆媳关系 ×15, 老年婚姻 ×12,
  养老金 ×11 — the same micro-post went out many nights running.
  **Fix:** backfill the history file from ground truth before shipping —
  for this deployment the source of truth was parsing `方向：X` out of the
  accumulated outbox HTML (`outbox/<platform>/YYYYMMDD_HHMM_<direction>.html`),
  which yielded 50 micro-topic records for 10-11 → 10-27.
  **Rule: a new rotation feature ships with (a) a backfill of historical picks
  and (b) a multi-day simulation showing 0 consecutive repeats.** Verify the
  *frequency distribution*, not just the presence of the feature.

---

## §A-sliding-window-sized-in-re

**⚠️ A sliding window sized in *records* is the wrong unit for multi-per-day feeds (2026-10-28).**

原始 SKILL.md 条目（逐字）：

**⚠️ A sliding window sized in *records* is the wrong unit for multi-per-day feeds (2026-10-28).**
  A window expressed as a **record count** is correct for a 1-record-per-day feed, but a
  multi-per-day feed emits several records per day — so a 9-record window covers only half
  the intended days, and while the window is still filling, the "not recently used"
  candidate set stays wide and `random.choice` over it hits repeats with real probability.
  Measured on the micro feed (2 records/day, 9-record window): 6 consecutive repeats in a
  30-day simulation, only 6/10 directions ever used, worst offender at 22% of all micro posts.
  **Fix: use LRU (least-recently-used), not windowed-random** — rank candidates by the index
  of their last appearance in the history and take the oldest. Result: 0 consecutive repeats,
  10/10 directions covered, distribution exactly even.
  **Two corollaries:**
  - **The window must also track pool size.** A hardcoded `MAX_RECENT = 5` against a 10-item
    pool means the expanded pool is only half used — expanding the pool without widening
    the window is a no-op.
  - **Same-day exclusions must key on `direction`, not list index** — two micro posts on one
    night must never share a direction.
  **Cron-side rule:** whenever you add cross-day rotation, write an assertion that the
  candidate set **SHRINKS**, and simulate N future days before shipping. "It generates
  different things" is not evidence of dedup.
  Full implementation (`_pick_lru`) + the 30-day simulation harness:
  `productivity/content-platforms/references/topic-pool-rotation-and-length-engineering.md`.

---

## §Rotation-simulation-MUST-use

**⚠️ Rotation simulation MUST use a temp history file, or it corrupts production and lies to you (2026-10-28).**

原始 SKILL.md 条目（逐字）：

**⚠️ Rotation simulation MUST use a temp history file, or it corrupts production and lies to you (2026-10-28).**
  Pointing the picker at the real `topic_history.json` while simulating rewrites
  production state on every iteration and yields a wrong distribution. One run here
  reported "micro covers only 4/10 directions" — an artifact of the simulator reading
  and appending the live file, not a real defect.
  **Recipe:** redirect the module's history globals to `tempfile` paths, and make the
  picker accept an injected path so it is testable at all:
  ```python
  tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8')
  tmp.write('[]'); tmp.close()
  T.HISTORY_FILE = tmp.name
  # ... simulate N days ...
  os.unlink(tmp.name)
  ```
  Then **diff the real files** to prove nothing leaked:
  `diff <(cat /tmp/bk_topic.json) outbox/<platform>/topic_history.json`.

---

## §last-status-ok-does-NOT-mean

**⚠️ `last_status=ok` does NOT mean the report was delivered (Case Y, 2026-10-24).**

原始 SKILL.md 条目（逐字）：

**⚠️ `last_status=ok` does NOT mean the report was delivered (Case Y, 2026-10-24).**
  The scheduler records `ok` because the *job* ran and produced a response; the
  *delivery* step is separate and its failure only surfaces in `last_delivery_error`.
  This deployment had BOTH channels broken at once: QQ SMTP dead 61 nights AND the
  Feishu `deliver: origin` route broken by a stale `omt_` thread_id (`99992402 field
  validation failed`, root cause `99992354 invalid open_message_id` — `omt_` is a thread
  id, not a valid `receive_id` for `receive_id_type=thread_id`).
  **Operational rule: when investigating "I didn't get the cron message", read
  `last_delivery_error` FIRST, before diagnosing the job body.** And when running as a
  cron whose report rides a channel, check that channel's health — a broken delivery
  route makes the failure report invisible, so the user sees silence instead of an
  error. Fix: `hermes cron edit <job_id> --deliver "feishu:<chat_id>"` (omit the thread
  id). Full diagnosis + 3-step verification in `references/feishu-stale-thread-id-delivery-failure.md`.

---

## §A-content-cron-has-a-second-

**⚠️ A *content* cron has a second, quieter failure mode: the pipeline works but the product is bad (2026-10-28).**

原始 SKILL.md 条目（逐字）：

**⚠️ A *content* cron has a second, quieter failure mode: the pipeline works but the product is bad (2026-10-28).**
  Every symptom in this file is a *delivery* failure — SMTP 535, dead channel, false
  `last_status`. But a content cron can also fail **while every green light stays on**:
  the script exits 0, the Feishu attachment lands, the user receives a file — and that
  file is the same headline they received last cycle, or 400 characters short of the
  script's own checklist target. Nothing errors. Nothing looks wrong. The user just
  quietly stops reading.
  **Diagnosis order for a content cron — check the PRODUCT first, then the channel:**
  1. Read the latest outbox HTML back and **measure** it (Chinese-char count, story
     sections present, topic direction).
  2. Compare against the *script's own* `CHECKLIST_ITEMS` — the checklist is a contract,
     not decoration. (Measured here: the script's own "1500字以上" target had **zero**
     articles meeting it — 813-1159 chars against a 1500 target.)
  3. Audit topic-direction frequency across recent outbox files:
     `ls -1 outbox/<platform>/*.html | sed 's/.*_//' | sort | uniq -c`.
  4. Only then diagnose delivery.
  **Rule: a cron that ships the same artifact to the same audience every N days is
  failing, even when the delivery channel is 100% green.** Fix the pool/rotation, not
  the channel. Full recipes (pool sizing, LRU rotation, length assertions, the
  `str.format()` silent-drop check) in
  `productivity/content-platforms/references/topic-pool-rotation-and-length-engineering.md`.

---

## §The-audit-tool-can-be-DEAD-a

**🔴 The audit tool can be DEAD and the session still reports "all green" (2026-11-05, 2 nights lost).**

原始 SKILL.md 条目（逐字）：

**🔴 The audit tool can be DEAD and the session still reports "all green" (2026-11-05, 2 nights lost).**
  The content linter (`lint_content_consistency.py`) crashed on **every** run for two
  consecutive nights — `NameError: check_orphan_character` (the `_self_test()` called a
  function that was never defined) — **and the ORPHAN rule it was supposed to enforce
  was never wired into `lint()` at all**. Both nights were recorded as "linter green,
  content clean". They were not: the linter never reached the check.
  **Root cause of the concealment: the exit code was swallowed by a pipe.**
  `python3 linter.py ... | tail -30; echo "EXIT=$?"` reports **tail's** exit code (0),
  not the linter's. The linter actually exited 1 with **empty stdout** and a one-line
  traceback on stderr.
  **Rules:**
  - **Never run an audit tool through a pipe when you care about its exit code.**
    ```bash
    python3 linter.py --pool ... --extensions ... > /tmp/lo.txt 2>/tmp/le.txt
    echo "REAL EXIT=$?"; cat /tmp/lo.txt; echo "--stderr--"; cat /tmp/le.txt
    ```
  - **Triage by output shape, not by the exit code alone:** *stdout empty + stderr has a
    traceback* = **the tool is broken**, not "the content has problems". These demand
    opposite responses (fix the tool vs. fix the prose) and mixing them up wastes a
    night.
  - **A tool that self-checks must exit 2 on self-check failure** — never let an
    exception drag it down to 1, which means "content has problems".
  - **"I wrote the function" ≠ "the rule works."** Prove a new rule fires by feeding it
    a real counter-example (a temp pool + temp extensions file) and asserting exit 1
    plus the expected check code. Running it against clean content only proves the
    empty-set case, which is exit 0 regardless of whether the rule is wired up.
  - **🔴 2026-11-07 新增第三步：「跨池型不误报」。** 前两步（正例不报 + 反例必报）**都不够** ——
    `HOOK_PROMISE` 规则落地时两步都过了，却立刻产生 **14 处假阳性**（15 处命中里只有 1 处是真缺陷）。
    根因：规则自己的装配函数只认 `story_a`/`story_b` 系列字段，而**微头条池的正文在 `content`** ——
    微头条的「正文」被装配成空串，于是钩子/标题里的每个数字都判成「未兑现」。
    **第三步：对每一个选题池各跑一遍，把命中项连同该池正文一起打出来逐条人工核对。**
    ⚠️ **不要只看汇总数**（15 实际只有 1 个真缺陷）—— 汇总数会让人以为是 15 个缺陷。
    便捷工具：`productivity/content-platforms/scripts/check_pool_type_false_positives.py`
    （退出码 2 = 装配不出正文 = 该池字段结构与装配函数不匹配 = 假阳性来源）。
    **新增装配函数前，先看 linter 里有没有现成的池型分叉助手**（`_units_for()` / `_ext_pair()`）——
    自造第二套装配逻辑 = 迟早与主流程漂移。
  - **🔴 2026-11-17 实测：报告里的「工具链状态」那一行，必须是**真的跑出来的**，不能是「应该没问题」**。当晚 `verify_cross_night_collisions.py` 首次真跑就是坏的（尾部多余一行 `</content>` ⇒ SyntaxError ⇒ exit 1）。**规则：任何新落地的校验器，在同一次会话里用真实生产参数跑一遍并记录退出码，才允许写进报告的「工具链状态」行。** 落地 ≠ 可用 —— 未被调用过的工具会静默腐烂。

---

## §Even-a-GREEN-content-audit-c

**⚠️ Even a GREEN content audit can hide a broken product: check the arithmetic and the cast.**

原始 SKILL.md 条目（逐字）：

**⚠️ Even a GREEN content audit can hide a broken product: check the arithmetic and the cast.**
  A content cron's failure modes split cleanly into two halves, and this skill owns the
  **delivery** half. The **product** half — arithmetic, casts, promise fulfilment,
  cross-field consistency — is owned by **`content-platforms`**; do not re-derive it here.
  - **The cron-side rule that matters:** the article is assembled from multiple sources
    (pool entry + expansion paragraphs in a separate file), so a single-file read misses
    contradictions that only exist after assembly. When a content cron looks green, hand
    the product check to `content-platforms` — it owns the linter, the auditor, and the
    full defect-family catalogue.
  - **Cron-side discipline that survives here:** if you change content source, run the
    content-side auditor with the **exit code seen separately** (never through a pipe) —
    `0` = clean / `1` = product has problems / `2` = tool or argument wrong.
    Exit 2 means *"your command was wrong"*, **not** *"the content is wrong"* — the two
    are opposite in direction, and treating 2 as 1 makes you edit correct prose into
    broken prose.
  - **The parser trap (why "all green" can be a lie):** a checker whose Chinese money
    shorthand parser is wrong reports *already-correct* copy as defective. That direction
    of harm is worse than a miss — you "fix" six places, several of which were right.
    **Rule: validate a checker's parser against known-good examples, not just against
    "did it report anything".** The shipped linter has a built-in `_self_test()`;
    self-test failure must raise exit 2 (tool broken), never exit 1 (content broken).
  - **Full write-up + the recorded defects:** `productivity/content-platforms/references/content-self-consistency-checking.md`
    and `productivity/content-platforms/SKILL.md` §C / §F.
  - **The linter itself** (and its third death mode, `SyntaxError`):
    `productivity/content-platforms/scripts/lint_content_consistency.py` and
    `productivity/content-platforms/references/pool-wide-scan-and-linter-syntax-death.md`.

---

## §A-dead-mail-channel-is-not-a

**⚠️ A dead mail channel is not a dead content channel (2026-10-25, failure #62).**

原始 SKILL.md 条目（逐字）：

**⚠️ A dead mail channel is not a dead content channel (2026-10-25, failure #62).**
  `toutiao-article-daily.py` renders its own `CHECKLIST_ITEMS` list into a visible
  "发布前检查清单" block at the bottom of every article. When v1.1.0 changed the sender
  from `权权的HERMES（头条）` to `围炉家常话（头条）`, it updated `send_email()` but **not**
  the checklist string — so every article had been telling the user to verify a sender
  name the pipeline doesn't use. The checklist was not decoration this time; it was
  *shipping*, so the drift reached the reader.
  **Rule: any value that appears in more than one place (a config string, a brand
  name, a from-header, a checklist item) must be asserted against its source of truth,
  not eyeballed.** Cheap check for this deployment:
  ```bash
  # every identity string in the script, side by side
  grep -rn "围炉家常话\|权权的HERMES" ~/.hermes/cron/scripts/*.py
  # the checklist item that ships to the reader
  grep -n "发件人是否为" ~/.hermes/cron/scripts/toutiao-article-daily.py
  ```
  Also note the **version banner drifted the same way** (`v1.1.0` in the file header and
  `main()`'s stdout while the code was already at v1.2.x) — version strings are the most
  commonly left-stale field in a long-lived script. Bump them in the same edit as the
  feature they describe.

---

## §Two-pools-that-rotate-in-loc

**⚠️ Two pools that rotate in lockstep will eventually pair a story with its own twin.**

原始 SKILL.md 条目（逐字）：

**⚠️ Two pools that rotate in lockstep will eventually pair a story with its own twin.**
  Two content pools advancing together can hand the reader the same story twice in
  consecutive nights — a *delivery-quality* failure that no channel error reports.
  **This skill's diagnostic contribution:** a green channel does not mean a green
  experience; check the *product* for repetition across nights, not just for transport.
  - **The full root-cause chain, the guard-window tuning table, and the
    before/after verification are owned by `content-platforms`**
    (`productivity/content-platforms/references/guard-window-vs-rotation-period.md`,
    `productivity/content-platforms/references/cross-field-defect-detection.md`,
    `scripts/verify_cross_night_collisions.py --before-script <旧脚本备份>`).
  - **Cron-side takeaway:** the "cross-night collision" check belongs in the content
    cron's routine verification, and its proof of a fix requires a **reverse control**
    (same seed history, same simulation, only the changed parameters differ) — running
    the post-fix state alone cannot distinguish *"fixed"* from *"detector broken"*.
  - **Also add a checklist line** (it renders to the reader) so the rule is visible in the product.

---

## §Measure-the-ASSEMBLED-produc

**⚠️ Measure the ASSEMBLED product, not an intermediate return value.**

原始 SKILL.md 条目（逐字）：

**⚠️ Measure the ASSEMBLED product, not an intermediate return value.**
  A generator can look broken in an audit when the audit simply measures the wrong
  object — and the reverse is equally true: a green audit can be measuring the wrong
  object too. Two traps on `toutiao-article-daily.py`:
  1. `generate_article()` returns **only the long-form** HTML; the micro-article HTML is
     appended later inside `send_email()`. Auditing the return value ⇒ "micro-articles
     are missing!" — a false alarm.
  2. A micro-post's 150-250 char target applies to the **source `content` field**, not the
     rendered block (content + dialogue highlight + image prompt + tags).
  **Rule: before asserting a threshold, confirm the threshold's unit and scope against
  the code that actually ships.** Use the ready-made auditor rather than hand-rolled
  regexes (a non-greedy `<div class="prompt-text">.*?</div>` truncates at the first inner
  `</div>`, letting English prompt text leak into the word count):
  ```bash
  python3 ~/.hermes/skills/productivity/content-platforms/scripts/audit_rendered_article.py \
      ~/.hermes/cron/outbox/toutiao/<today>.html \
      --pool ~/.hermes/cron/scripts/toutiao-article-daily.py
  ```
  It reports body Chinese-char count, section presence, image-prompt block count vs
  `no text` occurrences, hashtag count, and micro `content` word-count range —
  exit 0 = clean, 1 = problems found.
  **Full recipe set:** `productivity/content-platforms/references/topic-pool-rotation-and-length-engineering.md`.

---

## §The-don-t-re-run-the-script-

**⚠️ The "don't re-run the script" rule (Case R) and the "fix the content" mandate are in tension — resolve it by fixing the code, not by re-running (2026-10-28).**

原始 SKILL.md 条目（逐字）：

**⚠️ The "don't re-run the script" rule (Case R) and the "fix the content" mandate are in tension — resolve it by fixing the code, not by re-running (2026-10-28).**
  Case R says: if the outbox already has today's backup, do NOT run the script again
  (each extra run generates a *different* random topic and creates a second backup).
  But a session that audits the content and finds a defect still needs to ship the fix.
  The resolution that honours both:
  - **Do not re-run the production script** to prove the fix — that would duplicate
    today's already-delivered artifact.
  - **Do fix the script**, so tonight and every future night benefit.
  - **Prove the fix with an isolated harness**: load the module via
    `importlib.util.spec_from_file_location(...)`, redirect its history/artifact paths to
    **temp files**, render N days, assert on the output.
  - **Diff the real history files afterwards** to prove the harness didn't touch
    production state (`diff <(cat /tmp/bk_topic.json) outbox/<platform>/topic_history.json`).
  This gives the user today's correct content *and* tomorrow's improved content, with
  no duplicate delivery and no data corruption.
  ⚠️ Corollary: the harness must inject its history path, and the module under test
  must therefore accept one (`def _pick_micro_index(used_indices, history_path=None)`).
  A function that hardcodes a global path can only be tested against production data.

---

## §Tool-green-does-not-mean-pro

**🔴 Tool-green does not mean product-correct — and "all green" has been disproven repeatedly.**

原始 SKILL.md 条目（逐字）：

**🔴 Tool-green does not mean product-correct — and "all green" has been disproven repeatedly.**
  Across many nights the full chain was green — `audit exit 0`, `lint exit 0`, script
  `exit 0`, backup channel confirmed delivered by `message.get` — and manual reading still
  found reader-visible defects. **The cron-side lesson is the meta-lesson:**
  - **Automation only covers defect families that have been encoded.** A new family is
    invisible to every tool until someone reads the prose and then encodes it.
  - **A content cron's routine must include a cross-night comparison** (is tonight's
    micro-post the same story as the last few nights' long-form?) and a whole-sentence
    repeat scan (does the hook/title sentence appear verbatim in the body?).
  - **Do not re-fix an already-fixed historical collision.** When auditing history, first
    confirm **which version ran that night** — a collision observed in an old artifact may
    predate the guard that now excludes it. Replaying the current code against that
    night's history state will show the guard working correctly, i.e. the "defect" was a
    historical event, not a live one. Reporting it as live causes a correct fix to be
    re-applied and reported as a fresh bug.
  - **The defect catalogue itself (promise fulfilment, quantifier chains, premise chains,
    cast/arithmetic chains, timeline chains, golden-line provenance, repeat thresholds)
    is owned by `content-platforms`** — see its `references/` directory for the full
    per-family write-ups, the 24-chain reading checklist, and the auditor/linter scripts.
  - **The cron-side rules that stay here:** (a) after changing content source, **re-measure
    CJK char counts immediately** (the linter does not check word-count ranges; only the
    post-render auditor does, and that waits for the next run); (b) `--pool` must point at
    the **generator script itself**, not at a pool data file, or the linter exits 2;
    (c) when repairs span multiple batches, the report must say plainly
    **"this batch was not re-rendered/verified — confirm on tomorrow's first run"** and
    attach the exact re-check command, so the next session does not read an unverified
    repair as verified (that is how a defect gets treated as closed forever);
    (d) after changing production source, **py_compile passing ≠ the change took effect** —
    the three traps (replace hitting a docstring instead of code; list-literal slicing
    leaving orphan commas; anchors copied from memory failing) and the "runtime behaviour
    assertion" rule (import once, print the key constant) live in `content-platforms`
    §J; (e) proving a behaviour change requires a **reverse control**, not just a
    passing post-fix run.
