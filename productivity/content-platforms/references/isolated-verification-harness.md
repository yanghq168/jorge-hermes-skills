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
