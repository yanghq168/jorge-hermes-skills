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