# Case Y — Feishu delivery channel failure: stale `omt_` thread_id (2026-10-24, failure #61)

**A second, independent delivery failure line** on this deployment, discovered while
handling the QQ SMTP outage. The QQ email channel was already dead (61 nights); this
session found that the **Feishu channel that carries the cron report itself** was
*also* dead — so the nightly failure report was never reaching the user either.
Both channels green in `jobs.json`, zero actual delivery.

## Symptom

`jobs.json` showed a `last_delivery_error` that the daily reports had been ignoring:

```
delivery error: Feishu send failed: [99992402] field validation failed
```

From `~/.hermes/logs/errors.log`, this had been firing for 3 consecutive nights:

```
2026-10-22 20:31:18 WARNING cron.scheduler: Job '406529dd5f2e': live adapter send to
    feishu:oc_39c71fb71c2db9be002545966567498f failed ([99992402] field validation failed),
    falling back to standalone
2026-10-22 20:31:18 ERROR   cron.scheduler: Job '406529dd5f2e': delivery error: Feishu send failed
2026-10-23 20:30:51 ERROR   cron.scheduler: Job '406529dd5f2e': delivery error: ...
2026-10-24 02:01:03 ERROR   cron.scheduler: Job '2409bfc322fb': delivery error: ...
```

Both the **live adapter** path and the **standalone** path failed identically — which
is why "falling back to standalone" didn't help.

## Root cause

Both jobs stored a **stale/invalid `thread_id`** in their `origin` block:

| job id | name | origin.thread_id |
|---|---|---|
| `406529dd5f2e` | 头条号文章 | `omt_19705b69670f5b81` |
| `2409bfc322fb` | Hermes记忆数据每日备份 | `omt_19703695ee4f9be0` |

Feishu's `receive_id_type=thread_id` expects a **real `om_` message id**. The `omt_`
prefix is a *thread* identifier, not a message identifier, so the API rejects it:

```
GET /open-apis/im/v1/messages/omt_19705b69670f5b81
  -> 400 {"code":99992354, "msg":"The request you send is not a valid {open_message_id} ... 
          Invalid ids: [omt_19705b69670f5b81]"}

POST /open-apis/im/v1/messages?receive_id_type=thread_id
  -> 400 {"code":99992402, "msg":"field validation failed", "error":{"field_viol":...}}
```

So: `99992354` is the *underlying* error (invalid id), `99992402 field validation failed`
is the *surface* error the adapter reports. The adapter's `_send_raw_message` takes the
`receive_id_type=thread_id` branch whenever `metadata["thread_id"]` is set — and
`deliver: origin` populates that from `origin.thread_id`.

**This is why the failure looked like a generic field-validation error with no obvious
cause** — the invalid id is one layer below the reported error.

## The fix

Change `deliver` from `origin` to an explicit platform target **without** a thread id:

```bash
hermes cron edit <job_id> --deliver "feishu:oc_39c71fb71c2db9be002545966567498f"
```

`tools/send_message_tool._parse_target_ref` handles `oc_/ou_/on_/chat_/open_` prefixes
and treats the `:sub` part as optional thread id. With no `:sub`, `thread_id=None`, and
`_resolve_single_delivery_target` returns:

```python
{'platform': 'feishu', 'chat_id': 'oc_39c71fb71c2db9be002545966567498f', 'thread_id': None}
```

→ the adapter takes the `receive_id_type=chat_id` branch, which works.

## Verification (do all three, don't stop at #1)

```bash
# 1. Confirm the id is the problem
curl -H "Authorization: Bearer $TOKEN" \
  https://open.feishu.cn/open-apis/im/v1/messages/omt_19705b69670f5b81
# -> 99992354 invalid open_message_id

# 2. Confirm the chat_id path works
curl -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id \
  -d '{"receive_id":"oc_...","msg_type":"text","content":"{\"text\":\"diag\"}"}'
# -> {"code":0, "message_id":"om_..."}

# 3. End-to-end through the REAL scheduler code path
python3 -c "
import sys, asyncio; sys.path.insert(0,'.')
from tools.send_message_tool import _send_to_platform
from gateway.config import load_gateway_config, Platform
cfg = load_gateway_config()
r = asyncio.run(_send_to_platform(Platform('feishu'), cfg.platforms.get(Platform('feishu')),
    'oc_...', '[自检] test', thread_id=None))
print(r)   # -> {'success': True, 'message_id': 'om_...'}
"
```

Note `_send_to_platform` returns a **dict** (not a `SendResult`), so check
`r['success']` — reading `r.success` silently yields `None` and looks like a failure.

## Pitfalls

- **`last_status=ok` does NOT mean delivered.** The scheduler records `ok` because the
  *job* succeeded (the agent produced a response); the *delivery* is a separate step
  whose failure only shows in `last_delivery_error`. **When investigating "I didn't get
  the cron message", read `last_delivery_error` FIRST**, before concluding anything
  about the job itself.
- **A broken delivery channel masks the whole report.** If the report rides the same
  channel that's broken, the user sees silence. Always check `last_delivery_error` on
  the job you are currently running as, not just on jobs you are debugging.
- **The two channels can fail independently.** Here: QQ SMTP dead for 61 days AND
  Feishu thread routing broken for 3+ days. Fixing one does not fix the other.
- **`omt_` is not a valid `receive_id` for `thread_id` type.** If you must target a
  thread, use the **`om_`** id of a message in that thread.
- **Verify with the real code path, not a hand-rolled curl.** A curl to
  `receive_id_type=chat_id` proves the *API* works; only
  `_send_to_platform(..., thread_id=None)` proves the *scheduler* will route correctly.
- **Back up `jobs.json` before editing via CLI** (`cp jobs.json jobs.json.bak.$(date +%F)`).
  `hermes cron edit` rewrites the whole file; a mistaken `--deliver` value is a
  one-command foot-gun.
- **`_parse_target_ref` for feishu**: `^((?:oc|ou|on|chat|open)_[-A-Za-z0-9]+)(?::([-A-Za-z0-9_]+))?$`.
  The chat id must be one of those prefixes; a bare UUID or a bare `oc` id without the
  prefix won't match, and the parser falls back to treating the whole string as a chat
  id with no thread — which then fails at the API with a *different* error.
