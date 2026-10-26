## Case X — Failure #59 (2026-10-19): chronic outage continues, content pipeline healthy, credential diagnosis confirmed

The `toutiao-article-daily.py` cron failed for the **59th consecutive night** since 2026-08-25. Same auth code (`iylylmwnitbbbebi`), same `Connection unexpectedly closed` from `smtp.qq.com:465`. Today's session added three things worth recording:

### Lesson 1 — Direct 535 capture via debug-level probe (Case K companion)

The `scripts/probe_smtp.py` Case K test uses correct vs. wrong password to disambiguate IP-block vs. credential. This session ran `smtplib.SMTP_SSL` with `set_debuglevel(2)` to capture the full transcript, which revealed QQ's actual 535 message verbatim:

```
535 Login fail. Account is abnormal, service is not open, password is incorrect,
   login frequency limited, or system is busy. More information at
   https://help.mail.qq.com/detail/108/1023
```

This is **5 enumerated possibilities** QQ returns with a single code, which makes blind recovery harder. Two heuristics to narrow:

1. **"password is incorrect"** vs **"login frequency limited"**: If the auth code worked within the past 30 days (check `git log -p ~/.hermes/cron/config/config.yaml`), it's *probably not* password — it's rate-limit / service-not-open / abnormal-account. If the auth code is older than 30 days, regenerate first (QQ授权码 typically expires after ~30 days for some configurations).
2. **"system is busy"** vs **"service is not open"**: If probe works on port 25 (often more lenient), the 465/587 ports are throttled, not the credential.

The `probe_smtp.py` script does NOT extract this 535 message text — future patch should `print(e.smtp_error.decode())` when `SMTPAuthenticationError` fires, so the agent can pattern-match against the 5 reasons.

### Lesson 2 — 30-byte minimal email test = a free credential liveness check

A 30-byte email (`MIMEText('hermes cron test <timestamp>', 'plain', 'utf-8')`) sent through the same `SMTP_SSL` flow as the full HTML is essentially free (sub-second), and proves the credential is alive *regardless of message size or content*. If the minimal email also fails 535, the credential is dead — no need to retry the full HTML. This is faster than `probe_smtp.py` because it goes through `sendmail()` rather than stopping at `login()`.

Add to `scripts/probe_smtp.py` as a `--send-canary` flag that sends a 1-byte Subject email after successful login, to prove end-to-end credential liveness.

### Lesson 3 — Cron prompt is authoritative for content direction (not the skill)

The cron prompt sent each night states:
- 选题方向：养老、遗产、赡养、亲戚恩怨（头条中老年男性用户最爱）
- 长文吃流量，故事要完整，观点要犀利

These are **already encoded** in `references/toutiao-article-daily.md` (选题库特征 + 检查清单) and in the `TOPICS_POOL` / `MICRO_TOPICS_POOL` of the script. But agents reading the cron prompt afresh might be tempted to "improve" by adding hot-search-driven topics (unified-style) or expanding to other demographics. **Don't.** The Toutiao pipeline is deliberately **not** part of the hot-search pipeline — it's a fixed-topic rotation optimized for an audience the user has explicitly carved out. The cron prompt re-asserts this every night; treat it as load-bearing, not ignorable.

### Today's run (2026-10-19, failure #59)

- **Generated**: 长文《69岁老人把房子过户给儿子后，儿媳说"这房子是我们的，你凭什么住"》（房产纠纷方向）+ 微头条《我65岁，存款30万，退休金3000……》《我60岁，找了个老伴……》
- **HTML backup**: `~/.hermes/cron/outbox/toutiao/20261019_2030_房产纠纷.html` (27 KB, 331 行, 21 段正文). 标题、钩子、长文结构完整 — 内容生成100%正常
- **STANDBY log**: `~/.hermes/cron/outbox/toutiao/STANDBY_20261019.txt` (~500 B)
- **Resend script**: ran `resend_toutiao_today.py` which tries SSL465 + STARTTLS587 — both returned `SMTPServerDisconnected`
- **Direct probe**: `smtplib.SMTP_SSL` with debuglevel=2 → captured 535 verbatim
- **Minimal email probe**: 30-byte email → also 535, confirming credential is the failure mode
- **PENDING backlog**: still 16+ dates (Sept 10/03 → 2026-10/19), chronic outage unchanged
- **Outbox pruning**: NOT done today (Case W prune already done at N=53; size hasn't crossed the next prune threshold)
- **README extension**: REQUIRED per Case W Lesson 2 — append `## 2026-10-19（持续中 — 第59天）` block

### Updated decision rule (N=59)

| Failure count | Probe? | Article inline? | Outbox pruning? | README extension? | Report shape |
|---|---|---|---|---|---|
| 1-2 | Full probe | Yes | No | Yes | Full Case F + article |
| 3-9 | One confirmation | Title + hook only | No | Yes | Case F + outbox-detection callout |
| 10-19 | Skip | NO — outbox path only | No | Yes | Case H terse |
| 20-29 | Skip | NO | No | Yes | Case H + masking warning |
| 30-49 | Skip | NO | No | Yes | Case L + blast radius |
| 50-52 | Skip | NO | No | Yes | Case L + outbox prune warning |
| ≥53 | Skip | NO | Yes (one-time, 14-day keep) | **Yes — mandatory** | Case H terse + pruning confirmation |
| **59 (today)** | Skip (just probe 1× for transcript) | NO | No (already pruned at 53) | **Yes — mandatory** | Case H terse + 535 verbatim + credential status |

### Open question

The user (system) explicitly stated topic preferences in the cron prompt every night. This is **load-bearing** — the Toutiao script deliberately does NOT participate in the hot-search-driven content pipeline that the unified script uses. Future agents who see a "drop" in topic diversity should NOT add hot-search topics to the toutiao rotation; that's a different product for a different audience. The cron prompt is the authoritative spec; the script's `TOPICS_POOL` is the canonical implementation.

---

## Case Y — Failure #62 (2026-10-25): Feishu native-attachment delivery + a silent template-drop bug

Two genuinely new findings this cycle. The first gives the user their content back **without waiting for the revoked QQ auth code**; the second is a content bug that had been silently corrupting every article since v1.1.0.

### Finding 1 — Feishu native-attachment delivery works (email-free content path)

The QQ SMTP line has been dead 62 nights. But the 10-24 session repaired the **Feishu** `deliver` route (`feishu:oc_39c71fb71c2db9be002545966567498f`, `thread_id=None`). That route can carry files, not just text.

**The working recipe** (uses Hermes' own delivery path, so it matches what the scheduler does):

```python
import asyncio, os, sys
sys.path.insert(0, "/home/ubuntu/.hermes/hermes-agent")
# load ~/.hermes/.env into os.environ (FEISHU_APP_ID / FEISHU_APP_SECRET)

from gateway.config import Platform, load_gateway_config
from tools.send_message_tool import _send_to_platform

cfg = load_gateway_config()
pconfig = cfg.platforms.get(Platform.FEISHU)
res = asyncio.run(_send_to_platform(
    Platform.FEISHU, pconfig,
    "oc_39c71fb71c2db9be002545966567498f",   # chat_id
    "🏠 围炉家常话 · 头条号 | <caption>",
    thread_id=None,
    media_files=[("/abs/path/article.html", False)],   # (path, is_voice)
))
# -> {'success': True, 'message_id': 'om_x100b62eb37c1fc20dd682b8b7132015'}
```

**Verification** (don't trust the return value alone — read the message back):

```python
req = lark.im.v1.GetMessageRequest.builder().message_id(msg_id).build()
resp = client.im.v1.message.get(req)
# confirm: msg_type == 'file', deleted == False,
#          body.content contains {"file_key": "...", "file_name": "....html"}
```

**Gotchas:**

- **`.html` is NOT in the `MEDIA:` regex extension whitelist** (`base.py::extract_media` allows png/jpg/gif/webp/mp4/…/pdf/zip/docx/txt/csv — no html). But `.html` **IS** in `extract_local_files`'s `_LOCAL_MEDIA_EXTS` list. And Feishu's `file_type=stream` accepts arbitrary files, so a bare absolute path to an `.html` file is delivered as a native attachment. If you're constructing the request manually, pass it via `media_files` (not by relying on `MEDIA:` regex extraction in the agent response).
- **SDK class names**: `lark.im.v1.GetMessageRequest` (top-level `lark.im.v1`, NOT `lark.im.v1.message.GetMessageRequest`). Same for `CreateFileRequest` — the adapter's `_build_file_upload_request` handles both shapes via a `globals()` check, which is why the adapter path works when hand-written SDK calls don't.
- **Don't double-deliver.** Push once, verify, and if you pushed a pre-fix version, **delete it** (`lark.im.v1.DeleteMessageRequest`) so the user doesn't get two near-identical files.
- **Feishu vs the email recipient**: this delivers to the Feishu chat, NOT to `569545015@qq.com`. It's a channel substitution, not a fix for the mailbox. Say so explicitly in the report — the QQ auth code still needs regenerating if the mailbox is the destination that matters.

**Permanent fix applied**: `toutiao-article-daily.py::send_email()` now calls a new `_try_feishu_attachment(html_path, topic)` helper on SMTP failure, so every future night auto-pushes the HTML as a Feishu attachment. The error string becomes `[QQ SMTP 限频] Connection unexpectedly closed (HTML已备份: …) / 飞书附件投递成功 (message_id=…)`.

### Finding 2 — `str.format()` silently drops kwargs the template doesn't use (the story was never complete)

`HTML_TEMPLATE` had placeholders for only `{story_a_content}` and `{story_b_content}`. The data model also carries `story_a_dialogue`, `story_a_ending`, and `story_b_ending` — and `generate_article()` **passed all three into `.format()`**. But `str.format()` **does not raise on unused kwargs** (it only raises on *missing* placeholders). So the three fields were accepted and silently thrown away.

**Impact**: since v1.1.0, every single article shipped with its story dialogue and both story endings missing — story A collapsed from ~800 to ~490 chars. This directly violated the cron prompt's 「故事要完整，长文吃流量」 requirement, and it was invisible for 62 nights because the failure was a *content* failure, not a *delivery* failure. Nothing errored; the HTML just got quietly worse.

**Detection recipe (use this after ANY template/generator edit):**

```python
import re
h = open('/home/ubuntu/.hermes/cron/outbox/toutiao/<latest>.html', encoding='utf-8').read()
probes = {
  "story_a_dialogue": "<first 10 chars of the dialogue string>",
  "story_a_ending":   "<first 10 chars of the ending string>",
  "story_b_ending":   "<first 10 chars of the ending string>",
}
for k, v in probes.items():
    print(f"  {k:20s} present: {v in h}")
t = re.sub(r'<[^>]+>', '', h)
print("  Chinese chars:", len(re.findall(r'[\u4e00-\u9fff]', t)))
```

**Rule:** `str.format(**kwargs)` raises `KeyError` for a missing placeholder but is **silent** about a kwarg that no placeholder references. Therefore *every* generator template change must be followed by reading the rendered output back and grepping for the key content. A green "renders without error" is NOT proof that the content is complete. Verify the *product*, not the *process*.

**Fix applied**: added three placeholders + three labelled sections (`【故事A·对话】`, `【故事A·结局】`, `【故事B·结局】`) to `HTML_TEMPLATE`, and mirrored them in the `plain_text` variant. Re-render went from 2577 → 2789 Chinese chars (+212) with all three sections verified present.

### Case W README-extension check

`grep -c "^## " ~/.hermes/cron/outbox/toutiao/README.md` → 19 after this session (was 18). Extension confirmed.

### Outbox pruning gotcha (self-inflicted)

The Case W prune recipe uses `datestr="${fname:8:8}"` for `PENDING_<date>.html` and `"${s:9:8}"` for `STANDBY_<date>.txt`. The second offset is **wrong**: `STANDBY_20261025.txt` has the date starting at index **8** (eight characters `S-T-A-N-D-B-Y-_`), not 9. Using `:9:8` sliced off the first digit of the date, produced an inconsistent comparison, and **deleted today's STANDBY file**. Always verify the slice offset against the actual filename length before mass-deleting, and re-create the current day's STANDBY after any prune.

### Updated decision rule (N=62)

| Failure count | Probe? | Article inline? | Feishu attachment? | Outbox pruning? | README extension? |
|---|---|---|---|---|---|
| 1-9 | Yes | Yes | Yes | No | Yes |
| 10-29 | Skip | NO | Yes | No | Yes |
| 30-52 | Skip | NO | Yes | No | Yes |
| ≥53 | Skip | NO | Yes | Yes (14-day keep) | **Yes — mandatory** |
| **62 (today)** | Skip | NO | **Yes — implemented + verified** | Yes | **Yes — done (19 entries)** |

### Today's run (2026-10-25, failure #62)

- **Generated**: 长文《72岁老人存了40万，遗嘱写好两年，去世后三个子女差点打起来》（遗产分配方向）+ 微头条《随了20年份子钱，我终于想明白了：有些人，你永远还不起》《大伯供我上大学，花了15万。我工作第一件事，是把他屏蔽》
- **Cron trigger**: classic crontab fired once at 20:30:02 (遗产分配). Agent-mode report session did **not** re-run the script (Case R rule — outbox mtime confirmed today's content already existed).
- **HTML backup**: `20261025_2030_遗产分配.html` (fixed version, 2789 Chinese chars)
- **Feishu delivery**: SUCCESS — `om_x100b62eb37c1fc20dd682b8b7132015`, `msg_type=file`, `deleted=False`, file_name `20261025_2030_遗产分配.html`
- **Content bug fixed**: `story_a_dialogue` / `story_a_ending` / `story_b_ending` now render (see Finding 2)
- **Permanent Feishu fallback added** to `toutiao-article-daily.py::send_email()`
### Outbox after prune: 55 HTML + 23 PENDING + 1 STANDBY, 944 KB

---

## Case Z — Failure #63 (2026-10-26): the Feishu fallback silently broke under classic cron, and the topic pool had no rotation

Two bugs found and fixed. The first is a **verification gap** in Case Y's own recipe; the second is a **content-quality** bug that had been hurting traffic for weeks without anyone noticing.

### Finding 1 — Case Y's Feishu recipe only works under the venv interpreter

Case Y's `_try_feishu_attachment()` imported Hermes' delivery module **in-process**:

```python
from gateway.config import Platform, load_gateway_config
from tools.send_message_tool import _send_to_platform
```

That needs `lark_oapi`, which is installed **only** in `~/.hermes/hermes-agent/venv` — not in `/usr/bin/python3`. Classic crontab runs the script with `/usr/bin/python3`:

```
30 20 * * * python3 /home/ubuntu/.hermes/cron/scripts/toutiao-article-daily.py >> .../toutiao-article-daily.log 2>&1
```

So every classic-cron night the fallback returned `Feishu dependencies not installed` and the user got **nothing but an outbox file**. On 2026-10-25 the fallback *worked* — because that session ran the script by hand under the venv python, where `sys.executable` happened to be the venv. **The manual test masked the environment difference.** This is the same class of bug as "verified by hand, broken in production."

**Detection recipe** (whenever a cron script's fallback channel "worked yesterday but not tonight"):

```bash
# Which interpreter does classic cron actually use?
env -i /bin/sh -c 'command -v python3; python3 -c "import sys; print(sys.executable)"'
# → /usr/bin/python3

# Does that interpreter have the dependency the fallback needs?
/usr/bin/python3 -c "import lark_oapi" 2>&1 | tail -1
# → ModuleNotFoundError: No module named 'lark_oapi'

# Which one does have it?
/home/ubuntu/.hermes/hermes-agent/venv/bin/python3 -c "import lark_oapi; print('OK')"
```

**Fix — make the fallback interpreter-agnostic.** Extract the delivery logic into a standalone module and call it as a **subprocess with an explicit interpreter**:

```python
# toutiao-article-daily.py::_try_feishu_attachment
venv_python = '/home/ubuntu/.hermes/hermes-agent/venv/bin/python3'
python_bin = venv_python if os.path.isfile(venv_python) else os.sys.executable
proc = subprocess.run([python_bin, helper, str(html_path), caption, chat_id],
                      capture_output=True, text=True, timeout=90)
```

New file `~/.hermes/cron/scripts/_feishu_deliver.py` — importable *and* executable:
- `deliver(html_path, caption, chat_id)` → `(ok, message)`
- CLI: `python3 _feishu_deliver.py <abs_html_path> "<caption>" [chat_id]`

**Verification (must use the cron interpreter, not the venv):**

```bash
/usr/bin/python3 -c "
import importlib.util
spec = importlib.util.spec_from_file_location('t','/home/ubuntu/.hermes/cron/scripts/toutiao-article-daily.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
print(m._try_feishu_attachment('/abs/path/article.html', {'direction':'X','title':'Y'}))
"
# → 飞书附件投递成功 (message_id=om_...)
```

Then read the message back via `lark.im.v1.GetMessageRequest` → confirm `msg_type == 'file'`, `deleted == False`, `file_name` matches.

**Rule: a fallback that runs in-process inherits the *caller's* interpreter. If the caller may be a different interpreter than the one that has the dependency, the fallback must spawn its own.** Always test the fallback with the *cron's* interpreter, not the interactive one.

### Finding 2 — `random.choice()` on a 6-item pool with no history = the same headline 5 days in a row

`TOPICS_POOL` has 6 long-form topics. `generate_article()` did `topic = random.choice(TOPICS_POOL)` with no memory. Auditing the outbox filenames for the last 7 days:

```
10-21 赡养义务   10-22 赡养义务   10-23 赡养义务 + 房产纠纷
10-24 房产纠纷   10-25 遗产分配   10-26 赡养义务
```

赡养义务 ran **5 of 7 days**, and every run emitted the byte-identical headline *"67岁老人被三个儿子轮流养老，每家住四个月，第三家说'住够了'"*. For a pipeline whose stated purpose is 「长文吃流量」, replaying the same headline to the same audience is a direct traffic loss — returning readers see a duplicate and scroll past.

**Fix — history-backed rotation:**

```python
HISTORY_FILE = '/home/ubuntu/.hermes/cron/outbox/toutiao/topic_history.json'
MICRO_HISTORY_FILE = '.../micro_topic_history.json'
MAX_RECENT = 5

def _pick_topic(pool, history_path, key='direction'):
    history = _load_history(history_path)
    recent = [str(h.get(key)) for h in history[-MAX_RECENT:]] if history else []
    fresh = [t for t in pool if str(t.get(key)) not in recent]
    return random.choice(fresh) if fresh else random.choice(pool)
```

Same pattern for micro-articles, minus same-day duplicates. **Seed the history file from the existing outbox filenames** so the rotation starts correct on day one:

```python
for f in sorted(glob.glob('outbox/toutiao/2026*.html'))[-7:]:
    parts = os.path.basename(f)[:-5].split('_')
    hist.append({'key': '_'.join(parts[2:]), 'date': ...})
```

**Rule: any content pipeline with a finite topic pool needs cross-day de-duplication, and the pool size sets the rotation period (6 topics ≈ 6-day cycle).** An operator can audit this cheaply: `ls -1 outbox/*/*.html | sed 's/.*_//'` and count direction frequency.

### Finding 3 — `exit 0` on failure kept both schedulers green (Case M, now fixed in code)

`main()` printed `❌ 发送失败` and returned normally → classic cron logged success, `jobs.json` recorded `last_status: ok`. Neither scheduler could see the failure. Now:

```python
if '飞书附件投递成功' not in msg:
    raise SystemExit(1)
```

The `in msg` check matters: when the Feishu fallback *did* deliver, the user really did get the content, so the exit code must stay 0. A blind `exit 1` would have turned a successful (fallback-delivered) night into a red cron for no reason.

### Today's run (2026-10-26, failure #63)

- **Generated**: 长文《67岁老人被三个儿子轮流养老，每家住四个月，第三家说"住够了"》（赡养义务）+ 微头条《婆婆来家里住了一个月，我瘦了8斤》《随了20年份子钱...》
- **Cron trigger**: classic crontab 20:30:00 (赡养义务). Agent-mode report session did **not** re-run the script (Case R).
- **HTML backup**: `20261026_2030_赡养义务.html` (21.7 KB / 2879 Chinese chars; all three story sections verified present)
- **Feishu delivery**: SUCCESS — `om_x100b62c0c035e8a8c09b7a1dc4978fd`, `msg_type=file`, `deleted=False`
- **Fixes**: `_feishu_deliver.py` subprocess fallback (interpreter-agnostic) + topic rotation history + `exit 1` on true failure
- **README**: extended to 20 `## ` entries

### Updated decision rule (N=63)

| Failure count | Probe? | Article inline? | Feishu attachment? | Topic rotation? | Exit code honest? | README? |
|---|---|---|---|---|---|---|
| 1-9 | Yes | Yes | Yes | Yes | Yes | Yes |
| 10-29 | Skip | NO | Yes (verify with **cron's** interpreter) | Yes | Yes | Yes |
| 30-52 | Skip | NO | Yes | Yes | Yes | Yes |
| ≥53 | Skip | NO | Yes | Yes | Yes | **Yes — mandatory** |
| **63 (today)** | Skip | NO | **Yes — fixed & verified** | **Yes — added** | **Yes — fixed** | **Yes (20 entries)** |
