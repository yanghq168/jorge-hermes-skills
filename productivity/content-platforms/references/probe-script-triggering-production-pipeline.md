# 诊断探针误触发生产管线 → 重复投递 + 历史污染（含完整回滚）

**Class:** 内容生产管线的操作事故（不属于 cron 调度诊断）。
父技能：`../SKILL.md`（与 `references/isolated-verification-harness.md` 配套）。

**实测日期：** 2026-11-24（头条号夜更）
**根因：** 排查「扩库模块为什么没加载」时，把一段探针代码写进 `/tmp` 并
**当成脚本执行**；探针里 `import` 了生产脚本 `toutiao-article-daily.py`，
而该脚本**在模块级调用了 `main()`** ⇒ 探针一跑就完整生成了文章、
投递了飞书附件、**并写进了 `topic_history.json` / `micro_history.json`**。

**代价：** 读者端多收了一份重复文章（20:52 的《赡养义务》），
长文 history 多 1 条 + 微头条 history 多 2 条 ⇒ 次日 LRU 轮换会被
带偏（选到本该淘汰的方向）。必须完整回滚。

---

## 一、为什么会发生（机制）

生产脚本长这样（头条号）：

```python
# ~/.hermes/cron/scripts/toutiao-article-daily.py
if __name__ == "__main__":
    main()
```

**但只要 `main()` 不在 `if __name__ == "__main__":` 守卫里**，
任何 `import` 都会执行整条管线（生成 → 落盘 → 发邮件 → 写 history）。

触发方式其实非常日常，**不是「恶意改生产脚本」**：

| 触发方式 | 说明 | 危险度 |
|---|---|---|
| `python3 /tmp/probe.py`，probe 里 `import toutiao_article_daily` | import 即执行 | 🔴 高 |
| `python3 -c "import toutiao_article_daily; ..."` | 同上 | 🔴 高 |
| `importlib.util.spec_from_file_location(...)` 加载后**没有**触发 module-level `main()` | ✅ 安全 | 绿 |
| `exec(open('script.py').read())` | 会执行 module-level 代码 | 🔴 高 |

**⇒ 核心纪律：任何「只是想看看生产脚本里有什么」的探针，
在 import 生产脚本之前，必须先确认它把 `main()` 放在 `if __name__ == "__main__":` 里面。**

---

## 二、预防（写探针前）

### 1. 先 grep 确认守卫存在

```bash
grep -n 'if __name__' ~/.hermes/cron/scripts/toutiao-article-daily.py
grep -n '^main()\|^ *main()' ~/.hermes/cron/scripts/toutiao-article-daily.py
```

- 有 `if __name__ == "__main__":` 守卫 ⇒ `import` 安全
- 看到裸的模块级 `main()` ⇒ **import 就会跑整条管线**

### 2. 探针写在自己的目录，绝不写进 `~/.hermes/cron/scripts/`

`~/.hermes/cron/scripts/` 是**生产目录**，探针放进去会被
cron 扫描 / 被下次会话误当生产脚本执行。放 `/tmp` 也要注意：
**放在 `/tmp` 不代表安全 —— 危险来自 `import`，不是来自路径。**

### 3. 更安全：只读源码文本，不 import

绝大多数「我想知道生产脚本怎么写的」根本不需要执行它：

```python
import io, re
src = io.open(PATH, encoding='utf-8').read()
print('has __main__ guard:', 'if __name__' in src)
```

### 4. 真需要调用真实生产函数时 —— 用隔离 harness

见 `references/isolated-verification-harness.md`：把
`HISTORY_FILE` / `MICRO_HISTORY_FILE` 指向**临时目录**，
再 monkey-patch 掉 `main()`、强制选中要验的方向。

### 5. 临时加守卫是廉价的保险

如果必须 import，可以先在源码里确认/补上守卫：

```python
if __name__ == "__main__":
    main()
```

（**生产脚本本来就该这么写** —— 2026-11-24 实测该脚本**已有**守卫，
但探针作者仍然踩坑，见下。）

---

## 三、🔴 关键教训：守卫存在 ≠ import 安全（本例的真根因）

**本例的脚本是「有守卫」的**，但仍然重复投递了。原因是：

> 探针**没有 import 那个文件**，而是**把生产脚本的源码 `exec` 进来**
> （或用 `runpy` / `importlib` 在 `__name__ != "__main__"` 的语境下
> 加载并手动调用了模块级入口）。守卫判断的是 `__name__`，
> **一旦你主动调用了模块级函数，守卫就不保护你了。**

**⇒ 判别口诀（比「有没有守卫」更实用）：**

> **探针有没有调用生产脚本的「入口函数」？**
> 有 ⇒ 就是「会跑整条管线」；守卫完全帮不上忙。
> 断言法：`grep -n 'main()' <probe.py>` —— 只要探针里出现了
> 对入口函数的调用，无论何种加载方式，都必须先把 history 指向临时目录。

**⇒ 铁律：探针脚本运行前，先做「零生产副作用」预检。**

```bash
# 探针跑之前，把生产产物数与 history mtime 记下来
ls -1 ~/.hermes/cron/outbox/toutiao/<YYYYMMDD>*.html | wc -l
stat -c '%y %n' ~/.hermes/cron/outbox/toutiao/*history*.json ~/.hermes/cron/outbox/toutiao/*.json 2>/dev/null
```

跑完再执行同一条命令 —— **任何变化都说明探针污染了生产状态。**

---

## 四、回滚手册（重复投递 + history 污染）

按这个顺序做，**每一步都要回查确认**：

### Step 1 — 删掉重复投递物（读者端优先）

飞书附件删除后**必须 API 回查**：

```python
# 删除后回查，确认 deleted=True
m = client.message.get(message_id="om_xxx")
print(m['data']['items'][0]['deleted'])   # 期望 True
```

邮件（QQ SMTP）**撤不回** —— 如果 SMTP 还能用，只能补发说明；
本例 SMTP 已失效（授权码失效第 92 天），所以重复只落在飞书通道。

### Step 2 — 删掉重复的 outbox 产物

```bash
rm ~/.hermes/cron/outbox/toutiao/<YYYYMMDD>_<HHMM>_<方向>.html
```

### Step 3 — 修正 PENDING 软链接

`PENDING_<日期>.html` 是「当晚如果只能选一篇」的标记，
必须指回**唯一正确**的那份：

```bash
ls -l ~/.hermes/cron/outbox/toutiao/PENDING_<YYYYMMDD>.html   # 确认指向
rm ~/.hermes/cron/outbox/toutiao/PENDING_<YYYYMMDD>.html
ln -s <YYYYMMDD>_<HHMM>_<方向>.html ~/.hermes/cron/outbox/toutiao/PENDING_<YYYYMMDD>.html
```

### Step 4 — 回滚 history（**最关键，也最容易被忘**）

history 决定**次日 LRU 轮换选谁**，多一条会带偏后续多晚。

```bash
# 先备份
cp ~/.hermes/cron/outbox/toutiao/topic_history.json \
   ~/.hermes/cron/outbox/toutiao/topic_history.json.bak_<YYYYMMDD>_<HHMM>
cp ~/.hermes/cron/outbox/toutiao/micro_history.json \
   ~/.hermes/cron/outbox/toutiao/micro_history.json.bak_<YYYYMMDD>_<HHMM>
```

然后从备份里删掉误加的条目（长文 1 条 + 微头条 2 条），
写回并**核验条目数**：

```bash
python3 -c "
import json,os
p=os.path.expanduser('~/.hermes/cron/outbox/toutiao/topic_history.json')
d=json.load(open(p,encoding='utf-8'))
print('长文条目数:',len(d))
"
```

### Step 5 — 三条「零污染」证据链（写进交付报告）

报告里写「已回滚」时必须附：

1. **三份源文件 mtime 仍是上次修改日**（`toutiao-article-daily.py` /
   `toutiao_topics_extra.py` / `toutiao_story_extensions.py`）
2. **当日 outbox 产物数 = 1**（`ls -1 .../20261124*.html | wc -l` → `1`）
3. **history 文件 mtime 已被回滚操作更新，且条目数与误加前一致**

⚠️ 与 `references/negative-claim-contradiction-and-identity-collision.md`
里的「本会话未修改生产源码」证据链是同一套要求 —— **报告不能只写
「已回滚」三个字，必须给可核验的证据**。

---

## 五、与既有纪律的关系

| 既有纪律 | 与本例的关系 |
|---|---|
| `references/isolated-verification-harness.md`「调用真实生产函数时把 HISTORY 指向临时目录」 | **本例证明它不够**：探针若不 import、而是直接跑入口函数，history 路径替换就来不及了 ⇒ 必须在**运行前**就预置 |
| 「Case R：改源码不重跑生产脚本」 | 本例是**反面教材**：不是"重跑"，是"误跑" ⇒ 后果与重跑相同（第二份产物 + history 污染） |
| `references/duplicate-scheduled-task-detection.md`（双调度重复） | 本例是**第三种重复根因**：探针/调试脚本自触发 ⇒ 该参考文件讲的是「两个调度器」，**不覆盖**本例 |
| 「outbox 是用户唯一副本，不要清空 outbox/」 | 本例只删**重复的那一份**，不删正确的那份 ⇒ 一致 |

---

## 六、给未来会话的一句话

> **在 `/tmp` 写探针不等于安全。危险来自「调用了入口函数」，不是来自路径。
> 探针跑之前：① grep 确认入口 ② 记录产物数 + history mtime ③ 把 history 指向临时目录。
> 跑完：同样的命令再执行一次，任何变化都要回滚。**
