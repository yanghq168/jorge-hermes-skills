# 隔离验证 harness —— 改源码不重跑生产脚本，也能证明修复生效

**这是 session-detail 参考文件。** 类级方法论在 `../SKILL.md`。
本文件收录 2026-11-12 头条号实测的隔离验证手法。

---

## 一、要解决的矛盾

Case R（既有纪律）：**改源码，不重跑已投递的生产脚本**。
理由：重跑会产生第二份产物 + 污染 `topic_history`（详见
`references/orphan-extensions-and-hand-arithmetic-audit.md` §6）。

但 2026-11-12 当晚出现了 Case R 覆盖不到的新情况：

```
audit exit 0 / lint exit 0 / 脚本 exit 0 / 飞书 message.get 回查送达
                    ↓ 全绿
手工通读抓到 9 处读者可见硬伤（7 处内容 + 2 处金句复读）
                    ↓ 只能改源码
已投递的那份 HTML **仍是修复前的版本**（读者手上的就是那份）
```

于是变成三重矛盾：

| 要求 | 冲突方 |
|---|---|
| 证明修复真的生效 | 不重跑生产脚本 |
| 不产生第二份产物 | 重跑生产脚本 |
| 不污染 `topic_history` | 重跑生产脚本 |

**解法：隔离 harness。** 在**临时状态**下调用**真实生产函数**，把产物渲染到
临时文件，再对它跑审计 + 跑修复点断言。

---

## 二、隔离 harness 的五个组成部分

### ① 加载生产脚本（不 `import`，脚本名带连字符）

```python
import importlib.util, sys, os, tempfile, shutil, subprocess

def load(path, name='tg'):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m
```

⚠️ `toutiao-article-daily.py` 文件名带连字符 ⇒ **不能 `import`**，
只能走 `importlib.util.spec_from_file_location`。
⚠️ 扩库模块（`toutiao_topics_extra.py` / `toutiao_story_extensions.py`）
需要 `sys.path` 里含 `__file__` 所在目录 —— 生产脚本自己会处理，
但**测试脚本**若直接 import 扩库模块，必须自己插 `sys.path`。

### ② 把状态文件指向临时目录（关键：这是「不污染」的全部来源）

```python
tmp = tempfile.mkdtemp()
T = load("/home/ubuntu/.hermes/cron/scripts/toutiao-article-daily.py")
T.HISTORY_FILE = os.path.join(tmp, "t.json")
T.MICRO_HISTORY_FILE = os.path.join(tmp, "m.json")
open(T.HISTORY_FILE, "w").write("[]")
open(T.MICRO_HISTORY_FILE, "w").write("[]")
```

**所有写状态的动作都靠模块级常量定位** —— 只要把 `HISTORY_FILE` /
`MICRO_HISTORY_FILE` 覆盖掉，就永远不会碰生产文件。
（若某个脚本把路径硬编码在函数内部而非模块级，就没法隔离 ⇒
**这是「状态路径必须做成模块级常量」的设计要求**，改脚本时顺手满足。）

### ③ monkey-patch 强制选中你要验的那个方向

LRU 选取会随历史变化 ⇒ 想验「再婚财产」这一条，必须强制它被选中：

```python
orig = T._pick_topic
def forced(pool, hp, key='direction'):
    if pool is T.TOPICS_POOL:
        return [t for t in pool if t['direction'] == '再婚财产'][0]
    return orig(pool, hp, key)
T._pick_topic = forced
```

⚠️ **按 `pool is` 判断是长文池还是微头条池** —— 微头条池走另一个分支，
不能一刀切强制，否则会破坏微头条的选取逻辑。

### ④ 调**真实生产函数**，拼出完整产物

```python
html, plain, topic = T.generate_article()
micros = T.generate_micro_articles(long_direction=topic['direction'])
full = html + '\n'.join(m['html'] for m in micros)
out = os.path.join(tmp, "r.html")
open(out, "w", encoding="utf-8").write(full)
```

⚠️ **必须自己拼 `html + 微头条`** —— `generate_article()` 只返回长文 HTML，
微头条 HTML 是在 `send_email()` 里拼上的。只测 `generate_article()` 的返回值
会误判「微头条缺失」（既有教训，见 `topic-pool-rotation-and-length-engineering.md`）。

⚠️ **必须调真实函数，不要在 harness 里复刻逻辑** —— 2026-11-11 跨夜碰撞
测试就是自己复刻了一遍排除集，结果测出「修复无效」而实际是**测试脚本
没走真实路径**。harness 只做「强制选中 + 换状态路径」，其余全部走生产代码。

#### 🔴 2026-11-16 实测：两个 API 陷阱（照抄上次会话的调用方式会直接崩）

**① `generate_article()` 返回的是三元组，不是字符串。**

```python
html_content, plain_text, topic = T.generate_article()   # ✅
full = html_content + '\n'.join(m['html'] for m in micros)  # ✅
```
写成 `full = T.generate_article() + ...` ⇒
`TypeError: can only concatenate tuple (not "str") to tuple`。

**② `generate_micro_articles()` 的签名会变 —— 先 `inspect.getsource()` 确认。**

2026-11-12 记录的签名是
`generate_micro_articles(long_direction=topic['direction'])`；
2026-11-16 实测该函数**不接受参数**，且内部走的是
`_pick_micro_index(used_indices, exclude_directions=shadow_dirs)`
（**不是** `_pick_lru` —— `_pick_lru` 是被 `_pick_micro_index` 间接调用的）。

```python
import inspect
print(inspect.getsource(T.generate_micro_articles)[-700:])
```

**通则：harness 里任何对生产函数的调用，动手前先 `inspect.getsource()` 看一眼真实签名，
不要凭上一轮的记忆写。** 脚本改版后旧调用方式会以 TypeError 的形式炸出来。

### ⑤ 对隔离产物跑审计 + 跑修复点断言

```python
r = subprocess.run(
    ["python3", "/home/ubuntu/.hermes/skills/productivity/content-platforms/scripts/"
     "audit_rendered_article.py",
     out, "--pool", "/home/ubuntu/.hermes/cron/scripts/toutiao-article-daily.py"],
    capture_output=True, text=True)
print("ISOLATED_AUDIT_EXIT=", r.returncode)
print(r.stdout)
```

修复点断言 —— **必须双向**：

```python
checks = [
    ("标题「大女儿」",        "大女儿把老人告上了法庭" in full),
    ("标题不再说「三个儿女」", "三个儿女把老人告上法庭" not in full),
    ("正文补了领证",          "咱们先把证领了" in full),
    ("对白不再说「这房子是我名下的」", "这房子是我名下的" not in full),
    ("「6年前」时间线",       "6年前赵叔跟老伴登记" in full),
    ("不再说「等我俩都走了」", "等我俩都走了" not in full),
]
for n, ok in checks:
    print(("  ✅ " if ok else "  ❌ ") + n)
assert all(ok for _, ok in checks)
```

**为什么必须双向（旧串 `not in` + 新串 `in`）**：
只查「新串在不在」会漏掉两种失败 ——
① 改到了**别的段落**（新串出现了，但旧串还在原处）；
② 改完把旧串留在**另一个字段**里没清掉。
既有教训：「我以为矛盾句在 A 段、实际在 B 段，首轮修复根本没碰到那句」
⇒ 必须同时断言**旧的消失**和**新的出现**。

#### 🔴 2026-11-20 实测：断言要「钉语义要点」，不要「钉计划中的逐字措辞」

当晚写了 21 条断言，一次跑出 **19 条通过 / 2 条失败**。两条失败都是
**同一种原因** —— 落地措辞与计划措辞不同：

| 计划的断言 | 实际落地 | 失败原因 |
|---|---|---|
| `'当年他随过份子钱的' not in full and '他当年随过份子钱的那位邻居' in full` | 落地成了另一种改写 | 新串没按计划写 |
| `'大女儿坐在原告席上' in full` | 落地成「孙阿姨在旁听席上」 | 新串没按计划写 |

**教训：断言失败 ≠ 修复失败。** 落地时常常又避开了别的约束（字数、
`HOOK_PROMISE`、语义连贯），措辞自然不会照抄计划。

**正确写法：钉住语义要点，不要钉逐字措辞。**

```python
# ❌ 太脆：照抄计划里的措辞
assert '他当年随过份子钱的那位邻居' in full
# ✅ 钉要点：旧串消失了 + 要点还在
assert '当年他随过份子钱的' not in full and '随过份子钱的' in full
assert '原告席' in full and '旁听席' in full
```

**断言失败时的正确流程**：
1. 看 stderr（先分清是断言失败还是脚本 `SyntaxError`）；
2. **打开产物确认那处是不是真的还错** —— 别急着回去改文案；
3. 真的还错 → 回去改源码；其实已经对 → **把断言改成钉语义要点**。

⚠️ **别因为断言失败就断言修复失败** —— 那会导致重复劳动，或
把本来正确的文案改坏（与「规则假阳性比规则漏报更危险」同源）。

#### ✅ 一条断言 = 一个位置

别把多个位置的检查写成一个 `and` 串：

```python
# ❌ 失败时不知道是哪一处没改
assert '没人请他' in full and '没人来' not in full

# ✅ 逐个位置独立断言
assert '没人请他' in full
assert '最后一场酒席没人来' not in full
```

当晚的「五处一致链」（title / hook / story_a / viewpoint / 互动问题）
正是靠**每处一条断言**才定位到「改了标题但漏了观点段和互动问题」。

#### 📋 当晚的断言清单规模参考

一次修 18 处硬伤 ⇒ 21 条断言（每处硬伤 1 条 + 关键处额外 1 条
「旧串 not in」）。**断言数 ≥ 修复点数**是合理的一一对应关系；
少于修复点数意味着有改动没被验证。

---

## 三、跑完必须确认「生产状态零污染」

harness 结束 ≠ 一定没污染。必须显式核验：

```python
# 1) 当日产物数量未变
# 2) history 文件 mtime 未变
# 3) 无残留临时文件
shutil.rmtree(tmp)
```

当晚实测核验结果：当日产物仍只有 1 个、`topic_history.json` 的 mtime 停在
`20:30:01`（= 生产脚本运行时刻）、无残留临时文件。

---

## 四、这套手法带来的额外收益

隔离 harness 不只验证「我改的生效了」，还顺带做了一次**独立复审**：

- 对隔离产物跑 `audit_rendered_article.py` ⇒ 结构/字数/配图/标签全部合规
- 断言清单可以**把当晚人工通读抓到的每一处硬伤都写成一条断言** ⇒
  从「我记得改过」变成「机器断言过」
- 跑完能确认「读者手上的那份仍是修复前版本，修复从明晚首跑生效」——
  这句话必须写进交付报告，**不能默认读者拿到的是修复后的版本**

---

## 五、通用判据：什么时候该用隔离 harness

| 场景 | 用什么 |
|---|---|
| 内容硬伤修复（已投递后才发现） | **隔离 harness**（Case R + 证明生效） |
| 选题池/扩写**数据**改动，未投递 | 直接跑 lint + 审计脚本即可 |
| linter 新增规则 | 三步验证（正例/反例/跨池不误报），见 SKILL.md |
| 调度/投递链路问题 | 归 `cron-job-debugging` 技能 |

---

## 六、与 Case R 的关系（不变）

- 隔离 harness **不是**重跑生产脚本：它不写生产 history、不产生 outbox 产物、
  不触发 `send_email()`、不写 `STANDBY`。
- **禁止**用 harness 产物去「补发」给用户 —— 那等于投递了第二份内容。
- 已投递产物**未重跑、未改动**；改的是源码，明晚起自动生效。
- 交付报告里必须写明：**读者手上的那份仍是修复前的版本**。
