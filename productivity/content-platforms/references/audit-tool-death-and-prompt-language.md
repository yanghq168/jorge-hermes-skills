# 缺陷七：审计工具自己死了 + 配图提示词语言 + 周期频次链（2026-11-05 头条号实测）

> 承接 `references/orphan-extensions-and-hand-arithmetic-audit.md`（缺陷六）。
> 那一类讲「内容缺陷逃过审计」；这一类讲**审计工具本身失效**，
> 以及两类新缺陷（配图提示词混中文、周期频次 vs 年度汇总）。

## 一、🔴🔴 最重要的教训：审计工具「死了」但没人发现

### 现象

2026-11-04 加 ORPHAN 规则时，只写了内部实现 `_ext_orphan_issues()`，
却在 `_self_test()` 里调用了一个**从未定义**的 `check_orphan_character()`：

```python
# lint_content_consistency.py 的 _self_test() 里
ok = check_orphan_character('孙大爷69岁…', '过户那天，孙大爷从房管局出来。')
# NameError: name 'check_orphan_character' is not defined
```

后果链：

1. **linter 从 11-04 起每次都崩在自检上** → 退出码 1
2. 退出码 1 的语义是「内容有问题」，但实际是「**工具自己坏了**」→ **语义被误读**
3. 更糟：**ORPHAN 规则从未接入 `lint()`** —— 加了函数、写了自检，却忘了挂到主流程
4. 于是 11-04、11-05 两晚的「linter exit 0 全绿」是**假的** —— 根本没跑到检查

### 为什么会连着坏两晚没人发现

**因为「工具崩了」和「内容有问题」返回同一个退出码 1。**
当晚的会话只看了 stdout 的「✅ 全部检查通过」和 stderr 的一行 traceback，
没有把退出码**单独**核对。

### ✅ 硬规则

1. **跑审计工具必须单独看退出码，不能看管道里的 tail/head。**
   `python3 linter.py ... | tail -20` → `$?` 是 **tail 的退出码**，不是 linter 的。
   实测踩坑：`python3 linter.py ... | tail -30; echo "EXIT=$?"` 打印 `EXIT=0`，
   而 linter 实际 exit 1 且 stdout **完全为空**。
   ```bash
   # ✅ 正确
   python3 lint_content_consistency.py --pool ... --extensions ... > /tmp/lo.txt 2>/tmp/le.txt
   echo "REAL EXIT=$?"; cat /tmp/lo.txt; echo "--stderr--"; cat /tmp/le.txt
   ```
   **判别口诀：stdout 为空 + stderr 有 traceback = 工具崩了，不是内容有问题。**
2. **新增规则时，「写了函数」不等于「规则生效」。** 必须**实测会 fire**：
   造一个真实反例（临时 pool + 临时 extensions 文件），断言退出码 1 且报出预期 code。
   只跑「干净内容 → exit 0」证明不了规则接上了 —— 空集合也 exit 0。
3. **退出码 2（工具自检失败）的语义必须真的用起来。**
   自检崩溃时应当 `raise SystemExit(2)`，而不是被 `NameError` 带成 1。

### 本次的完整修法

```python
# ① 补一个两参版实现（自检用），契约统一为 (base_text, ext_text)
def check_orphan_character(base_text, ext_text):
    ...
# ② 自检改成两参调用 + 加一条「空扩写不得报错」
# ③ 在 lint() 里接入（关键是这步，11-04 漏了）
if ext:
    ea, eb = _ext_pair(ext)
    base_a = '\n'.join(x for x in (t.get('story_a',''), t.get('story_a_dialogue',''),
                                  t.get('story_a_ending','')) if x)
    base_b = '\n'.join(x for x in (t.get('story_b',''), t.get('story_b_ending','')) if x)
    for code, msg, ctx in _ext_orphan_issues(direction, base_a, ea, '故事A扩写'):
        issues.append({...})
    for code, msg, ctx in _ext_orphan_issues(direction, base_b, eb, '故事B扩写'):
        issues.append({...})
```

验证方式（**必须做**，否则等于没修）：
```python
# 造临时 pool + 临时 ext，扩写里放一个真孤儿「老李头」
# 期望：exit 1 + 报出 ORPHAN_CHARACTER
# 同时：干净内容 exit 0 + 自检通过
```

## 二、🔴 新缺陷类：配图提示词里混入中文（PROMPT_HAS_CJK）

### 现象

2026-11-05 手动扫全部 20 条选题的配图提示词，抓到 2 处：

```
赡养义务 img1: "...daughter-in-law's背影 walking away with unhappy expression..."
晚年孤独 img2: "...empty water glass beside him,发烧没人知道的场景..."
```

**为什么严重**：提示词是喂给 DALL·E / image2 的**英文** prompt。
中文片段会被模型当成「要画在画面里的文字」—— 读者拿到的是一张
**带乱码汉字**的配图。这比提示词写得不够好严重得多。

### 修法 + 永久规则

```python
def check_prompt_language(text):
    hits = re.findall(r'[\u4e00-\u9fff]+', text)
    if hits:
        issues.append(('PROMPT_HAS_CJK', ...))
```

**接入点必须选对字段**：
- ✅ 查 `cover_prompt`、`in_image_prompts[*].prompt`
- ❌ **不要**查 `in_image_prompts[*].desc` / `*.scene` —— 那是**中文给人看的**
  （「故事A-看脸色吃饭」「寄人篱下场景：儿媳给脸色看」），中文是正常的、正确的。

在 `lint()` 里要**单独走一条**（不能指望 `FIELD_CHECKERS` 遍历顶层字段），
因为 `in_image_prompts` 是**列表**：
```python
prompt_fields = [('cover_prompt', t.get('cover_prompt', ''))]
for ip in t.get('in_image_prompts', []) or []:
    if isinstance(ip, dict):
        prompt_fields.append((f'in_image_prompts[{ip.get("num","?")}].prompt', ip.get('prompt','')))
```

## 三、🔴 新缺陷类：周期频次 vs 年度汇总（PERIODIC_VS_YEARLY）

### 现象

赡养义务故事B：主体段写「大儿子**每两周**来一次」，
年底汇总写「今年大儿子来了 **24** 次」。
读者一算：每两周 = 26 次/年 ≠ 24 次 → **穿帮**。

### 为什么旧规则漏掉

`FREQ_CONFLICT` 的正则是
`([\d零一二两三四五六七八九十]+)\s*次(?:电话|回来|来看|回来看|探?望|轮休)` ——
只匹配「N次**动词**」，匹配不到「今年大儿子**来了** 24 次」里的「来了N次」。
所以全程绿灯。

### 修法（新增规则）

```python
def check_periodic_vs_yearly(text):
    # ① 周期频次 → 推算一年次数
    for mm in re.finditer(r'每\s*([\d零一二两三四五六七八九十两半]+)\s*(周|星期|礼拜|个月|月)\s*(?:来|去|看|打|聚|回)', text):
        # 「每半个月」→ 0.5 个月 → 12/0.5 = 24 次/年
        # 「每两周」→ 52/2 = 26 次/年
        # 「每个月」→ 12 次/年
    # ② 年度汇总次数
    for mm in re.finditer(r'今年[^。；]{0,40}?([\d零一二两三四五六七八九十]+)\s*次', text):
    # ③ 差值 > 0.6 才报（允许四舍五入）
```

**内容修法**：把「每两周来一次」改成「**每半个月**来一次」（= 24 次/年 ✔）。
选「每半个月」而不是把汇总改成 26 次，是因为 24 次这个数字本身和
「照顾我最多」的叙事更贴合，且改动面更小。

### 自检算例（正例不报 + 反例必报）

```
正例：'大儿子每半个月来一次…今年大儿子来了24次'      → 不报
反例：'大儿子每两周来一次…今年大儿子来了24次'        → 必报（26≠24）
正例：'二儿子每个月来一次。今年二儿子来了12次'        → 不报（12=12）
```

## 四、本次其余 5 处读者可见硬伤（都是「跨段口径不一致」）

| # | 缺陷 | 修法 |
|---|------|------|
| 1 | 大儿子「照顾我最多」，扩写里却在本子上「**排第三**」 | 改「你排第一」，并补一句「我记的是谁真来过，不是谁该来」 |
| 2 | 「我**那套房子**的租金」给她 —— 但她**自己住**在那套老房子里 | 改「我**楼下那套空房**的租金」 |
| 3 | 结尾「**儿孙们每周都来看她**」vs 实际最高频次是每半个月 | 改「来看她的儿子比以前**更勤了**」 |
| 4 | 养老院故事B 日程自相矛盾：主体「上午在家…下午下棋…晚上唱歌」vs 扩写「8点去公园下棋，下午打牌」 | 扩写统一为「上午在家歇着，下午去公园下棋，晚上去老年活动室唱歌」 |
| 5 | 同上 2 处配图提示词混入中文 | 见第二节 |

**共性**：全部是「**同一篇里两个地方对同一件事的取值/说法不一致**」，
正是缺陷六「通读要盯的 6 条链」的延伸 —— 本次新增第 7 条链：

> **排序/名次链**：某人是「照顾最多」，那他在任何排序/评价体系里就必须是第一。
> **空间链**：某人「拥有 X 房」且「住 X 房」时，不能同时把 X 房出租/送人。

## 五、手动扫「配图提示词混中文」的一次性配方

```python
cjk = re.compile(r'[\u4e00-\u9fff]')
for t in TOPICS_POOL:
    prompts = [('cover', t.get('cover_prompt',''))]
    for ip in t.get('in_image_prompts',[]):
        prompts.append((f"img{ip.get('num')}", ip.get('prompt','')))
    for name, pr in prompts:
        if cjk.search(pr):
            print(f"[{t['direction']}] {name}: {pr[:110]}")
```
（注意：**不要**扫 `desc` / `scene`，那两个字段本来就是中文。）

## 六、口径提醒：微头条字数按 CJK 字符数算，不是 `len()`

10 条微头条的 `len(content)` 全都 > 250（260–319），但 **CJK 字符数**
全都在 150–250 区间（185–250）。`audit_rendered_article.py` 用的是 CJK 口径，
所以「越界 0 条」是对的。**不要因为 `len()` 超了就以为越界。**

## 七、与 Case R 的关系（不变）

本次同样**改源码、不重跑已投递产物**：
- 生产 `topic_history.json` / `micro_topic_history.json` mtime 仍停在 `20:30:01`
- 隔离 harness（临时 history 文件）渲染验证：正文 3336 字、结构 10/10
- 今晚已投递的 HTML 仍是修复前版本（已由飞书送达），**修复对明晚生效**
