# Outage README template (for cron outbox `README.md` files)

When a cron script's SMTP/credential failure persists for ≥3 days, the script's `outbox/<platform>/README.md` should evolve from a one-shot incident note into a durable outage log. This template is what agents should produce when extending the README on each failed night.

## When to extend (not just write once)

- **First failure**: write the initial README with problem + fix recipe (see template below).
- **Every subsequent failed night**: append a `## YYYY-MM-DD（持续中 — 第N天）` entry. Do NOT rewrite the whole file; append.
- **After 2 successful nights**: append `## YYYY-MM-DD（已解决）` and an archive recipe. Do NOT delete — the README is the durable history.

## Template

```markdown
# 头条文章 Outbox

存放因 SMTP 发送失败而被本地备份的 HTML 邮件稿件。

## YYYY-MM-DD（首次失败）

**问题**：QQ 邮箱 SMTP 授权码 `<AUTH_CODE>` 已失效，QQ 服务器返回 `535 Login fail: Account is abnormal, password is incorrect`。

**影响脚本**：
- `~/.hermes/cron/scripts/<script-name>.py` （本 outbox 的脚本）
- `<other-scripts-using-same-credential>.py` （共享凭据的脚本）

**修复方案**：登录 https://mail.qq.com → 设置 → 账户 → POP3/IMAP/SMTP/Exchange/CardDAV/CalDAV服务 → 生成新的授权码 → 更新 `/home/ubuntu/.hermes/cron/config/config.yaml` 中 `mail.smtp_pass` 字段。

**当日备份**：
- `20260825_2031_<direction>.html` (27 KB) — 长文《<title>》 + N 条微头条

## YYYY-MM-DD（持续中 — 第14天）

**症状**：`Connection unexpectedly closed`，QQ 返回 `Login fail. Account is abnormal, password is incorrect, login frequency limited, or system is busy`（535）。

**outbox 累计**：N 份 HTML 备份（自 YYYY-MM-DD 起，每天 1-2 份）。

**修复（一行）**：
```bash
# 1. mail.qq.com → 设置 → 账户 → 重新生成 SMTP 授权码
# 2. 把新授权码填到 ~/.hermes/cron/config/config.yaml 的 mail.smtp_pass
# 3. 手动跑一次确认：python3 ~/.hermes/cron/scripts/<script-name>.py
```

**今日备份**：
- `20260907_2030_<direction>.html` — 长文《<title>》 + N 条微头条

## YYYY-MM-DD（持续中 — 第N天）⏵ LIVE

**症状**：同上，无新发现。

**今日备份**：
- `<file>.html` — 长文《<title>》 + N 条微头条

**自动检测脚本**（给未来的 agent）：
```bash
[ "$(ls -1 ~/.hermes/cron/outbox/<platform>/*.html 2>/dev/null | wc -l)" -ge 3 ] \
  && grep -q "持续中" ~/.hermes/cron/outbox/<platform>/README.md \
  && echo "KNOWN CHRONIC OUTAGE — skip SMTP probe, jump to fix instructions"
```

**详细诊断与决策表**：见 `~/.hermes/skills/cron-job-debugging/references/<outage-case-study>.md`
```

## Why append, not rewrite

The README is the **durable outage log** that survives across:
- cron-job-script edits (if someone refactors `toutiao-article-daily.py`, the README still records the full history)
- config changes (a future regenerated auth code won't erase the evidence that the old one failed)
- agent sessions (a fresh cron-run agent has no in-memory context, but `cat outbox/toutiao/README.md` reconstructs everything)

Rewriting the file on each run destroys this property. Always `cat >> README.md <<EOF ... EOF` in shell, or `Path("README.md").open("a")` in Python.

## 🔴 NEVER use read-modify-write to append (2026-11-16 accident)

`read_file` has a **default `limit` of 500 lines and silently truncates**; `write_file` **overwrites the whole file**.
Doing `read_file` → mutate → `write_file` to append one section destroyed **14 history entries**
in one go (README went 822 lines → 513 lines on 2026-11-16).

**Use one of these instead:**
```bash
cat >> "$path" <<'HERMES_EOF'

## YYYY-MM-DD（持续中 — 第N天）
- Symptom: ...
HERMES_EOF
```
```python
from pathlib import Path
with Path(path).open('a', encoding='utf-8') as fh:
    fh.write(entry)
```

If you must read-modify-write: pass an explicit `limit` >= the file's line count AND compare
`r['total_lines']` against it — otherwise you are silently truncating.

**Recovery when this happens:** `~/.hermes/state.db` → `messages.tool_calls` holds the full
arguments of every past `write_file` / `execute_code` call, so each night's section can be
recovered verbatim and the file rebuilt. See
`references/readme-append-truncation-disaster.md` for the recovery code and the three
pitfalls (JSON escaping layer, where the text lives per tool type, picking the complete
copy among same-night duplicates).

**Post-append verification (all three):**
```bash
grep -c "^## " "$path"          # must be exactly +1 vs before
grep -n "^## " "$path" | tail -3   # last three headings continuous
grep -cP '\x{FFFD}' "$path"     # mojibake must be 0
```

## 🔴 Backfilling a MISSING night (2026-11-25 实测)

A night can be **entirely missing** from the README — not because the cron didn't fire,
but because that night's **reporting session was cut off** before it could append.
The symptom is a **gap in the middle** of the log (not just a missing tail):
last heading is 11-23, tonight is 11-25, but 11-24's product + STANDBY + delivery
all exist on disk.

**How to tell "session was truncated" from "cron didn't run":**

```bash
# ① Does the night's ARTIFACT exist? (it does ⇒ cron ran fine)
ls -1 ~/.hermes/cron/outbox/<platform>/YYYYMMDD_*.html
ls -1 ~/.hermes/cron/outbox/<platform>/STANDBY_YYYYMMDD.txt

# ② Did the reporting session get cut off? (grep agent.log for that night)
grep "YYYYMMDD" ~/.hermes/logs/agent.log | grep -E "max_iterations_reached|reason=text_response"
```

A `max_iterations_reached(N/N)` line for that night's cron session id ⇒ **the session
was truncated, not the cron**. Then confirm the *cause* of truncation — on this
deployment it was the skill file growing past the `skill_manage` write limit, which
made `skill_manage` retries eat the whole iteration budget.

**Backfill procedure (4 steps):**

1. **Diagnose the truncation** from `agent.log` and record it in the entry.
2. **Source every fact from the artifacts** — never from memory, and **never re-run
   the script to "get a fresh value"** (that creates a second product and pollutes
   history). The sources are:
   - title / direction / word count → the night's outbox HTML (`audit_rendered_article.py`)
   - failure reason + Feishu `message_id` → the night's `STANDBY_YYYYMMDD.txt`
   - delivery verification → re-check the OLD `message_id` with
     `python3 ~/.hermes/cron/scripts/_verify_feishu_msg.py <message_id>`
     (the message still exists — reading it back is not a re-run)
3. **Append the backfilled entry** (append-only, per the rules above), marking it
   explicitly as a backfill so the next session knows its facts came from artifacts:
   `- **🔴 本夜报告会话被 max_iterations_reached 掐断** … 本段是事后回填（事实全部从产物取，未重跑脚本）`
4. **Verify the heading delta** — expected delta is **`1 + (number of missing nights)`**,
   not 1. The single-night "+1" rule does not apply to a backfill session.

**Also fix the root cause in the same session.** A backfill that only patches the log
leaves the next session to be truncated again. When the truncation cause is a skill
file at its size limit, compress it in the same session (move long narratives to
`references/`) — otherwise the README gap just recurs, one night per truncation.

## What goes in, not in (per entry)

IN (each failed night):
- Date + failure count + symptom (one line)
- Today's generated content summary (title, direction, hook)
- Updated blast radius if it changed (new scripts added to the outage)
- New diagnostic data point if any (e.g. time-to-failure fingerprint, port-587 test result)

OUT:
- Re-explanation of what 535 means (in the SKILL.md, not here)
- The full SMTP transcript (in the case-study reference, not here)
- The fix recipe verbatim (link to it once at first entry, then `同上`)

The README is for **status tracking**, the reference doc is for **diagnostics**, the SKILL.md is for **how to debug**. Don't conflate them.

## Cross-references

- `~/.hermes/skills/cron-job-debugging/SKILL.md` Cases H, I, J — terse-report patterns + decision table for report length
- `~/.hermes/skills/cron-job-debugging/references/toutiao-cron-outage-2026-08.md` — the worked example of a multi-week outage documented this way