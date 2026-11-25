---
name: cron-job-debugging
description: "Debug silently-failing Hermes cron jobs (no_agent script mode, scheduled prompt jobs, chained jobs). Diagnose 'Script not found', 'Blocked: script path resolves outside the scripts directory', silent no-op, exit-code-without-output, path-resolution failures, AND credential/SMTP delivery failures by reading scheduler output logs in ~/.hermes/cron/output/. Applies the script-path resolution rule (wrapper-file fix — absolute paths and symlinks are both rejected), the SMTP-credential deep-dive, and the local-fallback save pattern."
version: 1.7.0
author: Hermes Agent
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [cron, scheduler, debugging, troubleshooting, no_agent]
---

# Cron Job Debugging

Hermes cron jobs can fail silently — the scheduler writes a markdown report to
`~/.hermes/cron/output/<job_id>/<timestamp>.md`, but nothing surfaces in the
main conversation until the user notices a job isn't delivering. This skill
covers the diagnostic loop and the most common fixes.

## When to use

Load this skill when the user reports any of:
- "My scheduled job isn't running"
- "The [X] cron is failing"
- "I never got the [daily/weekly] digest"
- A no-agent script-mode job that was supposed to run at a specific time but produced nothing
- A scheduler output log file with `Status: script failed`

## The diagnostic loop (5 steps)

When a cron job is misbehaving, always run this loop in order. Don't skip
straight to "the script must be broken" — Hermes cron has its own failure
modes that don't surface until you read the output log.

### 1. List jobs and find the ID

```bash
hermes cron list
# or for cronjob tool user: cronjob(action='list')
```

Record the `job_id` (e.g. `077158d603ec`) and the configured `schedule`.

### 2. Read the most recent output log

Output logs are the source of truth for silent failures:

```bash
ls ~/.hermes/cron/output/<job_id>/ | tail -5
cat ~/.hermes/cron/output/<job_id>/<most-recent>.md
```

The log header always includes:
- `Job ID`, `Run Time`, `Mode` (agent vs `no_agent (script)`), `Status`

If `Status: script failed`, the **body of the log is the error message** — don't
just glance at the header.

### 3. Decode the common errors

| Log body | Meaning | Fix |
|----------|---------|-----|
| `Script not found: <path>` | Scheduler couldn't find the script | See "Script-path resolution" below |
| `Blocked: script path resolves outside the scripts directory` | The `script` path resolves (after following symlinks) to somewhere outside `~/.hermes/scripts/` | Absolute paths and symlinks are both rejected — use a **wrapper file** (§4) |
| (empty body, agent mode) | The LLM hit an error before producing output | Re-run with `cronjob(action='run')` and watch stderr |
| Non-zero exit code | Script crashed | Run the script manually to see the traceback |
| (no log file at all) | Job didn't tick — scheduler down or paused | `hermes cron status` |
| Log says success but delivery failed | Job ran but couldn't reach the target | Check `delivery` config + target chat/channel |
| `Connection unexpectedly closed` / `SMTPServerDisconnected` | Almost always a **credential/transport failure**, not a network blip | See "SMTP/credential failure deep-dive" below |
| `535 Login fail` / `535 Authentication failed` | SMTP auth code / password is wrong or expired | See "SMTP/credential failure deep-dive" below |

### 4. Apply the Script-path resolution rule

**The most common silent-failure cause.** When you create or update a cron job
with `script=some/relative/path.sh`, the scheduler resolves it relative to
`~/.hermes/scripts/` (the Hermes scripts dir), NOT the directory the script
lives in. So a script at `~/.hermes/cron/scripts/skill-backup.sh` entered as
`script="cron/scripts/skill-backup.sh"` is looked for at
`~/.hermes/scripts/cron/scripts/skill-backup.sh` — which doesn't exist.

Diagnose by computing the expected path the scheduler uses and comparing it
to where the script actually lives:

```bash
HERMES_SCRIPTS="${HOME}/.hermes/scripts"
SCHED_PATH="$HERMES_SCRIPTS/<what-you-entered-as-script-field>"
ACTUAL="$(find ~/.hermes -name '<script-name>' -type f 2>/dev/null | head -1)"
echo "Scheduler looks at: $SCHED_PATH"
echo "Script actually at: $ACTUAL"
```

**🔴 2026-11-18 修订：下面这三种「修法」在当前 Hermes 版本里 **两种是错的**。**
实测（`cron/scheduler.py:851-900` 的 `_run_job_script()`）：

- **绝对路径（曾标注为 "preferred"）现在无效** —— `cronjob(action='update',
  script='/abs/path')` 会被工具层直接拒绝：
  `Script path must be relative to ~/.hermes/scripts/. Got absolute or
  home-relative path: '...'. Place scripts in ~/.hermes/scripts/ and use just
  the filename.`
- **软链接现在无效** —— 调度器对 `script` 做 `Path(...).resolve()`（**跟随软链接**），
  再校验结果必须仍在 `~/.hermes/scripts/` 内。软链接指向 `~/.hermes/cron/scripts/`
  ⇒ resolve 后落在 scripts 目录之外 ⇒ 被拦截：
  `Blocked: script path resolves outside the scripts directory (...)`。
  更糟的是软链接**通过了路径校验后仍会污染状态**：Python 的 `__file__` 指向
  链接路径 ⇒ 脚本里 `os.path.dirname(os.path.abspath(__file__))` 推出的状态文件
  目录变成链接目录 ⇒ **去重/历史文件分裂成两份**（实测
  `.xhs_escape_visited.json` 同时出现在真实目录和链接目录，两边各自增长）。

**✅ 唯一可靠的修法：在 `~/.hermes/scripts/` 下放一个 wrapper 文件。**
wrapper 是**真实文件**（能扛过 `resolve()`），内部再以真实路径执行生产脚本：

```python
# ~/.hermes/scripts/cron/scripts/<name>.py  —— Python wrapper
import os, runpy, sys
REAL_SCRIPT = "/home/ubuntu/.hermes/cron/scripts/<name>.py"
if not os.path.isfile(REAL_SCRIPT):
    sys.stderr.write(f"wrapper: target script missing: {REAL_SCRIPT}\n")
    raise SystemExit(2)
_real_dir = os.path.dirname(REAL_SCRIPT)
if _real_dir not in sys.path:
    sys.path.insert(0, _real_dir)   # 让 `from config_loader import ...` 可导入
runpy.run_path(REAL_SCRIPT, run_name="__main__")
```

```bash
# ~/.hermes/scripts/cron/scripts/<name>.sh  —— shell wrapper
exec bash /home/ubuntu/.hermes/cron/scripts/<name>.sh
```

`runpy.run_path()` 的两个好处（软链接和"移动脚本"都没有）：
① `__file__` = 真实路径 ⇒ 脚本自己的 `_SCRIPT_DIR` 推导出的状态文件目录不变
⇒ **状态文件不会分裂**；
② `sys.path[0]` = 真实脚本目录 ⇒ `from config_loader import get_mail_config`
仍然解析到 `~/.hermes/cron/scripts/config_loader.py`。
⚠️ wrapper 里**不要**用 `os.chdir` 替代 `sys.path.insert` —— `chdir` 不改
`sys.path`，`config_loader` 会 ImportError。

**⚠️ "把脚本移到 `~/.hermes/scripts/` 下" 也不是好方案**：脚本内部硬编码的
`/home/ubuntu/.hermes/cron/scripts/...` 引用（visited 文件、扩写模块、
`config_loader` 位置）会全部失效。wrapper 不动生产脚本，是唯一零副作用的方案。

**验证必须用调度器自己的入口**，不要靠肉眼看路径：

```bash
cd ~/.hermes/hermes-agent && python3 -c "
import sys; sys.path.insert(0, '/home/ubuntu/.hermes/hermes-agent')
from cron.scheduler import _run_job_script
ok, out = _run_job_script('cron/scripts/<name>.py')
print('success:', ok); print(out[:500])
"
```

这会复刻调度器的完整校验链（resolve → 目录归属 → 存在性 → 解释器选择 →
`cwd=path.parent` → `HERMES_HOME`/`HOME` 环境），返回 `(success, output)`。
**这是 ground truth** —— 前面的 `ls`/`find` 只能证明文件在，不能证明调度器能跑它。

修完 job 的 `script` 字段仍保持**相对路径**（`cron/scripts/<name>.py`），
指向 wrapper：

```python
cronjob(action='update', job_id='<id>', script='cron/scripts/<name>.py')
```

⚠️ **修完必查状态文件有没有分裂**（跑一次 wrapper 后）：
```bash
ls -la ~/.hermes/cron/scripts/.<name>_visited.json \
       ~/.hermes/scripts/cron/scripts/.<name>_visited.json 2>&1
```
链接目录那份若出现 ⇒ 说明 wrapper 没生效或用错了修法，删掉它并把真实目录那份
恢复原值。**测试跑 wrapper 会消耗生产状态**（比如消耗去重池条目、生成多余产物）
—— 测完要按原值还原。

详见 `references/script-not-found-case-study.md`。

### 5. SMTP / credential failure deep-dive (delivery-side silent failures)

The other common silent-failure class: the script runs, prints `❌ 发送失败: Connection unexpectedly closed`, exits 0 — and nothing reaches the inbox. The cryptic "connection closed" hides the real cause (almost always auth).

**The trap**: Python's `smtplib` re-raises the server's *post-AUTH* socket teardown as a generic `SMTPServerDisconnected("Connection unexpectedly closed")`. The real rejection is buried in the server transcript a few lines earlier. You cannot see it from the script's stdout.

**Step 1 — Reproduce with debug output to surface the real error:**

```bash
cd ~/.hermes/cron/scripts
python3 -c "
import smtplib, socket
from email.mime.text import MIMEText
socket.setdefaulttimeout(30)
smtplib.SMTP.debuglevel = 1
with smtplib.SMTP_SSL('<smtp_server>', 465, timeout=30) as s:
    s.login('<user>', '<pass>')
    s.sendmail('<user>', '<to>', 'Subject: t\n\ntest')
"
```

Look at the `reply:` lines. The smoking gun is one of:

- `535 Login fail. Account is abnormal, service is not open, password is incorrect, login frequency limited...` — **auth code/password is wrong, expired, or service not enabled**. Cannot be fixed remotely; user must log into the mail provider's web UI and regenerate. This is the **expected default for QQ Mail** when an SMTP authorization code has been revoked — see the dedicated callout below.
- `550 Mailbox not found` / `User not found` — recipient address wrong, or sender not authorized to send as that address.
- `554 DT:SPM ...` (QQ specific) — message body rejected as spam; shorten subject, remove URL shorteners, or fix plain-text/HTML mismatch.
- `454 4.7.0 Too many login attempts` — rate-limited; back off and try later, or stop running the script from multiple places.

**Most reliable probe — manual AUTH LOGIN + `getreply()` per step.** When `debuglevel=1` buries the 535 inside AUTH retries, drive the SMTP session yourself so each protocol step produces its own line:

```bash
python3 -c "
import smtplib, base64
s = smtplib.SMTP_SSL('smtp.qq.com', 465, timeout=15)
s.ehlo()
s.send(b'AUTH LOGIN\r\n'); code, msg = s.getreply(); print(f'AUTH LOGIN  -> {code} {msg!r}')
s.send(base64.b64encode(b'USER') + b'\r\n'); code, msg = s.getreply(); print(f'username   -> {code} {msg!r}')
s.send(base64.b64encode(b'PASS') + b'\r\n'); code, msg = s.getreply(); print(f'password   -> {code} {msg!r}')
"
```

On this deployment with a revoked auth code, the third `getreply()` prints:

```
password -> 535 b'Login fail. Account is abnormal, service is not open, password is incorrect, login frequency limited, or system is busy. ...'
```

Always deterministic. No scrolling past fast output, no second AUTH retry muddying the transcript. See Case I for the full transcript + the AUTH-recipe patch history.

**⚠️ QQ Mail default failure shape (Case A — explicit 535):** For this QQ deployment, the most common signature when an SMTP authorization code has been revoked is a **visible `535 Login fail. Account is abnormal, service is not open, password is incorrect, login frequency limited, or system is busy.` line in the SMTP transcript** between the AUTH command and the bare `SMTPServerDisconnected`. `smtplib.SMTP.debuglevel = 1` will usually surface it, but `smtplib` retries AUTH LOGIN after AUTH PLAIN fails with 535, and the second AUTH closes abruptly — the 535 can scroll past fast. **More reliable recipe — do AUTH LOGIN manually and call `getreply()` after each step so the 535 is its own line** (recipe above).

**Rarer edge case — QQ silent-reject (Case B, no 535 in transcript):** When QQ's anti-spam system has *aggressively* revoked an auth code, the server may close the TLS socket IMMEDIATELY after `AUTH` with NO `reply:` line at all — `debuglevel=1` will show a clean `EHLO 250` then a bare `SMTPServerDisconnected` with no `535` between them. This is indistinguishable from a network drop except by the pattern: SSL handshake + EHLO succeed + AUTH never gets a reply → credential revoked by aggressive anti-spam (not just expired). Same user fix (regenerate in QQ web UI), but the diagnostic signature is different — don't conclude "network issue" just because the 535 line is missing. Confirm by trying port 587 STARTTLS as well: if EHLO succeeds there too and AUTH dies silently, it's the same silent-reject. If port 587 hangs at connect, you have a real firewall/network problem instead. The manual AUTH recipe above also makes this case unambiguous — the third `getreply()` returns `(0, b'')` or raises before printing anything if the server tore down the socket.

**Faster path — run `scripts/probe_smtp.py`** instead of retyping the debuglevel recipe. It auto-detects which credential sources this Hermes deployment uses (`config.yaml` + `~/.hermes/.env`), runs both 465-SSL and 587-STARTTLS probes, and reports which of the three failure modes you're in: 535-in-transcript (Case A), no-reply-silent-reject (Case B), or connect-time failure (Case C). Exit 0 = auth dead, exit 1 = real network problem. See `references/smtp-credential-failure-case-study.md` for the full Case B transcript.

**Step 2 — Verify the credential actually matches what's stored.** Cron scripts read from `~/.hermes/cron/config/config.yaml` (via the standard `config_loader.py`). They do NOT inherit your interactive shell's env vars. So if your working theory is "the env-var auth code works but the YAML one doesn't" — check both:

```bash
# What's in the config file
grep -A1 smtp_pass ~/.hermes/cron/config/config.yaml
# What's in the env (if the script reads os.environ)
env | grep -iE "smtp|auth_code|mail_pass"
# Which one is the script actually using?
grep -nE "smtp_pass|os\.environ|SMTP_PASS" ~/.hermes/cron/scripts/<script>.py | head
```

In Hermes' standard pattern (`from config_loader import get_mail_config`), the YAML wins over env. If both are wrong, the fix is the YAML; env vars are only a fallback inside the `try/except ImportError` block.

**Step 3 — Try the alternate transport.** Port 465 (SMTPS/SSL) and port 587 (STARTTLS) are independent — one can be blocked by the host firewall while the other works. If 465 fails, retry with `smtplib.SMTP('host', 587)` + `.starttls()`. If both fail with the same `535`, the credential is dead regardless of transport.

**Step 4 — Save locally as a fallback so today's content isn't lost.** While waiting for the user to fix the credential, persist the generated output so the article/digest is still recoverable:

```python
# Inside the cron script's main(), BEFORE send_email(), or in a wrapper:
import os
from datetime import datetime
out_dir = os.path.expanduser('~/.hermes/cron/output')
os.makedirs(out_dir, exist_ok=True)
ts = datetime.now().strftime('%Y-%m-%d_%H-%M')
with open(f'{out_dir}/<script>_{ts}.html', 'w', encoding='utf-8') as f:
    f.write(full_html)
with open(f'{out_dir}/<script>_{ts}.txt', 'w', encoding='utf-8') as f:
    f.write(plain_text)
```

Then in the failure report, point the user at the saved file. This is the difference between "today's content is gone" and "today's content is on disk, please fix auth."

### 6. Tiered fallback: retry transient, then save locally on hard failure

Step 4's "save before send" is the right pattern for content that takes a long time to generate. But most cron scripts already have the content in memory by the time they call `send_email()`, and saving-then-attempting-then-re-saving-on-failure is two writes of the same bytes. A tighter pattern that works well in practice:

**a. Retry transient `SMTPServerDisconnected` once with a 3s backoff.** Most 535 / socket-teardown failures are NOT transient — but a real network blip looks identical to a credential failure from the script's side. One cheap retry distinguishes them and recovers the rare real-blip case without hiding real auth failures.

```python
import time
last_err = None
for attempt in range(2):
    try:
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=15) as server:
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, TO_EMAIL, msg.as_string())
        return True, "发送成功"
    except (smtplib.SMTPServerDisconnected, smtplib.SMTPException, OSError) as e:
        last_err = e
        if attempt == 0:
            time.sleep(3)
        continue
```

**b. On final failure, save to a dedicated outbox.** Don't reuse `~/.hermes/cron/output/<job_id>/` — that's the scheduler's log dir and gets confused with run records. Use `~/.hermes/cron/outbox/<platform>/` (one subdir per delivery platform: `toutiao/`, `wechat/`, `email/`):

```python
from pathlib import Path
from datetime import datetime
outbox = Path("/home/ubuntu/.hermes/cron/outbox/toutiao")
outbox.mkdir(parents=True, exist_ok=True)
ts = datetime.now().strftime("%Y%m%d_%H%M")
fname = outbox / f"{ts}_{topic['direction']}.html"
fname.write_text(full_html, encoding="utf-8")
return False, f"{last_err} (重试2次仍失败，HTML已备份: {fname})"
```

**c. Tell the user where the backup is in the failure message.** The whole point is that today's content isn't lost while the credential gets fixed. Embed the absolute path in the script's stderr so the failure report can show "HTML saved to /home/ubuntu/.hermes/cron/outbox/toutiao/20260825_2031_亲戚恩怨.html" and the user can open it.

**Working example**: `~/.hermes/cron/scripts/toutiao-article-daily.py::send_email()` after the 2026-08-25 fix — read it directly as the reference implementation.

### 7. Verify by triggering

```bash
cronjob(action='run', job_id='<job_id>')
# Wait a moment, then read the new log
ls -t ~/.hermes/cron/output/<job_id>/ | head -1 | xargs -I {} cat ~/.hermes/cron/output/<job_id>/{}
```

## Pitfalls

- **🔴 2026-11-23: THIS skill file's own size is a live hazard — keep it under ~75k chars.**
  - On 2026-11-22 the reporting agent burned its entire iteration budget on
  `skill_manage` retries because `SKILL.md content is 100,314 characters
  (limit: 100,000)`. The session ended with `Turn ended:
  reason=max_iterations_reached(60/60)` — **the report was marked
  `last_status=error` even though the article had been generated and
  delivered successfully.** Root cause chain:
  1. `skill_manage` refuses writes to……
  - 📄 完整案例叙事已下沉 → `references/pitfalls-compression-archive.md`（§2026-11-23-THIS-skill-file-s）
- **Headers lie, bodies don't.** A log can show `Status: script failed` but
  also contain the exact reason — read the body, not just the header line.
- **The script field is opaque.** The `cronjob` tool, `hermes cron list`, and
  the job-store JSON all show the script as you entered it. They do not tell
  you *how the scheduler will resolve it*. Always verify the resolved path
  yourself if a script-mode job is failing.
- **Profile context matters.** A no_agent script runs with HERMES_HOME pinned
  to the active profile's home. If you reference `~/.hermes/...` from inside
  such a script, it goes to the *profile* home, not the root home. Use
  `${HERMES_HOME}` env var or absolute paths inside cron scripts.
- **Scripts run with the scheduler's env, not your shell env.** Cron jobs do
  NOT inherit your interactive shell's PATH, alias, or sourced env vars. If
  a script depends on PATH, set PATH at the top of the script. If it needs
  `~/.ssh/jorge_server`, set the env var explicitly inside the script.
- **`hermes cron list` shows paused jobs only with `--all`.** A job you
  paused last week won't show in plain `cron list` and you'll waste an hour
  chasing a non-issue.
- **A `no_agent` script that exits 0 can still show `last_status: error`.**
  This is a platform reporting bug, not a script bug — the mirror image of the
  `last_status=ok` masking case below. Tell-tale signs: `last_status: error`
  but `last_run_at` advancing normally, `last_delivery_error: null`, and the
  script's own log showing ✅. **Trust the script's own log and the outbox,
  not the scheduler's status field** — it is unreliable in *both* directions.
  Confirm with `python3 ~/.hermes/cron/scripts/<script>.py; echo "Exit: $?"`
  before assuming anything is broken. Known false-reporters on this deployment:
  `xhs-escape-weekend.py`, `wechat-article-daily.py`, `skill-backup.sh`,
  `agency-backup.sh`. Details in
  `references/no-agent-false-error-reporting.md`.
- **`last_status: error` cannot distinguish "false report" from "partial
  success".** A `no_agent` script that produced its output but then failed
  delivery exits non-zero — so the scheduler's `error` is *accurate*, yet the
  work product is safe on disk. Verified 2026-10-28: `wechat-article-daily.py`
  logs `❌ 邮件发送失败` **and** `✅ MD文件已生成`, and
  `/home/ubuntu/article-wechat-*.md` has a fresh file every night, while
  `jobs.json` shows `last_status: error`. **Always check for the artifact
  before re-running** (`ls -lt ~/.hermes/cron/outbox/<platform>/*.html`,
  `ls -lt /home/ubuntu/article-*.md`). If a product exists, the production
  step succeeded — fix only the delivery channel, and do NOT re-run the
  script (a second run generates different content and creates a second
  backup). Three-way triage — false report / partial success / total failure —
  in `references/no-agent-false-error-reporting.md`.
- **Multiple jobs can hit the same bug at once.** When one cron job's script
  path is wrong, check whether other jobs use the same path pattern — they
  almost certainly do. Fix all of them in one pass.
- **🔴 2026-11-18: the "three fixes" for script-path resolution were two-thirds
  wrong.** Absolute path ⇒ tool rejects it; symlink ⇒ scheduler's `resolve()`
  guard blocks it AND it splits the script's state file into two. The
  **wrapper-file** approach is the one that actually works. Read §4 before
  trying to fix a `Script not found` job — the older advice in this skill
  predates the scheduler's path guard. Full transcript + the wrapper
  implementations:
  `references/script-not-found-case-study.md`.
- **⚠️ A `no_agent` job that has NEVER succeeded looks like "the script is
  broken" but isn't.** Count the failures before investigating the script
  body: `ls ~/.hermes/cron/output/<job_id>/*.md | wc -l` vs
  `grep -l "Script not found" ~/.hermes/cron/output/<job_id>/*.md | wc -l`.
  If those two numbers are EQUAL, the script never ran even once — the fault
  is 100% path resolution, and reading the script's code is wasted effort.
  Measured 2026-11-18: 4 jobs, 172 runs each, 172/172 `Script not found`
  since 2026-05-31 — five months of silent failure nobody noticed because
  the failure report scrolled past. **Check the failure COUNT early, and
  report the duration ("broken since <date>, N consecutive failures")** —
  the duration is what makes the user realize this is not new.
- **🔴 `no_agent` jobs are the ones that fail silently** — an agent-mode job
  always produces *some* response, so a broken agent job is visible. A
  `no_agent` job whose script can't be found produces only a one-line
  scheduler log. **When a user says "the cron isn't running", enumerate ALL
  jobs and check each one's output log for `Status: script failed`** — one
  broken script path can disable four jobs simultaneously.
- **⚠️ Fixing a `no_agent` job's path can UNCOVER duplicate scheduling.**
  - job that never ran was harmless; once it runs, it may collide with classic
  crontab. Check `crontab -l` against `jobs.json` schedules for the same
  script BEFORE declaring victory. Two distinct failure modes to separate:
  - *agent-mode* + classic cron on the same script ⇒ usually fine (the agent
    audits rather than regenerates; check artifact counts to confirm).
  - *no_agent* + classic cron on the same script……
  - 📄 完整案例叙事已下沉 → `references/pitfalls-compression-archive.md`（§Fixing-a-no-agent-job-s-path）
- **⚠️ Verify what a script ACTUALLY delivers before assuming it delivers.**
  `wechat-article-daily.py` has functions named `send_md_to_feishu()` and
  `send_md_via_hermes()` that contain **no send call at all** — they only
  write a local `.md` file and return its path. Grep for the transport
  (`smtplib`, `requests`, `subprocess`, `hermes send`) rather than trusting
  function names. A misleading name can make you report "pushed to Feishu"
  for something that only touched the local disk.
- **`cronjob(action='run')` runs once on the next tick, not immediately.**
  If you need synchronous verification, execute the script directly via
  terminal and read the log a moment later.
- **`Connection unexpectedly closed` is almost never a real network issue.**
  Python's `smtplib` reports the server's post-AUTH socket teardown as that
  generic error. The actual cause (535, rate limit, blocked port) is in the
  SMTP transcript one level deeper. Turn on `smtplib.SMTP.debuglevel = 1`
  (or better: drive the SMTP session manually with `AUTH LOGIN` + `getreply()`
  per step — see Case I) and re-read the `reply:` lines before assuming
  connectivity is the problem.
  See the "SMTP / credential failure deep-dive" section for the full recipe.
- **`debuglevel=2` is NOT a "more verbose" upgrade — it can still bury the
  535.** Both `debuglevel=1` and `debuglevel=2` rely on Python's smtplib to
  walk through the AUTH negotiation, and Python retries with AUTH LOGIN after
  AUTH PLAIN fails with 535. The second AUTH closes abruptly and your
  terminal scrolls past the actual rejection. The only deterministic recipe
  for surface-the-535 on QQ is the manual `server.send(b"AUTH LOGIN\r\n");
  server.getreply()` per step pattern from Case I. Verified 2026-09-09
  (failure #15): `debuglevel=2` + `SMTP_SSL(...)` reproduces the exact same
  buries-the-535 behavior as `debuglevel=1`. Don't trust debuglevel alone.
- **Before any SMTP work, check the outbox age to detect a same-outage repeat.**
  - `ls -1 ~/.hermes/cron/outbox/<platform>/*.html 2>/dev/null | wc -l` is the fastest "is this the same SMTP outage I've already diagnosed?" check.
    If the count is ≥3 AND the platform's `outbox/<platform>/README.md` has no
    "Outage resolved" entry, you are looking at a known chronic failure —
    skip Steps 1-5 of the diagnostic loop and jump to the Case H terse-report
    pattern (outbox path + one-line fix). Sa……
  - 📄 完整案例叙事已下沉 → `references/pitfalls-compression-archive.md`（§Before-any-SMTP-work-check-t）
- **The "From header invalid" error mode (2026-08-23) was fixed and has
  not recurred.** If you see `550 ... "From" header is missing or invalid.
  Please follow RFC5322...` (vs `Connection unexpectedly closed`), check
  the script's `msg['From']` line uses `formataddr((str(Header('Name',
  'utf-8')), SMTP_USER))` — that pattern is the stable fix. The
  `Connection unexpectedly closed` family of errors is a separate
  credential problem; don't conflate them.
- **Cron scripts do not inherit your interactive env vars.** A script that
  reads `os.environ['QQ_EMAIL_AUTH_CODE']` will get an empty string in cron
  context, and your "I tested it manually and it worked" recollection is
  wrong because your shell *did* have the var set. Either bake the credential
  into `~/.hermes/cron/config/config.yaml`, or `export` it at the top of the
  script. See `references/smtp-credential-failure-case-study.md` for a
  worked case study.
- **Once `probe_smtp.py` confirms a known auth-revocation pattern, stop re-running the script.** The credential is binary (valid or revoked), not probabilistic — re-running the full content-generation + SMTP-failure cycle produces zero new information, just more identical `❌ 发送失败: Connection unexpectedly closed` output that consumes cron-output bandwidth. After the first confirm, switch immediately to user-report mode (point at the outbox backup, give the fix command). See Case E in `references/smtp-credential-failure-case-study.md`.
- **A failed email cron loses today's content unless you save it locally.**
  The script's `try/except` around `sendmail` swallows the error and exits
  cleanly — the article is gone. Always save the rendered HTML/text to
  `~/.hermes/cron/output/<script>_<timestamp>.{html,txt}` BEFORE attempting
  delivery, so a credential outage doesn't also nuke the work product.
  See "Step 4 — Save locally as a fallback" in the SMTP deep-dive.
- **Provider-specific error codes are not interchangeable.** QQ's `535` is
  a generic auth/account-abnormal message; Gmail is more specific; Outlook
  /Office365 adds a `5.7.606` error code you'll need to look up. Don't try
  to pattern-match across providers — read the full error string the first
  time.
- **Save AFTER failure, not only BEFORE send.** The Step 4 pattern (write
  HTML to disk before calling send_email) covers the "script crashes mid-
  delivery" case, but the common SMTP failure is the script completing
  cleanly with the article still in memory. A second backup at the catch-
  block tail catches BOTH the "credential died" and "network blip" paths
  without a wasted write on success. Combine: one retry on transient
  `SMTPServerDisconnected` (3s backoff), then save to
  `~/.hermes/cron/outbox/<platform>/` on final failure with the absolute
  path embedded in the error message. See step 6 of the SMTP deep-dive for
  the working template from `toutiao-article-daily.py`.
- **Three outbox-resident artifact types, three purposes (Case V, 2026-10-12).**
  - 
  - 📄 完整案例叙事已下沉 → `references/pitfalls-compression-archive.md`（§Three-outbox-resident-artifa）
- **The failure report must NOT depend on the broken channel.** When the
  cron is failing because of email, the failure report cannot be an email.
  Always check the cron's `deliver` config: if it's `deliver: origin` to
  Feishu/Lark/Slack, the agent's final response auto-delivers there and
  the failure report can ride that channel safely. If no `deliver` is
  configured, write the failure report into
  `~/.hermes/cron/outbox/<platform>/README.md` alongside the HTML backups
  so the user finds it when they next inspect the outbox. See Case F in
  `references/smtp-credential-failure-case-study.md` for the canonical
  report template.
- **Escalate to explicit user-facing fix instructions after the 3rd
  consecutive identical failure.** The first 1–2 occurrences: confirm with
  `probe_smtp.py`, save the outbox backup, and report minimally. From the
  3rd occurrence onward: include the verbatim QQ-web-UI fix steps
  (mail.qq.com → 设置 → 账户 → regenerate SMTP authorization code →
  update `~/.hermes/cron/config/config.yaml`) in the report, plus the
  cumulative failure count. By day 5+, the report should read like a
  runbook entry, not a passive error message — the user has likely been
  ignoring the first two.
- **At 10+ consecutive identical failures, stop running `probe_smtp.py`.**
  The credential state hasn't changed in a week; running the probe again
  consumes tokens to confirm what `~/.hermes/cron/outbox/<platform>/README.md`
  already says. Skip straight to: outbox path + auth code location + the
  one-line fix. The user knows — they just haven't done it. Treat it like
  a runbook dispatch, not an investigation. See Case H for the canonical
  terse report template.
- **⚠️ The README extension is independent of the failure report — and it is the
  step agents skip at high N.** At failure count ≥30 the terse dispatch report
  already "feels complete", so agents skip the `## YYYY-MM-DD（持续中 — 第N天）`
  README append. But the report rides the `deliver` channel and scrolls past;
  the README persists and is what lets the *next* session reconstruct the
  outage. Treat it as a terminal action, not cleanup. Verify with
  `grep -c "^## " ~/.hermes/cron/outbox/<platform>/README.md` — the count must
  increase by 1 per session. See the Escalation policy below and Case W in
  `references/case-log-chronic-outage.md`.
- **🔴 Do the README append EARLY, not last (2026-11-05, a session got cut off).**
  - A cron session hit its tool-call limit *after* the content fixes and verification
  but *before* the README append and the outbox prune — the two terminal actions.
  The fixes landed in the source (good), but the cross-session outage log skipped
  a night, so the next session's "第N天" counter was wrong and the README had no
  record of the linter repair.
  **Rule: for a chronic-outage cron, append the README entry and……
  - 📄 完整案例叙事已下沉 → `references/pitfalls-compression-archive.md`（§Do-the-README-append-EARLY-n）
- **⚠️ Case K ("IP-level AUTH block") is NOT reproducible on this deployment — never cite
  it without a fresh raw-socket control test.** Originally "discovered" 2026-09-11 (failure
  #17) from `server.login(good_pass)` and `server.login(wrong_pass)` both returning
  `SMTPServerDisconnected("Connection unexpectedly closed")` in ~0.6s with no `reply:` line
  and no 535, which looked like QQ rejecting AUTH from this IP before credential validation.
  **Disproven 2026-10-20 (failure #57):** a raw socket + manual `AUTH LOGIN` probe against
  smtp.qq.com:465 produced a complete, explicit transcript — `220` banner,
  `250-AUTH LOGIN PLAIN XOAUTH XOAUTH2`, `334 VXNlcm5hbWU6`, `334 UGFzc3dvcmQ6`, then
  **`535 Login fail. Account is abnormal, service is not open, password is incorrect, login
  frequency limited, or system is busy.`** TCP and TLS are healthy; QQ does validate the
  credential and returns Case A (explicit 535). The reason `smtplib.login()` appears to
  "hide" the 535 is purely client-side: `smtplib` tries AUTH PLAIN, gets the 535, retries AUTH
  LOGIN, and the second attempt's abrupt teardown surfaces as `SMTPServerDisconnected`.
  That exception is a **symptom of smtplib's retry logic**, not evidence of an IP block.
  **Operational rule:** never conclude "IP-level block" from `SMTPServerDisconnected`
  alone. Drive the session yourself — `socket.create_connection()` + `ssl.wrap_socket()`,
  then send `AUTH LOGIN`, base64 username, base64 password, printing every server line. If a
  `535` appears, the credential is dead; the fix is regenerating the auth code, full stop.
  Full transcript + the raw-socket recipe: `references/smtp-credential-failure-case-study.md`.
- **⚠️ A backfilled outage log must cover EVERY missed night, not just tonight (2026-11-06).**
  - The "append README early" rule fires per *session*, but sessions can be cut off before
  they append — so the log develops **holes**, not just a missing tail. On 2026-11-06 the
  README's last entry was 11-03 (day 71) even though 11-04 and 11-05 had both run and
  been delivered; the 11-04 session was truncated mid-work and the 11-05 session ran out
  of tool-call budget before its append.
  - **Fix on the next sessi……
  - 📄 完整案例叙事已下沉 → `references/pitfalls-compression-archive.md`（§A-backfilled-outage-log-must）
- **`crontab.txt` and Hermes `jobs.json` are independent schedulers.** Some
  deployments run the same script under both classic cron (`crontab -l` →
  `~/.hermes/cron/crontab.txt`) AND the Hermes cron scheduler (`jobs.json`).
  When debugging a "silent" cron, check both — `jobs.json` may show the job
  exists but not actually be the one firing, or vice versa. The log dir
  `~/.hermes/cron/output/<job_id>/` only exists for Hermes-scheduler runs.
- **`crontab.txt` is invisible to the Hermes health view.** Classic cron
  fires the script, the script writes to `toutiao-article-daily.log` (the
  redirect target), and `jobs.json` is never touched. So `jobs.json`'s
  `last_run_at` / `last_status` only reflects Hermes-scheduler runs of the
  script — classic cron is a parallel universe the scheduler can't see.
  Detection recipe for "is classic cron firing?": compare
  `ls -t ~/.hermes/cron/outbox/<platform>/*.html | head -1 | xargs stat -c %y`
  (outbox mtime, fires under either scheduler) against
  `python3 -c "import json; j=json.load(open('$HOME/.hermes/cron/jobs.json')); ..."`
  (Hermes-side timestamp). If outbox is newer than Hermes's last run, classic
  cron fired in between. This is the only way to detect double-fires when
  the same script is registered under both.
- **`outbox/<platform>/README.md` is the durable outage log; extend it
  on every failed night, don't rewrite.** When a cron has been failing
  for ≥3 consecutive nights, append a `## YYYY-MM-DD（持续中 — 第N天）`
  entry to the outbox README — never overwrite the file. The README is
  the cross-session memory that lets a fresh cron-run agent reconstruct
  the full outage history without burning tokens re-diagnosing. See
  `references/outage-readme-template.md` for the full template and
  "what goes in vs out" rules.
- **⚠️ 飞书 `message.get` 回查在本 SDK 版本有三处 API 差异（2026-11-03 实测）**：想确认备用通道「真的送达」而不是「脚本说送达」，必须回查消息。踩到的三个坑：**① `message.get` 是同步方法**（`await` 会报 `TypeError: object GetMessageResponse can't be used in 'await' expression`）；**② `success`/`code`/`msg` 是属性不是方法**（`resp.success()` 会报 `'int' object is not callable`）；**③ `data.items` 是 `Message` 对象不是 dict**（`it.get('msg_type')` 会报 `'Message' object has no attribute 'get'`）。`body.content` 里能看到 `{"file_key": "...", "file_name": "20261103_2030_房产纠纷.html"}` —— 用 `file_name` 核对「送达的是不是今夜那份」，比只看 `msg_type=file` 更可靠。
  - **已固化为 `~/.hermes/cron/scripts/_verify_feishu_msg.py`**（venv python 执行，`python3 _verify_feishu_msg.py <message_id>`）—— 以后每晚可直接回查，不用每次重写这段踩坑代码。
  - **注意 `create_time` 是毫秒时间戳**（如 `1793709006972`），不是秒。
- **⚠️ 飞书备用通道的 `message_id` 只出现在脚本自己的日志/错误串里**：`send_email()` 的失败返回串是 `[QQ SMTP 限频 / 飞书附件投递成功 (message_id=om_...)] Connection unexpectedly closed`。要回查就把这串 ID 抠出来 —— 别重跑脚本去"重新拿一个 ID"，那会生成第二份产物（Case R）。
- **⚠️ A dead mail channel is not a dead content channel (2026-10-25, failure #62).**
  - When the email/SMTP channel has been down for weeks but the cron also has a healthy
  chat-platform `deliver` route, **push the content as a native file attachment on that
  route** instead of only writing a report that says "email failed". Working recipe:
  `tools.send_message_tool._send_to_platform(Platform.FEISHU, pconfig, chat_id, caption,
  thread_id=None, media_files=[(abs_html_path, False)])` → returns
  `{'su……
  - 📄 完整案例叙事已下沉 → `references/pitfalls-compression-archive.md`（§A-dead-mail-channel-is-not-a）
- **⚠️ A dedup helper whose read key ≠ write key fails SILENTLY and forever (2026-10-27).**
  - A content-generator can look like it has working cross-day topic rotation while
  never actually deduplicating. The failure mode: `_record_topic()` appends
  `{'key': ..., 'title': ..., 'date': ...}` but `_pick_topic()` reads
  `h.get('direction')` → every lookup returns `None` → `recent` becomes
  `['None','None',...]` → the "not recently used" candidate set is always the
  FULL pool → `random.choice(fresh)` degener……
  - 📄 完整案例叙事已下沉 → `references/pitfalls-compression-archive.md`（§A-dedup-helper-whose-read-ke）
- **⚠️ A brand-new history file starts EMPTY → dedup silently does nothing until backfilled (2026-10-27).**
  - When you introduce a rotation feature and seed its history file with *only
  today's picks*, the dedup window has no prior data to compare against, so the
  feature is a no-op on day 1 and stays a no-op until the window fills (~5 days).
  Real damage measured here: micro-topic history created 10-26 with only 2
  entries → near-8-day observed distribution was 婆媳关系 ×15, 老年婚姻 ×12,
  养老金 ×11 — the same micro-post went ou……
  - 📄 完整案例叙事已下沉 → `references/pitfalls-compression-archive.md`（§A-brand-new-history-file-sta）
- **⚠️ A sliding window sized in *records* is the wrong unit for multi-per-day feeds (2026-10-28).**
  - A window expressed as a **record count** is correct for a 1-record-per-day feed, but a
  multi-per-day feed emits several records per day — so a 9-record window covers only half
  the intended days, and while the window is still filling, the "not recently used"
  candidate set stays wide and `random.choice` over it hits repeats with real probability.
  Measured on the micro feed (2 records/day, 9-record window): 6 co……
  - 📄 完整案例叙事已下沉 → `references/pitfalls-compression-archive.md`（§A-sliding-window-sized-in-re）
- **⚠️ Rotation simulation MUST use a temp history file, or it corrupts production and lies to you (2026-10-28).**
  - Pointing the picker at the real `topic_history.json` while simulating rewrites
  production state on every iteration and yields a wrong distribution. One run here
  reported "micro covers only 4/10 directions" — an artifact of the simulator reading
  and appending the live file, not a real defect.
  **Recipe:** redirect the module's history globals to `tempfile` paths, and make the
  picker accept an injected path so……
  - 📄 完整案例叙事已下沉 → `references/pitfalls-compression-archive.md`（§Rotation-simulation-MUST-use）
- **⚠️ `str.format(**kwargs)` silently DROPS kwargs the template doesn't reference (2026-10-25).**
  `generate_article()` passed `story_a_dialogue` / `story_a_ending` / `story_b_ending` into
  `HTML_TEMPLATE.format(...)`, but the template had **no placeholders for them** — so they were
  accepted and thrown away with no error. Every article since v1.1.0 shipped with its story
  dialogue and endings missing, silently violating 「故事要完整」. `str.format()` raises only on
  *missing* placeholders, never on *unused* kwargs.
  **Rule: after ANY generator/template edit, read the rendered product back and grep for the
  key content fields** — "renders without error" does NOT prove the output is complete.
  Verify the product, not the process. Same class of bug applies to any
  `dict`-driven template (`jinja2` silently renders empty for undefined vars too).
- **One revoked credential fails N scripts, not one.** When a content-platform
  cron (e.g. `toutiao-article-daily.py`) hits `SMTPServerDisconnected`, grep
  the whole `~/.hermes/cron/scripts/` directory for `smtp_pass` /
  `get_mail_config` to find every script that shares the credential. One
  bash one-liner tallies success/fail counts across all of them and gives
  the user the real blast radius (see `references/toutiao-cron-outage-2026-08.md`
  for the worked example: this deployment's QQ credential failure silently
  drops content from 3 content-platform scripts, not just the one in the
  log title). Don't fix one and report — fix the credential once and tell
  the user how many crons recover.
- **Match the report length to the delivery channel.** Case H's 4-line terse
  dispatch is right when the cron delivers via the same broken channel
  (e.g. `deliver: email` and email is what's broken — long reports burn the
  user's inbox) OR when failure count is ≥30 (user has been ignoring it
  for a month). For cron deliveries that route through the agent's main
  chat (`deliver: origin` to Feishu/Lark/etc.) at failure counts 10–25, a
  hybrid — headline + cross-script blast radius + generated-content
  summary, NO SMTP transcript — communicates more without wasting tokens.
  See `references/toutiao-cron-outage-2026-08.md` "Hybrid report shape".
- **Use a dedicated `outbox/` tree, not the scheduler's `output/` tree.**
  `~/.hermes/cron/output/<job_id>/` is the scheduler's own log directory;
  dropping backup artifacts there blurs "script ran" records with
  "content the user can still read" records, and the auto-rotation / log
  cleaners may eat your backups. Use `~/.hermes/cron/outbox/<platform>/`
  with one subdir per delivery platform (`toutiao/`, `wechat/`,
  `unified/`, `email/`) and a `README.md` in each explaining the most
  recent outage + the user-facing fix (regenerate QQ auth code, etc.).
- **Two-source-of-truth can both be stale.** When `config.yaml`'s `smtp_pass`
  and `~/.hermes/.env`'s `QQ_EMAIL_AUTH_CODE` were copied from the same QQ
  authorization code at setup time, a single revocation leaves BOTH dead.
  Just updating one won't help. Diff both against the live QQ web UI value
  before deciding the YAML is the canonical source. Pattern: `diff <(echo "$QQ_EMAIL_AUTH_CODE") <(grep smtp_pass ~/.hermes/cron/config/config.yaml | awk '{print $2}' | tr -d '"')` — if they match, you only have one
  credential to regenerate, not two.
- **QQ silent-reject has no `535` reply in the transcript.** Unlike the
  documented case study, a QQ anti-spam that aggressively revokes an auth
  code may close the TLS socket right after `AUTH` with no `reply:` line at
  all — `debuglevel=1` shows a clean EHLO then a bare `SMTPServerDisconnected`.
  Don't conclude "network problem" just because the 535 is missing.
  See the "Rarer edge case — QQ silent-reject (Case B)" callout in §5.
- **Manual AUTH LOGIN + `getreply()` is more reliable than `debuglevel=1`.**
  For QQ specifically, the default revocation signature (Case A) is a visible
  `535 Login fail. Account is abnormal...` line — but `debuglevel=1` can
  scroll past it because `smtplib` retries with AUTH LOGIN after AUTH PLAIN
  fails, and the second AUTH closes abruptly. Driving the SMTP session
  yourself with `server.send(b"AUTH LOGIN\r\n"); server.getreply()` per step
  prints each protocol reply on its own line — the 535 is deterministic.
  Prefer the manual recipe for terminal-typed probes, or when you suspect
  smtplib's AUTH retry is hiding the actual error. See Case I for the full
  transcript.
- **⚠️ `last_status=ok` does NOT mean the report was delivered (Case Y, 2026-10-24).**
  - The scheduler records `ok` because the *job* ran and produced a response; the
  *delivery* step is separate and its failure only surfaces in `last_delivery_error`.
  This deployment had BOTH channels broken at once: QQ SMTP dead 61 nights AND the
  Feishu `deliver: origin` route broken by a stale `omt_` thread_id (`99992402 field
  validation failed`, root cause `99992354 invalid open_message_id` — `omt_` is a thread……
  - 📄 完整案例叙事已下沉 → `references/pitfalls-compression-archive.md`（§last-status-ok-does-NOT-mean）
- **⚠️ A *content* cron has a second, quieter failure mode: the pipeline works but the product is bad (2026-10-28).**
  - Every symptom in this file is a *delivery* failure — SMTP 535, dead channel, false
  `last_status`. But a content cron can also fail **while every green light stays on**:
  the script exits 0, the Feishu attachment lands, the user receives a file — and that
  file is the same headline they received last cycle, or 400 characters short of the
  script's own checklist target. Nothing errors. Nothing looks wrong. The use……
  - 📄 完整案例叙事已下沉 → `references/pitfalls-compression-archive.md`（§A-content-cron-has-a-second-）
- **🔴 The audit tool can be DEAD and the session still reports "all green" (2026-11-05, 2 nights lost).**
  - The content linter (`lint_content_consistency.py`) crashed on **every** run for two
  consecutive nights — `NameError: check_orphan_character` (the `_self_test()` called a
  function that was never defined) — **and the ORPHAN rule it was supposed to enforce
  was never wired into `lint()` at all**. Both nights were recorded as "linter green,
  content clean". They were not: the linter never reached the check.
  **Roo……
  - 📄 完整案例叙事已下沉 → `references/pitfalls-compression-archive.md`（§The-audit-tool-can-be-DEAD-a）
- **⚠️ When a cron session's report says "audit passed", check the audit tool's own
    health at least once per session** — a green light from a tool you haven't run
    correctly is not evidence.
  - Full write-up (incl. the `PROMPT_HAS_CJK` and `PERIODIC_VS_YEARLY` rules added
    alongside the repair): `productivity/content-platforms/references/audit-tool-death-and-prompt-language.md`.
- **⚠️ Even a GREEN content audit can hide a broken product: check the arithmetic and the cast.**
  - A content cron's failure modes split cleanly into two halves, and this skill owns the
  **delivery** half. The **product** half — arithmetic, casts, promise fulfilment,
  cross-field consistency — is owned by **`content-platforms`**; do not re-derive it here.
  - **The cron-side rule that matters:** the article is assembled from multiple sources
    (pool entry + expansion paragraphs in a separate file), so a single-……
  - 📄 完整案例叙事已下沉 → `references/pitfalls-compression-archive.md`（§Even-a-GREEN-content-audit-c）
- **⚠️ A dead mail channel is not a dead content channel (2026-10-25, failure #62).**
  - `toutiao-article-daily.py` renders its own `CHECKLIST_ITEMS` list into a visible
  "发布前检查清单" block at the bottom of every article. When v1.1.0 changed the sender
  from `权权的HERMES（头条）` to `围炉家常话（头条）`, it updated `send_email()` but **not**
  the checklist string — so every article had been telling the user to verify a sender
  name the pipeline doesn't use. The checklist was not decoration this time; it was
  *shippin……
  - 📄 完整案例叙事已下沉 → `references/pitfalls-compression-archive.md`（§A-dead-mail-channel-is-not-a）
- **⚠️ Two pools that rotate in lockstep will eventually pair a story with its own twin.**
  - Two content pools advancing together can hand the reader the same story twice in
  consecutive nights — a *delivery-quality* failure that no channel error reports.
  **This skill's diagnostic contribution:** a green channel does not mean a green
  experience; check the *product* for repetition across nights, not just for transport.
  - **The full root-cause chain, the guard-window tuning table, and the
    before/aft……
  - 📄 完整案例叙事已下沉 → `references/pitfalls-compression-archive.md`（§Two-pools-that-rotate-in-loc）
- **⚠️ Measure the ASSEMBLED product, not an intermediate return value.**
  - A generator can look broken in an audit when the audit simply measures the wrong
  object — and the reverse is equally true: a green audit can be measuring the wrong
  object too. Two traps on `toutiao-article-daily.py`:
  1. `generate_article()` returns **only the long-form** HTML; the micro-article HTML is
     appended later inside `send_email()`. Auditing the return value ⇒ "micro-articles
     are missing!" — a……
  - 📄 完整案例叙事已下沉 → `references/pitfalls-compression-archive.md`（§Measure-the-ASSEMBLED-produc）
- **⚠️ The "don't re-run the script" rule (Case R) and the "fix the content" mandate are in tension — resolve it by fixing the code, not by re-running (2026-10-28).**
  - Case R says: if the outbox already has today's backup, do NOT run the script again
  (each extra run generates a *different* random topic and creates a second backup).
  But a session that audits the content and finds a defect still needs to ship the fix.
  The resolution that honours both:
  - **Do not re-run the production script** to prove the fix — that would duplicate
    today's already-delivered artifact.
  -……
  - 📄 完整案例叙事已下沉 → `references/pitfalls-compression-archive.md`（§The-don-t-re-run-the-script-）
- **✅ Cheap proof that the script fired exactly once — check the crontab log + the
  outbox together (2026-11-05).** Two independent signals, both one-liners:
  ```bash
  grep "toutiao-article-daily" /var/log/syslog | grep "$(date +%Y-%m-%d)" | tail -3
  ls -t ~/.hermes/cron/outbox/<platform>/*.html | head -1 | xargs stat -c '%y %n'
  ```
  If syslog shows **one** `CRON[...] CMD (python3 .../toutiao-article-daily.py ...)`
  line dated today AND the newest outbox HTML is dated today, classic cron fired
  exactly once → **0 runs allowed for the reporting session** (Case R). A single
  `grep -c` on the log is enough to rule out a double-fire; don't guess.
  Pair it with the outbox filename check (`YYYYMMDD_HHMM_<direction>.html` — one file
  per night) to confirm no second product was generated.
  Note the log line shows the **redirect target** (`>> .../logs/<script>.log`), so the
  same log file is the place to read the night's stdout/stderr without re-running
  anything.
- **✅✅ The session's job is a REPORT, not a run — verify the four signals in one
  pass, then spend the remaining budget on the product (2026-11-08 实测有效).**
  For a classic-cron-fired content cron, the reporting session should open with a
  **single combined check** rather than one probe at a time. The 2026-11-08 session
  did exactly this and never re-ran the script:
  ```bash
  # ① 当晚是否已跑（syslog 只看今天这一行）+ 产物是否已落盘
  grep "toutiao-article-daily" /var/log/syslog | grep "$(date +%Y-%m-%d)"
  ls -la --time-style=full-iso ~/.hermes/cron/outbox/toutiao/ | grep "$(date +%Y%m%d)"
  # ② 脚本自己的日志尾部（一次看到「选题 + 失败原因 + 落盘路径 + message_id」）
  tail -40 ~/.hermes/cron/logs/toutiao-article-daily.log
  # ③ 备用通道是否真的送达（抠出 message_id 回查，不要重跑脚本去拿）
  python3 ~/.hermes/cron/scripts/_verify_feishu_msg.py <message_id>
  # ④ 产物本身过一遍审计（注意单独看退出码，别用管道吞掉）
  python3 ~/.hermes/skills/productivity/content-platforms/scripts/audit_rendered_article.py <html> --pool <pool>
  ```
  **信号①里的 `message_id` 已经出现在脚本日志尾部** —— 不用重跑脚本就能拿到它。
  把它回查确认（`msg_type` / `deleted` / `file_name` 三项）才算「送达」，
  然后才把剩余预算花在**通读 + 修复**上。
  ⚠️ 这套顺序的价值在于：把「跑没跑/送没送到」（便宜、确定）先钉死，
  剩下的额度全部用于「内容对不对」（贵、才是真正需要 agent 智力的部分）。
- **🆕 2026-11-11 实测：这条顺序再加一条 —— 「**产物已经落盘**」要同时用
  **产物文件数 + 两个 history 文件的 mtime** 交叉验证，不能只看其中一个**。
  当晚 `ls 20261111*.html | wc -l` = 1 且两个 history 文件 mtime 都停在
  `20:30:01` ⇒ 确认 classic cron 恰好触发 1 次、本会话 0 次执行许可（Case R）。
  只数产物文件可能被「上次残留 + 今晚失败」骗过；只看 mtime 则无法证明没有
  第二个产物。**两个信号一起看，结论才成立。**
- **🔴 2026-11-11 实测：即使 audit / lint / 脚本 exit 全绿 + 备用通道已回查
  送达，产物仍可能有三类「跨字段·跨夜失配」硬伤** —— 那晚 `audit exit 0` /
  `lint exit 0` / 脚本 exit 0 / 飞书 `message.get` 回查 `msg_type=file` +
  `file_name` 全部正常，仍抓到跨夜同故事碰撞、钩子整句复读、金句标签对不上
  实际出处 3 类读者可见缺陷。**根因是现有规则全都在查「单字段内的算式」或
  「同一条内容内部的重复」，查不到「这条内容与另一条内容（另一晚）的关系」。**
  通用教训：**审计工具全绿 ≠ 跨字段关系正确**；夜间内容 cron 的通读必须包含
  **跨夜比对**（今晚的微头条 == 前/后几晚的长文？）+ **整句复读扫描**（钩子/
  标题句在正文里逐字出现？）。检测与修复代码见
  `productivity/content-platforms/references/cross-field-defect-detection.md`。
- **🆕 2026-11-09/11-10/11-11/11-12/11-13 实测：这条顺序持续有效（连续 5 晚验证）**。
  当晚实测有效顺序（与 11-08 的差别只在第 ③ 步）：
  1. **一条命令同时取四个信号**（syslog 当日行数 + outbox 落盘 + 脚本日志尾部 + 飞书回查）。
     syslog `count=1` + outbox 当日只有一个产物 ⇒ **classic cron 恰好触发 1 次 ⇒ 本会话 0 次执行许可**（Case R）。
  2. **回查送达用脚本自己日志里的 `message_id`** —— 从 `STANDBY_<日期>.txt` 或日志尾部抠，
     再用 `_verify_feishu_msg.py` 回查 `msg_type=file` / `deleted=False` / `content.file_name=<今夜那份>`。
     **`file_name` 比 `msg_type` 可靠**（能确认送的是不是今夜这一份）。
  3. **立刻追加 README**（`## YYYY-MM-DD（持续中 — 第N天）`），并用 `grep -c "^## "` 核验标题数 +1。
     11-09 实测：33 → 34（delta=1），无乱码字符。**这一步必须在内容审计之前做**——
     内容修复最容易耗尽工具调用额度。
  4. 然后才跑 audit / lint（退出码**单独看**），做手工通读，改源码，最后剪 outbox。
  5. **README 追加完后再回填「修复后的复核」段落**（lint exit 0 / 假阳性检测 exit 0 /
     定点断言条数 / 金句复读自查命中数 / 微头条字数区间 / 假阳性人工核对结论），
     再核验一次标题数 —— **同一天不要新增第二个 `## ` 标题**，把复核写进当天段落里。
- **🔴 Tool-green does not mean product-correct — and "all green" has been disproven repeatedly.**
  - Across many nights the full chain was green — `audit exit 0`, `lint exit 0`, script
  `exit 0`, backup channel confirmed delivered by `message.get` — and manual reading still
  found reader-visible defects. **The cron-side lesson is the meta-lesson:**
  - **Automation only covers defect families that have been encoded.** A new family is
    invisible to every tool until someone reads the prose and then encodes it.……
  - 📄 完整案例叙事已下沉 → `references/pitfalls-compression-archive.md`（§Tool-green-does-not-mean-pro）

## Cross-reference: known recurring outage

For the `toutiao-article-daily.py` QQ SMTP outage (20+ nights as of 2026-09-13, identical `Connection unexpectedly closed` every night, auth code `<revoked auth code>` revoked), see `references/toutiao-cron-outage-2026-08.md`. It contains the verbatim QQ-web-UI fix steps, the outbox cleanup recipe, the terse-report pattern from Case H, and Cases I/J/L for refined probe recipes. **If you see a `Connection unexpectedly closed` on `smtp.qq.com:465` for `569545015@qq.com`, read that file first — the credential is almost certainly already revoked and the outbox already has today's content.**

For Cases S+ (failure #34 onwards, 2026-09-27+), see `references/toutiao-cron-outage-2026-09.md` — the continuation log. **At every cron-session start, read the relevant `references/` files AND the outbox README** before any diagnostic — together they cover the full outage history. The consolidated per-night narrative (Cases G–P) is in `references/case-log-chronic-outage.md`.

### Outbox pruning when accumulation gets unwieldy (Case W, 2026-10-16, failure #53)

The chronic-outage cron is at failure #53; `~/.hermes/cron/outbox/toutiao/` had accumulated ~117 HTML files (~3 MB) plus 14 PENDING symlinks plus 4 STANDBY files. At this size, `ls` becomes slow and the directory is unusable as a quick "is there a backup?" check.

Pruning recipe — keep the last N days, preserve README + PENDING + STANDBY untouched:

```bash
# Keep last 14 days of HTML backups; delete older ones
KEEP_FROM=$(date -d '14 days ago' +%Y%m%d)
cd ~/.hermes/cron/outbox/<platform>/
ls -1 *.html 2>/dev/null | while read f; do
  fname="${f%.html}"
  datestr="${fname:0:8}"
  if [[ "$datestr" < "$KEEP_FROM" ]]; then
    rm -f "$f"
  fi
done
# Also delete the corresponding PENDING symlinks and old STANDBY entries.
# ⚠️ Date-offset traps (verified 2026-10-27, CORRECTED 2026-10-29):
#   - "PENDING_20261027.html" → date starts at index 8  → "${f:8:8}"  ✅
#   - "STANDBY_20261027.txt" → date starts at index 8  → "${f:8:8}"  ✅
#   ⚠️ An earlier version of this recipe said STANDBY used index 9. That was
#   WRONG: both "PENDING" and "STANDBY" are 7 characters, so both dates start
#   at index 8. Using index 9 on a STANDBY file yields "0261029." — which is
#   lexicographically < "20261015", so **the recipe deleted every STANDBY file,
#   including today's** (observed 2026-10-29: STANDBY count went 3 → 0).
#   ⚠️ ALWAYS verify the slice before deleting:
#       echo "${f:8:8}"   # must print a bare 8-digit date like 20261029
#   If it prints anything else (dots, a shifted digit), the offset is wrong.
ls -1 PENDING_*.html 2>/dev/null | while read f; do
  datestr="${f:8:8}"
  if [[ "$datestr" < "$KEEP_FROM" ]]; then rm -f "$f"; fi
done
ls -1 STANDBY_*.txt 2>/dev/null | while read f; do
  datestr="${f:8:8}"     # ⚠️ index 8, NOT 9 — see the offset-trap note below
  if [[ "$datestr" < "$KEEP_FROM" ]]; then rm -f "$f"; fi
done

# ⚠️ Deleting a PENDING symlink's target HTML orphans the symlink → broken link.
# Always sweep broken symlinks after pruning:
find . -maxdepth 1 -name "PENDING_*.html" -xtype l -delete
```

**Verification after pruning (never skip):**

```bash
cd ~/.hermes/cron/outbox/<platform>/
echo "HTML: $(ls -1 2026*.html 2>/dev/null | wc -l)  PENDING: $(ls -1 PENDING_*.html 2>/dev/null | wc -l)  STANDBY: $(ls -1 STANDBY_*.txt 2>/dev/null | wc -l)"
# every PENDING symlink must resolve
for f in PENDING_*.html; do [ -e "$f" ] || echo "BROKEN: $f"; done
# today's content + today's STANDBY must still exist
ls -la PENDING_$(date +%Y%m%d).html STANDBY_$(date +%Y%m%d).txt
```

**Don't prune without preserving the README's history.** The README's "持续中 — 第N天" entries are the cross-session memory; the user may want to read them when they finally fix the auth code to see how long the outage ran. The recipe above leaves `README.md` untouched.

**⚠️ Add a post-prune restore check for STANDBY files (2026-10-29).** The STANDBY
files are regenerated only when the script runs, so a bad prune deletes them
permanently — there is no backup to restore from. After pruning, if the STANDBY
count dropped to 0 (or below what you expected), **reconstruct the missing files
by hand** from the script's own `main()` template rather than skipping ahead:

```python
# Reconstruct a STANDBY file for a date whose HTML backup still exists
standby = (
    f"📰 头条号今日文章（QQ SMTP 535 限频/授权码失效，已自动备份）\n"
    f"选题：{title}\n"
    f"方向：{direction}\n"
    f"时长：长文 + 2 条微头条\n"
    f"HTML：/home/ubuntu/.hermes/cron/outbox/toutiao/PENDING_{date}.html\n"
    f"原因：{reason}\n"
)
```
The `title`/`direction`/`reason` are all recoverable: title and direction are in
the backup HTML's banner, and the reason string is in the matching
`STANDBY_*.txt` reference inside the scheduler output log
(`~/.hermes/cron/output/<job_id>/*.md`) or in `~/.hermes/cron/logs/*.log`.

**Why 14 days:** enough to give the user a meaningful buffer of "I haven't read these yet" articles when they finally fix the credential and want to sweep history with `scripts/resend_outbox_html.py --all`, but small enough to keep `ls` instant. Tune by storage size: at ~27 KB per HTML, 14 days = ~380 KB per platform, very manageable.

**Anti-pattern: don't write a Python script to do this.** A bash one-liner is correct; a `.py` script over-engineers a 30-second cleanup. Case P warned against bespoke platform-specific scripts; same applies to one-off cleanup tools.

### The cleanup paradox at high N (Case W)

At failure #53 the cron-session agent did everything right — ran the script
once (agent-mode = one canonical run), delivered the terse report, pruned the
outbox — and still **skipped the README extension**, because the report
already felt "done". That is the trap at high N: the report is the visible
artifact, but the README is the durable one.

The rule, and the check that catches a skip, are in the **Escalation policy**
below. The full failure narrative is in
`references/case-log-chronic-outage.md` (Case W).


## Escalation policy — chronic-outage dispatch by failure count

A recurring failure is a *reporting* problem as much as a technical one. The
report must shrink as the failure count climbs: the user has already been told
N times, so each additional report should carry only what is new.

**Read the outbox README first** (`~/.hermes/cron/outbox/<platform>/README.md`).
It is the cross-session memory — it holds the outage history, the verbatim fix
steps, the blast radius, and the last "第N天" marker. Probes are *confirmation*,
not investigation. At N≥3 a README that still says "持续中" with no "已恢复"
entry means: skip the diagnostic loop entirely and dispatch.

| Failure count | Probe? | Article inline? | Report shape |
|---|---|---|---|
| 1–2 | Yes, full probe | Yes, full article | Full diagnostic + article |
| 3–9 | One confirmation probe | Title + hook only | Standard report + outbox-detection callout |
| 10–19 | Skip — README already says it | **No** | 4-line terse dispatch + outbox path |
| ≥20 | Skip — pure ceremony | No | Terse + `last_status=ok` masking warning |
| ≥25 | Skip | No | Terse + cross-script blast-radius count + one-line fix |
| ≥30 | Skip | No | Terse + scheduler-masking diagnosis + runbook entry |
| ≥50 | Skip | No | Terse + outbox pruning + **mandatory** README extension |

The 4-line terse dispatch (Case H shape):

```
📋 <pipeline>日报（N天连续失败）
✅ 内容生成成功 → outbox/<platform>/YYYYMMDD_HHMM_<direction>.html
❌ 邮件未送达：QQ SMTP 535 Login fail（auth code <code> 第N天）
🔧 修复：mail.qq.com → 账户 → SMTP服务 → 重新生成授权码 → 写回 ~/.hermes/cron/config/config.yaml
```

**Never inline the article after night 3.** The outbox already has it; pasting
1500+ words into a chat channel is token-burn on both sides.

**The README extension is a mandatory terminal action.** The cron report rides
the agent's `deliver` channel and scrolls past; the README persists. After every
session on a failing cron, append a `## YYYY-MM-DD（持续中 — 第N天）` block.
Verify with `grep -c "^## " ~/.hermes/cron/outbox/<platform>/README.md` — the
count must increase by 1. Skipping this breaks the cross-session memory chain
and is the single most common way a chronic outage loses its history.

**Run-count rule (agent-mode vs script-mode).** How many times you may run the
script depends on which scheduler fired:

| Scheduler mode | Pre-existing outbox backup? | Runs allowed |
|---|---|---|
| Classic cron (`crontab.txt`) | Yes | **0** |
| Hermes `no_agent` script-mode | Yes | **0** |
| Hermes agent-mode prompt | **No — you ARE the run** | **1, exactly** |

Each extra run generates a *different* random topic and a second outbox file.
Check `ls -t ~/.hermes/cron/outbox/<platform>/*.html | head -1` first: if the
newest backup is dated today, do not re-run.

**Outbox pruning when accumulation gets unwieldy.** Keep the last ~14 days of
HTML backups; preserve README + PENDING + STANDBY. Beware the date-offset trap:
`PENDING_YYYYMMDD.html` starts its date at index **8** (`${f:8:8}`) and so does
`STANDBY_YYYYMMDD.txt` (`${f:8:8}`) — both prefixes are 7 characters. Getting
this wrong deletes today's STANDBY file (observed 2026-10-29). Always sweep broken symlinks afterwards with
`find . -maxdepth 1 -name "PENDING_*.html" -xtype l -delete`, and verify every
PENDING symlink still resolves. Prefer a bash one-liner over a bespoke Python
script for this cleanup. Full recipe: `references/case-log-chronic-outage.md`.

**Where the per-night history lives.** The full case-by-case narrative (Case G,
H, I, J, R, M, N, O, P — one section per cron-run session, with its date, its
"Today's run" log, and the reasoning behind each rule above) is in
`references/case-log-chronic-outage.md`. That file also opens with a distilled
table of all 20 durable lessons from those sessions. Read it when you need the
*history* or the *reasoning*; do not read it as step 1 of a live outage.

Related case-detail references:
- `references/no-agent-false-error-reporting.md` — `no_agent` scripts that succeed (exit 0) but are reported as `last_status: error`; the mirror image of the `last_status=ok` masking case
- `references/duplicate-scheduled-task-detection.md` — duplicate deliveries: `jobs.json` vs `crontab.txt` overlap, same-purpose scripts under different names, stale brand/identity strings
- `references/toutiao-cron-outage-2026-08.md` — the original outage (Cases A–F)
- `references/toutiao-cron-outage-2026-09.md` — continuation log (Cases S+, failure #34+)
- `references/toutiao-cron-outage-2026-10-week4.md` — Cases X/Y/Z (failure #59+)
- `productivity/content-platforms/references/topic-pool-rotation-and-length-engineering.md` — **content-quality failures that stay green**: pool sizing, LRU rotation, length assertions, `str.format()` silent-drop check (companion to the delivery-side references above)
- `productivity/content-platforms/references/orphan-extensions-and-hand-arithmetic-audit.md` — **孤儿扩写 + 人工算账审计**：扩写段落整个换成另一个故事；自动化审计全绿但手工通读抓到 9 处硬伤。含 ORPHAN 检测规则的三次踩坑、通读要盯的 6 条链、批次替换原子性陷阱
- `productivity/content-platforms/references/audit-tool-death-and-prompt-language.md` — **审计工具自己死了**（linter 连坏 2 晚，退出码被管道吞掉 →「全绿」是假的；「写了函数 ≠ 规则生效」）+ 配图提示词混中文 + 周期频次 vs 年度汇总。**跑审计工具必须单独看退出码**
- `productivity/content-platforms/references/hook-promise-and-title-payoff-audit.md` — **钩子承诺不兑现（标题党翻车）**：钩子/标题承诺的画面、引语、数字正文一个字都没写 → 读者点进来想看的东西看不到。2026-11-06 实测 10/10 长文命中且全程绿灯。内容侧的「单字段自洽、跨字段失配查不到」盲区。**2026-11-07 已落地 `HOOK_PROMISE` 规则**（实测会 fire），并记录了规则自身「装配口径只认 story_* → 微头条池整池假阳性」的坑
- `productivity/content-platforms/references/character-lifecycle-and-timeline-chain-audit.md` — **缺陷十一「人物生死状态链断裂」+ 缺陷十二「时间线链打架」**：已故角色仍在对话里说话（死人复活）、同一事件两个时点（丧事当天 vs 三个月后）。2026-11-10 实测，audit/lint/脚本全绿 + 飞书已送达仍靠通读抓到 10 处硬伤。含**通读清单 8 条链 → 10 条链**（新增⑨角色生死状态链、⑩时间线链）、⚠️ **`lint --pool` 必须指向生成器脚本本身，指向池数据文件会 exit 2（参数用错 ≠ 内容有问题）**、按事件关键词全池回扫
- `productivity/content-platforms/references/golden-echo-and-label-provenance-audit.md` — **金句复读 + 金句标签对不上实际出处（第九类跨字段失配）**：同一句金句在 viewpoint/action/结局里被整句复读 → 读者在同一篇里看到同一段话连说两遍；且模板把 `golden1/2/3` 标成【故事A结尾】/【故事B结尾】/【文章结尾】，但金句是按**池槽位**写的、不是按**实际出处**写的 —— 14 条长文实测 0 条真落在标注位置。2026-11-08 实测命中 27 处，全程绿灯。**2026-11-08 已落地 `GOLDEN_ECHO` 规则**（实测会 fire）。通用教训：「摘要卡 + 正文」型结构天然产生复读缺陷，规则要按「跨字段重复」查而不是按「字段内自洽」查
- `productivity/content-platforms/references/cross-field-defect-detection.md` — **缺陷十三/十四/十五「跨字段·跨夜失配」**：跨夜同故事碰撞（`SHADOW_MAP` 只挡当晚，挡不住「前一晚的长文 == 今晚的微头条」，60 天模拟 20%）、钩子整句在正文里逐字复读（`HOOK_PROMISE` 只查「有没有兑现」）、金句出处标注对不上实际出处（9/20 不符）。含**守卫夜数调参表**（3/3 碰撞 0/60 且两池覆盖 10/10；5/5 会把微头条覆盖压到 4/10）、**检测与修复代码**、以及「必须调用真实生产函数而不是在测试脚本里复刻逻辑」的踩坑
- `productivity/content-platforms/scripts/check_pool_type_false_positives.py` — **跨池型假阳性检测器**：给 linter 加完新规则后跑它，逐池把「命中项 + 该池正文字段」并排打出来供人工核对。退出码 2 = 装配不出正文 = 该池字段结构不匹配 = 假阳性来源。⚠️ 不要只看汇总数
- `scripts/send_email_with_outbox.py` — **可直接 import 的发送封装**（`send_email_with_outbox`）：给裸 `smtplib.SMTP_SSL().login().sendmail()` 补上「瞬时故障重试一次（3s backoff）+ 最终失败落盘 outbox 并把绝对路径写进错误串」两段逻辑。cron 脚本里 `from send_email_with_outbox import send_email_with_outbox as send_email` 即可，行为与本技能 §6 的模板一致（2026-08-25 第三次 QQ 授权码失效后写的）
- `scripts/resend_outbox_html.py` — 授权码修复后补发 outbox 里的历史 HTML
- `scripts/probe_smtp.py` — SMTP 凭据探针（465-SSL + 587-STARTTLS，判别 535 / silent-reject / connect 失败三种形态）
- `productivity/content-platforms/scripts/verify_cross_night_collisions.py` — **跨夜同故事碰撞验证器**：检测内容 cron 的「长文 ↔ 微头条」两池跨夜撞同一故事。**支持 `--before-script` 反向对照**（用旧脚本备份跑「修复前」配置，证明改动真的带来了行为变化，而不只跑「现在 0 次」）。全程只读生产 history，零污染
- `references/pitfalls-compression-archive.md` — **Pitfalls 完整案例叙事归档**：SKILL.md 里被压缩下沉的 20 条长案例的逐字原文（按 `§标签` 索引）。SKILL.md 正文只留可执行规则 —— 两者配合读
- `references/smtp-credential-failure-case-study.md` — full SMTP transcripts
- `references/case-m-last-status-masking.md` — `last_status=ok` masking
- `references/feishu-stale-thread-id-delivery-failure.md` — stale `omt_` thread_id
- `references/outage-readme-template.md` — README entry template
- `references/readme-append-truncation-disaster.md` — **2026-11-16 事故：「读-改-写」追加 README 把 822 行截成 513 行、14 段历史消失**。含 `read_file` 500 行静默截断的机制、`cat >>` / `open('a')` 的正确写法、**从 `~/.hermes/state.db` 的 `messages.tool_calls` 逐段还原**的完整代码（三个坑：JSON 转义层 / 按工具类型取值 / 同夜多候选去重）、以及三道追加后核验。⚠️ 只增不减的日志文件（outbox README / `topic_history.json` / `jobs.json`）**只追加，绝不读改写**
- `references/qq-smtp-rate-limit-pitfall.md` — rate-limit variant
- `references/script-not-found-case-study.md` — **path-resolution case study（2026-11-18 修订：原「绝对路径」修法已失效，软链接会被 resolve() 守卫拦截且会分裂状态文件；唯一可行解是 wrapper 文件）**
- `scripts/verify_cron_scripts.py` — **一键验证 no_agent job 的脚本真的能跑**：驱动调度器自己的 `_run_job_script()`（复刻 resolve → 目录守卫 → 存在性 → 解释器 → cwd → env 全链路），并把「SMTP/凭据等下游失败」与「路径本身失败」分开判定（前者记为 `PASS_PATH`）。**`ls` 只能证明文件在，不能证明调度器跑得动 —— 验证必须用它**。用法：`python3 verify_cron_scripts.py [--json]`
- `templates/cron_wrapper_python.py.tmpl` / `templates/cron_wrapper_shell.sh.tmpl` — **wrapper 模板**：复制到 `~/.hermes/scripts/<rel_dir>/<name>.py|.sh` 并替换 `__NAME__` / `__REAL_PATH__` 占位符。改脚本路径时直接复制模板，不要手敲
- `productivity/content-platforms/scripts/audit_rendered_article.py` — **产物审计脚本**：测已渲染 HTML 的正文中文数、结构完整性、配图数与 `no text`、标签数、微头条 `content` 字数区间（`--pool` 核对选题池，`--json` 机器可读）。改生成器后跑它，别手写正则数字数
- `productivity/content-platforms/references/topic-pool-rotation-and-length-engineering.md` — 内容质量四缺陷（池子/LRU/`str.format()`/清单漂移）+ **两个测量陷阱**（要测装配后的产物；微头条字数测 `content` 而非渲染块）

## Recovery scripts (for after the credential is fixed)

```bash
# 1. Verify the new credential works before doing anything else
python3 ~/.hermes/skills/cron-job-debugging/scripts/probe_smtp.py

# 2. Push the latest outbox backup through the new credential
python3 ~/.hermes/skills/cron-job-debugging/scripts/resend_outbox_html.py toutiao

# 3. (Optional) sweep ALL accumulated backups for that platform
python3 ~/.hermes/skills/cron-job-debugging/scripts/resend_outbox_html.py toutiao --all

# 4. (Optional) re-send a specific file by name
python3 ~/.hermes/skills/cron-job-debugging/scripts/resend_outbox_html.py toutiao --file 20260920_2030_房产纠纷.html
```

`resend_outbox_html.py` is platform-agnostic — replace `toutiao` with `wechat`, `xhs`, `unified`, or `email` to target a different outbox subdir. The script reads the same `~/.hermes/cron/config/config.yaml` the cron scripts use; no edit needed when the auth code is rotated. Reference: Case P.

## Diagnostic commands cheatsheet

```bash
# Before ANY diagnostic on a known-recurring cron: read the outbox README
read_file ~/.hermes/cron/outbox/<platform>/README.md
# If it ends with "持续中" and no "已恢复", jump to Case H dispatch — skip everything below.
# List all jobs including paused
hermes cron list --all

# Check scheduler status
hermes cron status

# View the newest log for a job
LATEST=$(ls -t ~/.hermes/cron/output/<job_id>/ | head -1)
cat ~/.hermes/cron/output/<job_id>/$LATEST

# Find where a script actually lives
find ~/.hermes -name 'skill-backup.sh' -type f 2>/dev/null

# Check expected vs actual scheduler resolution
echo "Expected: ${HOME}/.hermes/scripts/<script-field-as-stored>"
test -f "${HOME}/.hermes/scripts/<script-field-as-stored>" && echo "OK" || echo "MISSING"

# 🔴 GROUND TRUTH: run the scheduler's own entry point (resolve + guard +
# interpreter + cwd + env). Use THIS to verify a script-mode job actually runs —
# `ls` proves existence, not runnability.
cd ~/.hermes/hermes-agent && python3 -c "
import sys; sys.path.insert(0, '/home/ubuntu/.hermes/hermes-agent')
from cron.scheduler import _run_job_script
ok, out = _run_job_script('cron/scripts/<name>.py')
print('success:', ok); print(out[:800])
"

# ⚠️ After fixing paths, check for STATE-FILE SPLITTING (symlink fix causes it):
ls -la ~/.hermes/cron/scripts/.<name>_visited.json \
       ~/.hermes/scripts/cron/scripts/.<name>_visited.json 2>&1

# Trigger the job manually
hermes cron run <job_id>

# Tail the most recent output file across all jobs
tail -n 20 ~/.hermes/cron/output/*/*.md | head -50
```
