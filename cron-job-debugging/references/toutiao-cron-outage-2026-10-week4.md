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
- **Outbox after prune**: 55 HTML + 23 PENDING + 1 STANDBY, 944 KB
