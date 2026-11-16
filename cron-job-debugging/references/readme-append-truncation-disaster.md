# README 追加事故 —— `read_file` 的 500 行默认上限会静默截断日志

**2026-11-16 实测事故。** 这是「README 追加」这条纪律在实现层的地雷：
纪律本身是对的（每晚追加一段），但**用错工具实现它会毁掉整个文件**。

---

## 一、事故经过

当晚要把 `## 2026-11-16（持续中 — 第84天）` 追加到
`~/.hermes/cron/outbox/toutiao/README.md`（已累积 40 个标题、约 137 KB、822 行）。

用的是这个写法（看起来完全合理）：

```python
from hermes_tools import read_file, write_file
r = read_file(path)            # ⚠️ 只返回前 500 行！
content = r["content"]          # 行号前缀 "N|"
lines = [ln.split("|", 1)[1] for ln in content.split("\n") if "|" in ln ...]
text = "\n".join(lines)
text += entry                    # 追加今晚这一段
write_file(path, text)          # ⚠️ 整个覆盖写回！
```

**结果：README 从 822 行被截断到 513 行，11-02 ~ 11-15 共 14 段历史日志当场消失。**

### 为什么必然出事

1. `read_file` 的 `limit` 默认 **500 行**，且**超限时静默截断** —— 不报错、不警告。
2. `r["total_lines"]` 会告诉你真实行数，但**你必须主动去看**；不看你就会以为读全了。
3. `write_file` 是**全量覆盖**。你读到的就是 500 行 ⇒ 你写回去的就是 500 行 + 新段。
4. 于是 14 段历史被无声删除。

---

## 二、恢复方法：从会话数据库还原（本次实际有效）

outbox 目录**没有备份**，README 也没有 git。真正的还原源是
**Hermes 自己的会话数据库** —— 每一晚的 README 追加都是当晚 agent 的一次
`write_file` / `execute_code` 工具调用，**完整文本就存在 `tool_calls` 字段里**。

```python
import sqlite3, json, re, codecs
c = sqlite3.connect('/home/ubuntu/.hermes/state.db')
cur = c.cursor()

# messages 表结构（2026-11-16 实测）：
#   id, session_id, role, content, tool_call_id, tool_calls, tool_name,
#   timestamp, token_count, finish_reason, reasoning, ...
# ⚠️ 关键内容在 `tool_calls`（JSON 字符串），不在 `content` 里。

rows = cur.execute("""
    SELECT id, session_id, tool_calls, content FROM messages
    WHERE tool_calls LIKE '%持续中 — 第%' OR content LIKE '%持续中 — 第%'
    ORDER BY id""").fetchall()

def get_code(mid):
    """从 execute_code 的 tool_calls 里取出原始 Python 源码字符串。"""
    tc = cur.execute("SELECT tool_calls FROM messages WHERE id=?", (mid,)).fetchone()[0]
    outer = json.loads(tc)                        # list of tool calls
    args = json.loads(outer[0]['function']['arguments'])
    return args['code']

def get_write_content(mid):
    """从 write_file 的 tool_calls 里取出完整待写入文本。"""
    tc = cur.execute("SELECT tool_calls FROM messages WHERE id=?", (mid,)).fetchone()[0]
    outer = json.loads(tc)
    args = json.loads(outer[0]['function']['arguments'])
    return args['content']
```

### 还原时的三个坑（各踩一次）

| 坑 | 现象 | 解法 |
|---|---|---|
| **JSON 转义层** | `tool_calls` 里存的是 JSON 字符串，含 `\n` 字面量、`\uXXXX` | 用 `json.loads` 两层解析拿到**原始 Python 源码**，再从源码里切出 `entry = """..."""` 之间的三引号块。**不要**手工 `unicode_escape`（会把中文和标点一起搞坏）。 |
| **工具调用类型不同，取值方式不同** | `write_file` 的参数在 `args['content']`；`execute_code` 的参数在 `args['code']`，entry 藏在源码的三引号里 | 先 `json.loads` 看 `outer[0]['function']['name']` 是什么，再决定取哪个 key。 |
| **同一晚有多个候选** | 同一夜 agent 可能多次触碰 README（追加 + 回填 + 复核） | 按「`\n- ` 开头行数 × 长度」打分选**最完整**的那份，并加 `must contain '- Symptom:'` 这类有效性过滤 —— 否则会选到工具输出片段（`grep` 结果、行号列表），不是真日志。 |

### 还原后必须做的三件事

```python
# 1) 重建 + 去重：同一天可能恢复出两份（短的被长的覆盖）
parts = re.split(r'\n(?=## )', text)
# 对每个日期，只保留 bullets 最多的那份

# 2) 核验标题序列连续 + 无乱码
for h in re.findall(r'^## .*$', text, re.M): print(h)
print("mojibake:", text.count('\ufffd'))

# 3) 核验「第N天」编号连续（本次：第69天 → 第84天，中间无缺口）
```

本次还原结果：**41 个标题**（原 40 + 今晚 1），第 69→84 天连续无缺口，
乱码 0，全部历史段落完整。

---

## 三、正确的追加写法（以后照这个抄）

### 首选：纯追加，绝不读改写

```python
from hermes_tools import terminal
# 用 shell >> 追加 —— 天然不会截断，也不受 read_file 行数限制影响
terminal(f"""cat >> {path} <<'HERMES_EOF'

## 2026-11-16（持续中 — 第84天）
- Symptom: ...
- Generated: ...
HERMES_EOF
""")
# 然后核验
print(terminal(f"grep -c '^## ' {path}")['output'])
```

### 次选：Python 追加（不读全文）

```python
from pathlib import Path
p = Path('/home/ubuntu/.hermes/cron/outbox/toutiao/README.md')
with p.open('a', encoding='utf-8') as fh:      # ← 'a' 模式，不是 'w'
    fh.write(entry)
```

### 如果必须读改写：显式读满 + 断言

```python
r = read_file(path, offset=1, limit=2000)        # ← 显式给足
total = r["total_lines"]
if total > 2000:
    raise RuntimeError("文件超过读取上限，改用纯追加模式")   # ← 别静默截断
```

**通用规则：日志类文件只追加，不读改写。** 唯一需要读改写的是
「回填缺失夜」—— 而那正是本次事故里最危险的动作。

---

## 四、预防清单（写进 README 追加纪律）

- [ ] 用 `>>` / `open(..., 'a')` 追加，**不用** `read_file` + `write_file`
- [ ] 若用了 `read_file`，必须显式 `limit` ≥ 文件行数，并**比较 `total_lines`**
- [ ] 追加后核验：`grep -c "^## "` 比对追加前的数量（必须 **+1**）
- [ ] 追加后核验：`grep -n "^## " | tail -3` 看最后三个标题是不是连续的
- [ ] 核验无乱码：`grep -cP '\x{FFFD}'` 必须为 0
- [ ] **不要**在同一晚反复读写同一个 README（回填 + 追加 + 复核合成一次）

---

## 五、更普遍的教训

**「读-改-写」模式对任何只增不减的日志文件都是危险的。**
本仓库里同类的只增文件：`outbox/<platform>/README.md`、
`topic_history.json`、`micro_topic_history.json`、`jobs.json`。

要么纯追加，要么读时确认读全了。两者都不是「顺手读一下改一下」。

**另外：会话数据库是意外的最后一道保险。**
`~/.hermes/state.db` 的 `messages.tool_calls` 字段保存了每一次工具调用的
**完整入参**。任何「我覆盖了一个本不该覆盖的文件」的事故，
都可以从这里回捞 —— 前提是你知道去哪儿捞。
