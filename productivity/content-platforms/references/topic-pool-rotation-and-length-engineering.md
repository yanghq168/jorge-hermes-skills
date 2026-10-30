# 选题池轮换与字数工程（内容平台通用）

> 适用范围：任何「有限选题池 + 每日自动产出」的 cron 内容脚本
> （头条号 `toutiao-article-daily.py`、公众号 `wechat-article-daily.py`、全平台 `unified-content-daily.py`）
>
> 本文件记录 2026-10-28 在头条号管线上发现并修复的三个内容质量缺陷。
> 三个缺陷**都不报错、不崩溃、调度器全绿**，但每一个都在持续消耗流量。

---

## 缺陷一：池子大小 = 轮换周期，同一标题必然重复

### 症状
`TOPICS_POOL` 6 条 + `MAX_RECENT = 5` 的去重窗口 = **6 天一轮换**。
同一篇标题每 6 天复现一次；按 65 天累计，每篇长文标题重复约 11 次。
头条老读者反复刷到逐字相同的标题会直接划走 —— 对「长文吃流量」是硬伤。

### 三个必须一起改的量
| 量 | 旧值 | 新值 | 说明 |
|---|---|---|---|
| 池子大小 | 6 | 10 | 轮换周期 = 池子大小 |
| 去重窗口 | 固定 5 | **跟随池子大小** | 固定窗口会让扩库失效 |
| 选择算法 | 窗口内随机 | **LRU** | 见下 |

### 关键陷阱：去重窗口必须跟随池子大小

```python
# ❌ 固定窗口：池子扩到 10 条后，窗口还是 5，扩库等于白扩
MAX_RECENT = 5

# ✅ 窗口 = 最长池 - 1
def _set_recent_window():
    global MAX_RECENT
    MAX_RECENT = max(1, max(len(TOPICS_POOL), len(MICRO_TOPICS_POOL)) - 1)
```

### 关键陷阱：窗口按「条数」算，对微头条是错的

长文 **1 条/天**，窗口 9 条 ≈ 9 天，看起来没问题。
但微头条 **2 条/天**，同样的窗口 9 条只覆盖 **4.5 天** ——
窗口还没填满，`fresh` 子集里仍有 7-8 条候选，随机选就有实打实的概率撞车。

30 天模拟实测（旧算法）：
```
微头条: 连续重复 6 次, 只覆盖到 6/10 个方向
        分布 {'婆媳关系':15, '老年婚姻':12, '养老金':11, ...}
```

### 修复：改用 LRU（Least Recently Used）

「取**最久没出现过**的那条」，没有随机撞车，池子能跑满完整周期。

```python
def _pick_lru(pool, history_path, key='direction', exclude=()):
    history = _load_history(history_path)
    last_seen = {}
    for i, h in enumerate(history):
        k = _hist_key(h)
        if k:
            last_seen[k] = i          # 索引越大 = 最近出现过
    exclude = set(exclude or ())
    avail = [t for t in pool if str(t.get(key)) not in exclude] or list(pool)
    def _rank(t):
        return last_seen.get(str(t.get(key)), -1)   # 从未出现 = -1 = 最旧
    oldest = min(_rank(t) for t in avail)
    ties = [t for t in avail if _rank(t) == oldest]
    return random.choice(ties)
```

30 天模拟结果（修复后）：
```
长文:   连续重复 0, 10/10 方向, 分布各 3 次完全均匀
微头条: 连续重复 0, 10/10 方向, 分布各 6 次完全均匀
```

### 必须配套的两个工程细节

**① 同日两条微头条要按 `direction` 排除，不是按 index**
```python
used_dirs = {str(MICRO_TOPICS_POOL[i].get('direction')) for i in used}
topic = _pick_lru(MICRO_TOPICS_POOL, hpath, key='direction', exclude=used_dirs)
```

**② 读取端必须兼容多种历史字段名**
`_record_topic()` 写入 `'key'`，旧代码读 `'direction'` —— 键名不匹配会让去重**静默失效**：
`recent` 恒为 `['None','None',...]` → `fresh` 恒等于全池。
```python
def _hist_key(entry):
    for k in ('key', 'direction'):
        v = entry.get(k)
        if v is not None and str(v) not in ('', 'None'):
            return str(v)
    return ''
```

### 验证脚本必须用临时 history 文件
用真实 `topic_history.json` 做模拟会**污染生产数据**并让结果失真
（早期一次模拟因此得出「微头条只覆盖 4/10」的假结论）。
```python
tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8')
tmp.write('[]'); tmp.close()
T.HISTORY_FILE = tmp.name          # 重定向
# ... 模拟 ...
os.unlink(tmp.name)
```
另外：被测函数**必须支持注入 history 路径**，否则单测永远在读生产文件。
```python
def _pick_micro_index(used_indices, history_path=None):
    hpath = history_path or MICRO_HISTORY_FILE
```

### 扩库放在独立模块
主脚本已 85 KB，再加选题会继续膨胀。拆分方式：
- `toutiao_topics_extra.py` — `EXTRA_TOPICS` / `EXTRA_MICRO_TOPICS`
- `toutiao_story_extensions.py` — `STORY_EXTENSIONS`（见缺陷三）

```python
try:
    import os as _os_exp, sys as _sys_exp
    _dir = _os_exp.path.dirname(_os_exp.path.abspath(__file__))
    if _dir not in _sys_exp.path:
        _sys_exp.path.insert(0, _dir)
    from toutiao_topics_extra import EXTRA_TOPICS, EXTRA_MICRO_TOPICS
    TOPICS_POOL = TOPICS_POOL + EXTRA_TOPICS
except ImportError as _e:
    print(f'⚠️ 扩库加载失败，沿用内置选题池: {_e}')
```

⚠️ **不要依赖 `sys.path[0]`**：脚本文件名带连字符时无法 `import`，
测试只能用 `importlib.util.spec_from_file_location` 加载；
而 `sys.path[0]` 在 cron 下是脚本目录、在测试下是 cwd —— 所以必须显式插入 `__file__` 目录。

### 导入时做字段契约自检
```python
_LONG_KEYS = {'direction','category','title','hook','story_a','story_a_dialogue',
              'story_a_ending','story_b','story_b_ending','viewpoint','action',
              'golden1','golden2','golden3','tags','cover_prompt','in_image_prompts'}
for _t in TOPICS_POOL:
    _missing = _LONG_KEYS - set(_t)
    if _missing:
        raise ValueError(f'长文选题 {_t.get("title")!r} 缺字段: {_missing}')
```

---

## 缺陷二：脚本自带的检查清单常年不达标（自相矛盾）

### 症状
脚本的 `CHECKLIST_ITEMS` 里明明白白写着：
```
"文章字数够不够长？（头条长文吃流量，1500字以上）"
```
但实测每篇正文（故事A+故事B+对话+结局）只有 **813-1159** 中文字，
全篇 1072-1446 —— **没有一篇达标**。清单是给人看的，从来没人真的量过。

### 修复：给每个方向补「细节段」
补的是**具体数字、动作、对话**，不是空泛抒情 —— 否则字数上去了，完读率下来了。

`STORY_EXTENSIONS` 结构（key = direction）：
```python
STORY_EXTENSIONS = {
    "赡养义务": (
        "<追加到 story_a 末尾的段落>",
        "<追加到 story_b 末尾的段落>",
    ),
    ...
}
```

拼接：
```python
def _apply_story_extensions(topic):
    ext = STORY_EXTENSIONS.get(topic.get('direction'))
    if not ext:
        return topic
    extra_a, extra_b = ext
    topic['story_a'] = topic['story_a'] + '\n\n' + extra_a
    topic['story_b'] = topic['story_b'] + '\n\n' + extra_b
    return topic
```

### 效果
| 方向 | 扩写前正文 | 扩写后正文 | 全篇 |
|---|---|---|---|
| 遗产分配 | 813 | **1273** | 1532 |
| 赡养义务 | 938 | **1387** | 1636 |
| 亲戚恩怨 | 899 | **1308** | 1550 |
| 房产纠纷 | 979 | **1493** | 1742 |
| 晚年孤独 | 939 | **1308** | 1592 |
| 随礼人情 | 932 | **1364** | 1619 |
| 养老院 | 1049 | **1548** | 1816 |
| 兄弟姐妹 | 1105 | **1604** | 1866 |
| 再婚财产 | 1051 | **1536** | 1814 |
| 远居赡养 | 1159 | **1673** | 1960 |

### 通用规则
**检查清单里的数字必须被真正测量。** 写进 `CHECKLIST_ITEMS` 的每个数字
（字数、张数、条数）都应该有一条对应的自动断言，否则它只是一句愿望。

---

## 缺陷三：`str.format()` 静默丢弃模板没用到的 kwargs

`HTML_TEMPLATE` 只有 `{story_a_content}` / `{story_b_content}`，
但 `generate_article()` 还传了 `story_a_dialogue` / `story_a_ending` / `story_b_ending`。
`str.format()` 对**多余的 kwargs 不报错**（只对*缺失的*占位符报 KeyError），
于是三个字段被静默丢弃 —— 每一篇文章的「故事」都缺了对话和结局，
直接违反「故事要完整」。

### 检测（任何模板/生成器改动后必做）
```python
import re
long_ph = set(re.findall(r'\{([a-z_0-9]+)\}', HTML_TEMPLATE))
provided = {'title','date','direction', ...}          # generate_article() 提供的 kwargs
print("会 KeyError 的:", long_ph - provided)
print("会被静默丢弃的:", provided - long_ph)          # ← 这个为空才安全
```

### 规则
> **验产物，不验过程。** "渲染没报错" ≠ "内容完整"。
> 每次改动生成模板后，必须回读渲染结果并 grep 关键段落是否真的出现。

---

## 缺陷四：检查清单自己会漂移，而且它**被渲染进产物**发给读者

### 症状
2026-10-30 审计发现：脚本 `CHECKLIST_ITEMS` 里写的是

```
"发件人是否为「权权的HERMES（头条）」？"
```

而 `send_email()` 里真正的 `msg['From']` 一直是

```python
msg['From'] = formataddr((str(Header('围炉家常话（头条）', 'utf-8')), SMTP_USER))
```

v1.1.0 改发件人时**只改了 `send_email()`，没改清单那一行**。
更要命的是 `CHECKLIST_ITEMS` 不是注释 —— 它被
`checklist_html = '\n'.join(...)` 渲染成文章底部的「发布前检查清单」区块，
**每篇文章都在对读者说「请确认发件人是权权的HERMES（头条）」**，而它明明是围炉家常话。

同一次审计还发现版本横幅同样漂移：文件头与 `main()` 打印的仍是 `v1.1.0`，
而代码功能早已到 v1.2.x（扩库 10 条 + LRU + 字数扩写）。

### 根因
**同一个身份/版本字符串在脚本里出现了 N 处，改一处忘了改另一处。**
前面三个缺陷都是「机制错了」，这个是**「机制对、但引用漂移了」**——
它不会让任何断言失败，只是让产品开始说假话。

### 修复
```python
# CHECKLIST_ITEMS 里
"发件人是否为「围炉家常话（头条）」？",     # ← 与 msg['From'] 保持一致
```
同时把文件头与 `main()` 横幅的版本号更新为 `v1.2.2`，
横幅主体名也从「权权的HERMES」改成「围炉家常话」。

### 规则
> **任何在多处出现的值（品牌名、发件人、版本号、路径、账号）都要对着唯一真源做断言，不要靠眼睛扫。**
> 尤其：**被渲染进产物的字符串，本身就是产物的一部分**，它漂移了 = 出货了错误信息给用户。

一行检查（把同一身份的所有出现位置并排打出来，肉眼对）：
```bash
grep -rn "围炉家常话\|权权的HERMES" ~/.hermes/cron/scripts/*.py
grep -n "发件人是否为" ~/.hermes/cron/scripts/toutiao-article-daily.py
```

**版本号是长期脚本里最容易长期发臭的字段** —— 和它描述的功能在同一次编辑里 bump。

### 附：测量产物时最容易踩的两个坑

1. **要测「最终装配后的产物」，不是中间返回值。**
   `generate_article()` 只返回长文 HTML；微头条 HTML 是在 `send_email()` 里
   `html + '\n'.join(m['html'] for m in micros)` 才拼上去的。
   只测 `generate_article()` 的返回值 → 会误判「微头条缺失」。

2. **微头条的字数要测选题池的 `content` 字段，不是渲染块。**
   渲染块 = content + 对话高亮 + 配图提示词 + 标签。
   实测：content 250 字（合规）→ 渲染块读到 322 字，看起来像违反 250 上限 —— **那是量错了对象**。
   受 150-250 约束的是 `MICRO_TOPICS_POOL[*]['content']`。

现成脚本：`scripts/audit_rendered_article.py`（本技能内），一条命令测完
字数、结构完整性、配图数、标签数、微头条区间：
```bash
python3 scripts/audit_rendered_article.py \
    ~/.hermes/cron/outbox/toutiao/20261030_2030_兄弟姐妹.html \
    --pool ~/.hermes/cron/scripts/toutiao-article-daily.py
```

---

## 端到端回归验证模板（改完必跑）

```python
# 1) 池子与窗口
assert len(T.TOPICS_POOL) == 10 and len(T.MICRO_TOPICS_POOL) == 10
assert T.MAX_RECENT == max(len(T.TOPICS_POOL), len(T.MICRO_TOPICS_POOL)) - 1

# 2) 方向/标题唯一
assert len({t['direction'] for t in T.TOPICS_POOL}) == len(T.TOPICS_POOL)
assert len({t['title']     for t in T.TOPICS_POOL}) == len(T.TOPICS_POOL)

# 3) 模板契约
assert not (set(re.findall(r'\{([a-z_0-9]+)\}', T.HTML_TEMPLATE)) - provided)

# 4) 30 天轮换模拟（临时 history）
#    长文: 连续重复 0, 10/10 覆盖, 分布各 3 次
#    微头条: 连续重复 0, 10/10 覆盖, 分布各 6 次

# 5) 字数达标
#    长文正文 ≥1100, 全篇 ≥1500; 微头条 content ∈ [150,250]

# 6) 渲染回归：每条长文都能渲染出完整 HTML，三段齐全
#
# 6b) 装配口径：微头条 HTML 是在 send_email() 里才拼上长文的，
#     测产物必须测装配后的全文，不能只测 generate_article() 的返回值
#     full = html + '\n'.join(m['html'] for m in micros)

# 6c) 身份字符串一致性（缺陷四）：
#     清单里渲染出去的字符串必须 == 代码里实际用的值
assert '发件人是否为「围炉家常话（头条）」？' in full
assert '权权的HERMES（头条）' not in full        # 旧串不得残留

# 7) 生产数据未被污染
diff <(cat /tmp/bk_topic.json) ~/.hermes/cron/outbox/toutiao/topic_history.json
```

**产物审计用现成脚本**（不要手写正则）：
```bash
python3 scripts/audit_rendered_article.py <article.html> --pool <content_script.py>
```
它会正确处理「剔除提示词区块后数字数」的嵌套 div 配对，
避免非贪婪正则截断导致正文里混进英文提示词、字数虚高。

---

## 速查表

| 症状 | 根因 | 一句话修法 |
|---|---|---|
| 同一标题每 N 天复现 | 池子大小 = 轮换周期 | 扩池 + 窗口跟随池子大小 |
| 去重"配了但没生效" | 读写端字段名不一致 | `_hist_key()` 兼容读 `key`/`direction` |
| 微头条比长文更容易撞车 | 窗口按条数算，2 条/天只覆盖一半 | 改 LRU |
| 模拟结果看着不对 | 模拟读了生产 history 文件 | 临时文件 + 路径可注入 |
| 扩库加载失败 | 依赖 `sys.path[0]` | 显式插入 `__file__` 目录 |
| 内容少了一截但不报错 | `str.format()` 丢弃多余 kwargs | 比对占位符 ↔ kwargs |
| 检查清单的数字从不达标 | 清单是愿望，没人量过 | 加自动断言 + 补写细节段 |
| 清单/版本号与代码对不上 | 同一字符串散落多处，改一处忘一处 | 对着真源 grep 断言；渲染进产物的字符串更要改 |
| 审计脚本报「微头条缺失」 | 测了中间返回值，没测装配后的全文 | 复刻 `send_email()` 的拼接口径 |
| 微头条字数看着超限 | 测了渲染块（含提示词），不是 `content` 字段 | 测 `MICRO_TOPICS_POOL[*]['content']` |
