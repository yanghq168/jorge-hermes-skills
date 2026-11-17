# 第 18 类缺陷「分项之和 ≠ 声明总额」+ 8 字复读扫描 + 钩子/结局互为复读

**2026-11-16 头条号实测。** 当晚 `audit_rendered_article.py` **exit 0**、
`lint_content_consistency.py` **exit 0**、假阳性检查 **exit 0**、脚本 exit 0、
飞书 `message.get` 回查送达 —— **全程绿灯**，人工通读仍抓到 **8 处读者可见硬伤**。

本文档收录当晚的缺陷清单、检测方法、以及为什么现有规则全部漏掉。

---

## 一、当晚抓到的 8 处硬伤

| # | 缺陷 | 属于哪条链 | 现有规则为何漏掉 |
|---|---|---|---|
| 1 | 钩子句「他给自己倒了一杯水」在正文里**逐字复读** | 钩子↔正文 | `HOOK_PROMISE` 只查「有没有兑现」，不查「兑现方式是不是整句复制」 |
| 2 | `story_b_ending` 与 `viewpoint` 12 字复读：「找人聊，主动定规矩——这」 | 跨字段复读 | `GOLDEN_ECHO` 只查 `golden1/2/3` ↔ 正文，**不查两个正文字段之间** |
| 3 | 扩写段把 `story_a` 的同一笔账算了两遍（11 字：「00，一个月5500块」） | 扩写↔主体复读 | 同上；且数值本身「自洽」，只是重复 |
| 4 | 扩写段 `ext_b` 与 `story_b` 9 字复读：「。有人需要我，我就」 | 扩写↔主体复读 | 同上 |
| 5 | 「去年他去社保局办事」↔ 1998 年考勤表 +「12年下来」 | 时间线链 | `PERIOD_MONTH_YEAR` 只查「每月×12≠一年」，不查「相对时间 + 绝对年份」 |
| 6 | 「我等这句话等了二十六年」↔ 1998→2014 = 16 年 | 时间线链 | 同上 |
| 7 | **理疗骗局算账：4800+6800+9800 = 21400，文中写「2万1」= 21000，差 400** | 金额链（分项 vs 总额） | `SPLIT_VS_TOTAL` 只在**同一句/相邻句**内比对；这里是「三项商品价」vs「另一句的总结总额」 |
| 8 | 「出门还是六点」↔ 结尾「早上7点去菜市场」 | 时间线链 | 无规则覆盖「同一角色的日常作息」跨字段不一致 |

**最严重的是第 7 条** —— 头条中老年读者最爱「算账」题材，读者一按计算器就穿帮。

---

## 二、为什么三条审计工具全绿

- `audit_rendered_article.py` —— 测**长度与结构**（字数、段落齐不齐、配图数、标签数、微头条字数区间）。它**不读内容语义**。
- `lint_content_consistency.py` —— 测**单字段内的算式**与**角色存在性**。它按「字段」切分单元，
  **不比对两个不同字段之间的重复**，也不比对「商品明细」vs「另一句的总结」。
- `check_pool_type_false_positives.py` —— 测**规则本身会不会误报**。

**共同盲区：跨字段的关系。** 三者都只看「一条内容内部」或「一个字段内部」，
没有一个在问「这句话跟另一句话对得上吗」。

---

## 三、新增检测方法（2026-11-16 实测有效）

### ① 全字段两两公共子串扫描（阈值 8 字，比 linter 的 10 更严）

当晚实测：`GOLDEN_ECHO` 的 10 字阈值**全绿放过了 3 处真实复读**
（12 字 / 11 字 / 9 字各一处）。**9 字那处差一个字就漏报。**

```python
import itertools
def lcs(a, b):
    """最长公共子串"""
    best = ''
    for i in range(len(a)):
        for j in range(i + len(best) + 1, len(a) + 1):
            if a[i:j] in b and len(a[i:j]) > len(best):
                best = a[i:j]
    return best

FIELDS = {
    'story_a': t['story_a'], 'story_a_dialogue': t['story_a_dialogue'],
    'story_a_ending': t['story_a_ending'], 'ext_a': ea,
    'story_b': t['story_b'], 'story_b_ending': t['story_b_ending'], 'ext_b': eb,
    'viewpoint': t['viewpoint'], 'action': t['action'],
    'golden1': t['golden1'], 'golden2': t['golden2'], 'golden3': t['golden3'],
    'hook': t['hook'], 'title': t['title'],
}
for a, b in itertools.combinations(FIELDS, 2):
    s = lcs(FIELDS[a], FIELDS[b])
    if len(s) >= 8:          # ← 8，不是 10
        print(f"  {a} ↔ {b}: {len(s)}字 「{s}」")
```

**范围必须包含 `ext_a` / `ext_b`** —— 当晚 2 处复读就藏在扩写段里
（`ext_a`↔`story_a` 11 字、`ext_b`↔`story_b` 9 字）。

**阈值取 8 的理由**：10 字阈值是经验值，会漏掉「差一个字」的复读；
8 字仍基本不误报（正常叙述不会有 8 字完全重合且语序一致的片段）。
当晚跑完：修复前 6 处 → 修复后 3 处，且剩余 3 处都是**合理的呼应**
（`story_a`↔`story_a_dialogue` 的「儿子说：'爸，我」、`story_a`↔`story_a_ending`
的「去菜市场，跟李大姐」、`story_a`↔`hook` 的「，没人知道。晚上」）—— 人工确认后不改。

### ② 钩子整句复读检测（逐句归一化后 `in`）

```python
body = ''.join(FIELDS[k] for k in (
    'story_a','story_a_dialogue','story_a_ending','ext_a',
    'story_b','story_b_ending','ext_b','viewpoint','action'))
bn = re.sub(r'[^\u4e00-\u9fff]', '', body)
for sent in re.split(r'[。！？；]', FIELDS['hook']):
    s = re.sub(r'[^\u4e00-\u9fff]', '', sent)
    if len(s) >= 6 and s in bn:
        print("钩子整句在正文逐字出现:", sent)
```

**修法：改正文那一句，不动钩子。** 钩子是流量钩子，优先级高于正文顺滑。
修完后钩子短语在全文应**只出现 1 次**（钩子里那一次）。

### ③ 分项 vs 声明总额的跨句扫描

```python
# 找出同时含「明细数字」和「总结性总额词」的段落，人工核对
for m in re.finditer(r'[^。\n]{0,120}(?:一共|总共|加起来|合计|前后)[^。\n]{0,60}[。\n]', blob):
    nums = re.findall(r'(\d+(?:\.\d+)?)\s*(?:块|元|万)?', m.group(0))
    if len(nums) >= 2:
        print(m.group(0), nums)     # ← 人工加一遍
```

**这条必须跨句扫，不能只看单字段。** 当晚的三项商品价在一句、
总额「2万1」在五段之后 —— `SPLIT_VS_TOTAL` 完全够不着。

### ④ 中文口语金额缩写的人工加数

当晚两处：`4800+6800+9800=21400`（文中 21000）、
`62×12=744` / `744×12=8928`（这两处**是对的**）。

⚠️ **人名/数字抽取类正则会漏**：`9800` 和 `9400` 只差一个数字，
`re.findall(r'\d+')` 两处都抓到 —— 但**分项和与总额的关系**需要人工心算。
**linter 的 `_num()` 口径正确（解析器自检通过），它只是不知道该比哪两个数。**

---

## 四、修复顺序与纪律

当晚 8 处全部**改源码不重跑**（Case R），遵守：

1. **逐条落盘**：每条替换成功后立即写文件，失败的单独报告。
2. **锚点用最小唯一片段**：`src.count(old) != 1` 就跳过并打印上下文，**不猜原文**。
3. **回读断言**：`assert old not in new_src and new in new_src`。
4. **改完 `py_compile` 三个源文件**。
5. **隔离 harness 验证**（见 `isolated-verification-harness.md`）：
   临时 history → 强制选中方向 → 调真实生产函数 → 对隔离产物跑审计 + 跑**双向**定点断言。

### ⚠️ 修复钩子复读时，断言该怎么写（当晚踩了一次）

**错误断言**：`"他给自己倒了一杯水" not in full` —— 会**假失败**，
因为钩子本来就该保留这句话（纪律是「改正文，不动钩子」）。

**正确断言**：数出现次数。

```python
assert full.count("他给自己倒了一杯水") == 1     # 只在钩子里
assert full.count("桌上有头天烧剩的半壶水") == 1  # 正文改写后
```

**通用规则：涉及「钩子 ↔ 正文」的断言要区分两处位置，不能用简单的 `not in`。**

---

## 五、隔离 harness 的两个 API 陷阱（当晚实测）

### ① `generate_article()` 返回的是**三元组**，不是字符串

```python
html_content, plain_text, topic = T.generate_article()   # ✅
# html_content, plain_text, topic = T.generate_article()
full = html_content + '\n'.join(m['html'] for m in micros)  # ✅
```

⚠️ 写成 `full = T.generate_article() + ...` 会报
`TypeError: can only concatenate tuple (not "str") to tuple`。

### ② `generate_micro_articles()` 的参数名会变

⚠️ **2026-11-17 再次实测修正（本节上一版记录有误）**：
2026-11-16 当晚记的是「该函数**不接受参数**」—— **错了**。
2026-11-17 实测真实签名是：

```python
inspect.signature(T.generate_micro_articles)   # → (long_direction=None)
```

**它接受 `long_direction=` 参数**，且内部调用
`_pick_micro_index(used_indices, exclude_directions=shadow_dirs)`。
2026-11-16 之所以「不接受参数」是因为当晚调用时把位置参数传错了位置。

⚠️ **monkey-patch `_pick_micro_index` 时，签名必须带全部关键字参数** ——
写成 `def fake(used_indices, history_path=None)` 会在
`exclude_directions=shadow_dirs` 这个关键字实参上抛
`TypeError: fake_pick_micro() got an unexpected keyword argument 'exclude_directions'`。

✅ **正确写法**：

```python
def fake_pick_micro(used_indices, history_path=None, exclude_directions=()):
    ...
```

**做法：先 `inspect.getsource()` / `inspect.signature()` 确认签名再 monkey-patch**，
不要照抄上次会话的调用方式 —— **这个 API 每个版本都在变**。

```python
import inspect
print(inspect.signature(T.generate_micro_articles))
print(inspect.signature(T._pick_micro_index))
print(inspect.getsource(T.generate_micro_articles)[-700:])
```

### ③ 选题池分散在**三个源文件**里（2026-11-17 实测踩了 3 次）

改文案前**必须先定位在哪个文件**，否则锚点永远匹配不上：

| 文件 | 内容 |
|---|---|
| `toutiao-article-daily.py` | 基础 `TOPICS_POOL`（10 条长文）/ `MICRO_TOPICS_POOL`（10 条微头条）/ `DIRECTION_QUESTIONS` |
| `toutiao_topics_extra.py` | `EXTRA_TOPICS`（扩库长文）/ `EXTRA_MICRO_TOPICS`（扩库微头条） |
| `toutiao_story_extensions.py` | `STORY_EXTENSIONS`（扩写段落，每方向一个 `(a, b)` 二元组） |

**定位法**：`for f in 三个文件: print(f, txt.count(key))` —— 当晚连踩 3 次「以为在这个文件、实际在那个文件」。

⚠️ 跨池扫描时**长文池要包含 `EXTRA_TOPICS`**（运行时是
`TOPICS_POOL = TOPICS_POOL + EXTRA_TOPICS`），否则会漏掉一半方向。

---

## 六、通读清单更新

既有清单已到 13 条链。本次新增：

| # | 链 | 问什么 |
|---|---|---|
| ⑭ | **分项-总额链** | 明细里的每一项加起来 = 声明的总额吗？（跨句） |
| ⑮ | **全字段复读链** | 任意两个字段之间有没有 ≥8 字的逐字重合？（含扩写段） |

---

## 七、给 linter 的后续建议（尚未落地）

现有 `GOLDEN_ECHO` 只查 `golden1/2/3` ↔ 正文。**应新增一条
`FIELD_ECHO`：任意两个正文字段之间 ≥8 字公共子串** —— 当晚可抓 3 处。
⚠️ 落地时必须按既有三步验证：
① `_self_test()` 正例不报 + 反例必报；② 真实反例断言 exit 1；
③ **跨池型不误报**（微头条池字段结构不同，装配口径必须分叉）。
