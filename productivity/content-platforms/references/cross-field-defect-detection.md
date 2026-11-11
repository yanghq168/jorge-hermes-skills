# 跨字段 / 跨夜失配缺陷 —— 检测与修复手册

**这是 session-detail 参考文件。** 类级方法论在 `../SKILL.md`（缺陷分类、检查清单、审计工具清单）。
本文件收录 2026-11-11 实测抓到的 3 类新缺陷（十三/十四/十五）的完整检测代码、
修复代码和实测数据，供后续会话直接复用。

---

## 为什么需要这份手册

现有全部审计规则查的都是**单字段内的算式**或**同一条内容内部的重复**：

| 规则 | 查什么 | 查不到什么 |
|---|---|---|
| `lint_content_consistency.py` | 数字算不算得通、角色存不存在 | 「这句话跟当篇故事有没有关系」 |
| `HOOK_PROMISE` | 钩子承诺的场景/引语/数字**有没有兑现** | 兑现的方式是不是**整句复制** |
| `GOLDEN_ECHO` | 金句**有没有**被正文整句复读 | 金句**来自哪一段**、标签对不对 |
| `audit_rendered_article.py` | 字数、结构、配图数、标签数 | 任何**跨字段/跨夜**的关系 |

于是「全绿但读者能看出硬伤」成为常态。2026-11-11 当晚
`audit exit 0` / `lint exit 0` / 脚本 exit 0 / 飞书已回查送达，
仍被抓到 3 类读者可见硬伤。

---

## 缺陷十三：跨夜同故事碰撞（长文池 ↔ 微头条池）

### 现象

读者在**连续两封邮件**里读到同一个故事。

### 实测实例（非模拟）

- 11-10 长文 = `随礼人情`（老周头随20年份子钱 / 烧本子）
- 11-11 微头条 1 = `人情往来`（**同一个老周头、同一个烧本子**）

两个方向名听起来不同（`人情往来` vs `随礼人情`），**但讲的是同一个故事**。

### 根因

`generate_micro_articles()` 只把**当晚**长文方向的影子微头条排除掉：

```python
shadow_dirs = []
if long_direction:
    for micro_dir, long_dir in SHADOW_MAP.items():
        if long_dir == long_direction:
            shadow_dirs.append(micro_dir)
```

**前一晚**的长文方向的影子完全没管。而两池 LRU **同步推进** ⇒ 跨夜碰撞是
**必然事件**，不是概率事件。60 天模拟实测碰撞率 **20%**。

### 修法

排除集扩到「**当晚 + 前 N 晚 + 后 N 晚**」的长文方向影子。

**「后 N 晚」不能省** —— 只挡「往前看」会漏掉「微头条先出、长文后出」那种顺序，
读者照样连着两晚读到同一个故事。

**长文方向可以预测**：LRU 在无并列时选择唯一（池子全部用过之后每条 last_seen
索引各不相同）⇒ 可推演未来 N 晚的方向。实测预测 **30/30 准确**。

```python
SHADOW_GUARD_NIGHTS = 3


def _recent_long_directions(history_path, n, exclude_last=True):
    """最近 n 晚已用过的长文方向（时间倒序，去重）。"""
    history = _load_history(history_path)
    seq = [_hist_key(h) for h in history]
    seq = [d for d in seq if d]
    if exclude_last and seq:
        seq = seq[:-1]          # 最后一条是今晚的长文，调用方单独处理
    out = []
    for d in reversed(seq):
        if d not in out:
            out.append(d)
        if len(out) >= n:
            break
    return out


def _predict_next_long_directions(history_path, n):
    """预测未来 n 晚的长文方向（按 LRU 规则推演）。"""
    history = _load_history(history_path)
    last_seen = {}
    for i, h in enumerate(history):
        k = _hist_key(h)
        if k:
            last_seen[k] = i
    sim = dict(last_seen)
    counter = len(history)
    order = []
    for _ in range(n):
        cands = [t for t in TOPICS_POOL
                 if str(t.get('direction')) not in order]
        if not cands:
            break
        ranks = [(sim.get(str(t.get('direction')), -1), t) for t in cands]
        oldest = min(r for r, _ in ranks)
        ties = [t for r, t in ranks if r == oldest]
        pick = sorted(ties, key=lambda t: str(t.get('direction')))[0]
        d = str(pick.get('direction'))
        order.append(d)
        sim[d] = counter
        counter += 1
    return order


def _shadow_dirs_for(guarded_long_dirs):
    guarded = set(str(d) for d in guarded_long_dirs if d)
    return [micro_dir for micro_dir, long_dir in SHADOW_MAP.items()
            if long_dir in guarded]
```

调用处：

```python
guarded_long = set()
if long_direction:
    guarded_long.add(str(long_direction))
guarded_long |= set(_recent_long_directions(
    HISTORY_FILE, SHADOW_GUARD_NIGHTS, exclude_last=True))
guarded_long |= set(_predict_next_long_directions(
    HISTORY_FILE, SHADOW_GUARD_NIGHTS))
shadow_dirs = _shadow_dirs_for(guarded_long)
```

### ⚠️ 守卫夜数不能更大 —— 实测调参表

| prev/next | 跨夜碰撞 | 长文覆盖 | 微头条覆盖 | 微头条方向分布 |
|---|---|---|---|---|
| 0/0（无守卫） | 22/60 | 10/10 | 10/10 | 均匀 |
| 1/1 | 22/60 | 10/10 | 10/10 | 均匀 |
| 2/2 | 33/60 | 10/10 | 10/10 | 均匀 |
| **3/3（采用）** | **0/60** | **10/10** | **10/10** | 6 条影子各 6 次 + 4 条非影子各 ~20 次 |
| 4/4 | 0/60 | 10/10 | 10/10 | 非影子涨到 21 次 |
| 5/5 | 0/60 | 10/10 | **4/10** ❌ | 只有 4 个方向 |

**5/5 是陷阱**：10 条微头条里有 6 条是影子方向，守卫窗口一大就被挤掉，
微头条方向覆盖从 10/10 掉到 4/10 —— 读者会觉得「天天就那几条」。
**3/3 是平衡点**：碰撞 0/60 + 两池覆盖都 10/10。

⚠️ **prev 必须是 N 晚（不是 N-1）** —— 实测 2/2 仍留 33/60 碰撞，3/3 才归零。

### 检测脚本（跑在临时 history 上，不污染生产）

```python
import importlib.util, sys, os, re, json, tempfile, shutil, filecmp
from collections import Counter
sys.path.insert(0, '/home/ubuntu/.hermes/cron/scripts')
spec = importlib.util.spec_from_file_location(
    "tg", "/home/ubuntu/.hermes/cron/scripts/toutiao-article-daily.py")
tg = importlib.util.module_from_spec(spec); spec.loader.exec_module(tg)

PROD_L = '/home/ubuntu/.hermes/cron/outbox/toutiao/topic_history.json'
PROD_M = '/home/ubuntu/.hermes/cron/outbox/toutiao/micro_topic_history.json'
bak_l, bak_m = PROD_L + '.bak', PROD_M + '.bak'
shutil.copy(PROD_L, bak_l); shutil.copy(PROD_M, bak_m)   # 事后证明零污染

lh = json.load(open(PROD_L)); mh = json.load(open(PROD_M))
tmpL = tempfile.mktemp(suffix='.json'); tmpM = tempfile.mktemp(suffix='.json')
json.dump([{'key': h.get('direction'), 'direction': h.get('direction')} for h in lh], open(tmpL, 'w'))
json.dump([{'key': h.get('direction'), 'direction': h.get('direction')} for h in mh], open(tmpM, 'w'))
tg.HISTORY_FILE = tmpL; tg.MICRO_HISTORY_FILE = tmpM

N = 60
coll = Counter(); long_seen = []; micro_dirs = []
for d in range(N):
    long_t = tg._pick_topic(tg.TOPICS_POOL, tmpL, key='direction')
    tg._record_topic(tmpL, long_t, key='direction')
    ld = long_t['direction']; long_seen.append(ld)
    micros = tg.generate_micro_articles(long_direction=ld)   # ← 真实生产函数
    picked = [m['direction'] for m in micros]
    micro_dirs += picked
    if any(tg.SHADOW_MAP.get(p) == ld for p in picked):
        coll['same_night'] += 1
    for back in range(1, 4):
        if d - back >= 0 and any(tg.SHADOW_MAP.get(p) == long_seen[d - back] for p in picked):
            coll[f'back{back}'] += 1; break
    pred = tg._predict_next_long_directions(tmpL, 3)
    if any(tg.SHADOW_MAP.get(p) in pred for p in picked):
        coll['forward'] += 1

os.unlink(tmpL); os.unlink(tmpM)
assert filecmp.cmp(PROD_L, bak_l, shallow=False)   # 生产未被污染
os.remove(bak_l); os.remove(bak_m)
```

**关键点：必须调用真实的 `generate_micro_articles()`，不要在测试脚本里
重新实现一遍选取逻辑** —— 2026-11-11 第一次就是这么写的（自己复刻了一遍
排除集），结果测出「修复无效」而实际是测试脚本没走真实路径。

### 通读清单新增第 ⑪ 条链：跨池同故事链

> 「今晚的微头条 == 前/后几晚的长文？」

---

## 缺陷十四：钩子整句在正文里逐字复读

### 现象

`HOOK_PROMISE` 只查「钩子承诺**有没有兑现**」，查不到「兑现的方式是
**整句复制**」。结果是读者在两屏之内看到同一句话两遍 —— 比金句复读更靠前
（钩子就在正文最上方）。

### 实测命中 2/10 方向

| 方向 | 钩子句 | 正文位置 |
|---|---|---|
| 养老院 | 「三个子女都孝顺，可她就是觉得心里空落落的」 | `story_a` 第 2 段 |
| 兄弟姐妹 | 「不是因为他生气，是因为她知道，一开口，兄弟三个就再也回不来了」 | `story_a` 末段 |

### 检测口径（比「最长公共子串 ≥10 字」更准）

公共子串会误报正常的呼应（「那天晚上三个子女在他」这种 10 字是**钩子承诺的
兑现**，是正确的）。真正的缺陷是**整句逐字复制** ⇒ 判定口径是：

**把钩子按句切开 → 归一化（去标点空格）→ 逐字 `in` 正文**。

```python
import re

def norm(s):
    return re.sub(r'[\s，,。．.、；;：:！!？?""\'\'（）()…—-]', '', s or '')

for t in tg.TOPICS_POOL:
    d = t['direction']
    ext = STORY_EXTENSIONS.get(d, (None, None))
    ea = ext[0] if ext and ext[0] else ''
    body = t['story_a'] + t['story_a_dialogue'] + t['story_a_ending'] + ea
    nb = norm(body)
    for s in [x for x in re.split(r'[。！？；\n]', t['hook']) if len(norm(x)) >= 8]:
        ns = norm(s)
        if ns and ns in nb:
            print(f'⚠️ {d}: 「{s.strip()[:44]}」 仍在正文逐字出现')
```

修复后：**10 个方向命中 0**。

### 修法

**改正文那一句，不动钩子。** 钩子是头条的流量钩子，优先级高于正文顺滑。

```
养老院  story_a: 「三个子女都孝顺，可她就是觉得心里空落落的。」
              → 「三个子女都孝顺，可她心里就是空落落的。」

兄弟姐妹 story_a: 「…不是因为不生气，是因为她知道，一开口，兄弟三个就再也回不来了。」
              → 「…不是因为他生气，是因为她心里清楚：这一开口，兄弟三个往后就再也回不来了。」
```

⚠️ 改完必须**立刻重新量该方向的字数**（微头条 150–250 是硬约束）。

---

## 缺陷十五：金句出处标注与实际出处对不上

### 现象

模板把 `golden1/2/3` **硬编码**成「故事A结尾 / 故事B结尾 / 文章结尾」：

```html
<div class="skeleton-label orange">【金句1】故事A结尾</div>
```

但金句是按**池槽位**写的、不是按实际出处写的 —— 实测 **20 条里 9 条**标注与
实际出处不符。标签是**渲染给读者看的**（不是注释），读者会以为是排版错乱。

### 修法：不手改金句，按实际出处**动态算标签**

**不手改金句的理由**：改金句会连带出新的复读（改了金句，viewpoint/action 那边
还留着旧表述 ⇒ `GOLDEN_ECHO` 立刻 fire）。动态算标签是零内容风险的做法。

```python
_GOLDEN_REGIONS = (
    ('A', '故事A结尾'),
    ('B', '故事B结尾'),
    ('V', '观点'),
    ('Act', '行动'),
)


def _bigrams(text):
    import re as _re_lbl
    s = ''.join(_re_lbl.findall(r'[\u4e00-\u9fff]', text or ''))
    return set(s[i:i + 2] for i in range(len(s) - 1))


def _overlap_ratio(a_bi, b_bi):
    if not a_bi or not b_bi:
        return 0.0
    return len(a_bi & b_bi) / min(len(a_bi), len(b_bi))


def _golden_labels(topic, ext=None):
    """算出 golden1/2/3 各自真实出处对应的标签文案。"""
    if ext is None:
        try:
            import os as _os_lbl, sys as _sys_lbl
            _d = _os_lbl.path.dirname(_os_lbl.path.abspath(__file__))
            if _d not in _sys_lbl.path:
                _sys_lbl.path.insert(0, _d)
            from toutiao_story_extensions import STORY_EXTENSIONS as _SE
            ext = _SE.get(topic.get('direction'))
        except Exception:
            ext = None
    ea = ext[0] if ext and len(ext) > 0 and ext[0] else ''
    eb = ext[1] if ext and len(ext) > 1 and ext[1] else ''

    # ⚠️ _apply_story_extensions() 已经把扩写拼进 story_a/story_b 了
    # （它会 mutate topic）⇒ 这里不能再拼一次，否则扩写被算两遍。
    sa = topic.get('story_a', '')
    sb = topic.get('story_b', '')
    if ea and ea not in sa:
        sa += '\n' + ea
    if eb and eb not in sb:
        sb += '\n' + eb

    regions = {
        'A': sa + '\n' + topic.get('story_a_dialogue', '') + '\n' + topic.get('story_a_ending', ''),
        'B': sb + '\n' + topic.get('story_b_ending', ''),
        'V': topic.get('viewpoint', ''),
        'Act': topic.get('action', ''),
    }
    reg_bi = {k: _bigrams(v) for k, v in regions.items()}

    labels = []
    for idx, gk in enumerate(('golden1', 'golden2', 'golden3'), start=1):
        gb = _bigrams(topic.get(gk, ''))
        scores = sorted(
            ((_overlap_ratio(gb, reg_bi[k]), name) for k, name in _GOLDEN_REGIONS),
            key=lambda x: -x[0])
        top_score, top_name = scores[0]
        second = scores[1][0]
        # 差距太小 → 分不清来源 → 中性标签，不说假话
        if top_score <= 0.0 or (top_score - second) < 0.05:
            src = '文章金句'
        else:
            src = top_name
        labels.append(f'【金句{idx}】{src}')
    return labels
```

### 三个关键设计点

1. **打分用整段故事**（不只是 `story_a_ending` 那一句）—— 金句常常是提炼自
   故事**中段**的。只拿 ending 比会大量判不出出处（实测「文章金句」从 8/30
   降到 3/30）。
2. **差距太小就标中性「文章金句」** —— **宁可模糊也不说假话**。硬要标一个
   位置就是回到原来那个错。
3. **池型分叉**：微头条池没有 `golden1/2/3` ⇒ 必须直接返回中性标签，
   否则整池假阳性（与 `HOOK_PROMISE` 同一个坑）。

### 模板改成占位符

```html
<div class="skeleton-label orange">{golden1_label}</div>
<div class="skeleton-label orange">{golden2_label}</div>
<div class="skeleton-label orange">{golden3_label}</div>
```

`generate_article()` 里：

```python
golden1_label, golden2_label, golden3_label = _golden_labels(topic)
...
HTML_TEMPLATE.format(
    ...,
    golden1_label=golden1_label,
    golden2_label=golden2_label,
    golden3_label=golden3_label,
)
```

⚠️ **`str.format()` 静默丢弃未引用的 kwargs**（既有教训）—— 改完模板必须
**渲染一遍并 grep 占位符是否被替换**，不能只看 `py_compile` 过。

### 检查清单同步更新

清单会**渲染给读者**，不能漂移：

```python
# 旧（会渲染一句假话给读者）
"3个金句位置对不对？（故事A结尾、故事B结尾、文章结尾）",
# 新
"3个金句的出处标注对不对？（标签按实际出处自动生成，别手改成固定位置）",
```

---

## 通用检测脚本：跨字段公共子串扫描

一次性扫出所有方向的跨字段重复/呼应（≥10 字）：

```python
import importlib.util, sys, re
sys.path.insert(0, '/home/ubuntu/.hermes/cron/scripts')
spec = importlib.util.spec_from_file_location(
    "tg", "/home/ubuntu/.hermes/cron/scripts/toutiao-article-daily.py")
tg = importlib.util.module_from_spec(spec); spec.loader.exec_module(tg)
from toutiao_story_extensions import STORY_EXTENSIONS


def cjk(s):
    return ''.join(re.findall(r'[一-鿿]', s or ''))


def lcs(a, b):
    """最长公共连续子串。"""
    if not a or not b:
        return ''
    prev = [0] * (len(b) + 1); best = ''
    for i in range(1, len(a) + 1):
        cur = [0] * (len(b) + 1); ai = a[i - 1]
        for j in range(1, len(b) + 1):
            if ai == b[j - 1]:
                cur[j] = prev[j - 1] + 1
                if cur[j] > len(best):
                    best = a[i - cur[j]:i]
        prev = cur
    return best


FIELDS = ['story_a', 'story_a_dialogue', 'story_a_ending',
          'story_b', 'story_b_ending', 'viewpoint', 'action',
          'golden1', 'golden2', 'golden3']

for t in tg.TOPICS_POOL:
    d = t['direction']
    ext = STORY_EXTENSIONS.get(d, (None, None))
    ea = ext[0] if ext and ext[0] else ''
    eb = ext[1] if ext and len(ext) > 1 and ext[1] else ''
    bodyA = cjk(t['story_a'] + t['story_a_dialogue'] + t['story_a_ending'] + ea)
    bodyB = cjk(t['story_b'] + t['story_b_ending'] + eb)
    hits = []
    for g in ('golden1', 'golden2', 'golden3'):
        for bname, b in (('故事A体', bodyA), ('故事B体', bodyB)):
            s = lcs(cjk(t[g]), b)
            if len(s) >= 10:
                hits.append((f'{g}↔{bname}', s))
    s = lcs(cjk(ea), bodyB)
    if len(s) >= 10:
        hits.append(('ext_a↔故事B体', s))
    s = lcs(cjk(eb), bodyA)
    if len(s) >= 10:
        hits.append(('ext_b↔故事A体', s))
    if hits:
        print(f'### {d}  {t["title"][:32]}')
        for k, v in sorted(set(hits), key=lambda x: -len(x[1])):
            print(f'   [{k}] len={len(v)} :: {v}')
```

---

## 这三条的共性（写给未来的自己）

> 三条都是**跨字段 / 跨夜**的失配。现有规则查的是「单字段内的算式」和
> 「同一条内容内部的重复」，查不到「**这条内容与另一条内容的关系**」。

**通读清单已从 10 条链扩到 11 条链（新增⑪跨池同故事链）。**
