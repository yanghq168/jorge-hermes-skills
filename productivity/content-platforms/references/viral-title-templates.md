# 爆款标题模板库

> 适用场景：抖音热搜话题转公众号/头条号文章
> 来源：基于对 `unified-content-daily.py` 的分析和真实爆款标题规律研究（2026-05-28）

## 5种标题类型

### 1. 情绪冲击型
调动读者情绪开关，让读者感到"说的太对了"

```
《{word}上热搜后，我看到评论区最真实的一面》
《全网都在讨论{word}，我却想说几句真话》
《刷到{word}这个话题，我失眠了一整晚》
```

### 2. 悬念留白型
让读者必须点进去才能知道答案

```
《{word}上热搜背后，藏着一个被忽视的事实》
《关于{word}，你可能一直理解错了》
《为什么是{word}而不是别的？这届网友终于说实话了》
```

### 3. 故事钩子型
让人想知道"后来呢"，用具体数字和调研感增加可信度

```
《我把{word}研究了一周，这就是我的答案》
《关于{word}，我问了身边10个人，得到了截然不同的回答》
《{word}爆火72小时后，我决定说几句实话》
```

### 4. 反常识型
颠覆读者认知，制造认知冲突

```
《{word}被吹上天，我却觉得可以冷静一下》
《都在说{word}}好，但没人告诉你这个》
《关于{word}，我不打算跟风》
```

### 5. 身份共鸣型
让特定人群觉得"说的就是我"

```
《如果你也在刷{word}}，进来看看》
《看完{word}，我想聊聊年轻人为什么总感到累》
《{word}刷屏后：一个普通人想说几句心里话》
```

## 热词类型 → 标题类型映射

| 热词类型 | 推荐标题类型 | 原因 |
|---------|------------|------|
| 情感/家庭话题 | 故事钩子型 + 身份共鸣型 | 容易引发共情 |
| 明星/K-pop热点 | 情绪冲击型 | 情绪激动，读者想表达 |
| 社会事件 | 反常识型 + 悬念留白型 | 想了解真相 |
| 生活技巧/种草 | 悬念留白型 | 想找到答案 |

## 当前代码问题

`make_viral_title()` 当前只有4个模板，全部是 `《{word}：xxx》` 结构：

```python
if platform == '公众号':
    templates = [
        f"《{word}：这个真相很多人不知道》",
        f"《{word}：看完我沉默了》",
        f"《{word}：不是你想的那样》",
        f"《{word}：说透了这件事》",
    ]
```

**问题**：
1. 悬念感不够，读者一眼就知道是"揭秘"类型
2. 没有利用热搜词本身的流量势能
3. 情绪词太泛，"沉默""真相"用得太多

## 移植到 unified-content-daily.py

建议将 `make_viral_title()` 改为先判断热词类型（复用已有的 `_detect_real_topic()` 逻辑），再选择对应标题类型数组，最后随机抽取。

```python
def make_viral_title(word, topic_info, platform):
    """基于真实话题生成有冲击力的标题"""
    
    # 先判断热词类型
    real_topic = _detect_real_topic_static(word, topic_info)  # 新增辅助函数
    
    if platform == '公众号':
        if real_topic == 'kpop_entertainment':
            # 情绪冲击型 — 娱乐话题需要情绪爆发
            templates = 情绪冲击型_templates
        elif real_topic in ('family', 'love'):
            # 故事钩子型 + 身份共鸣型 — 情感话题需要共情
            templates = random.choice([故事钩子型_templates, 身份共鸣型_templates])
        elif real_topic in ('work', 'beauty'):
            # 悬念留白型 — 技巧/种草类需要答案
            templates = 悬念留白型_templates
        else:
            # 默认反常识型 — 生活类话题用反常识制造冲突
            templates = 反常识型_templates
    elif platform == '头条号':
        # 头条号标题更短，更直接
        ...
    
    return random.choice(templates).format(word=word)
```