# wechat-article-daily.py 参考实现

## 概述

独立公众号情感长文脚本，路径：`~/.hermes/cron/scripts/wechat-article-daily.py`

**特征**：双故事对比论证法，专门走情感/家庭/婚姻话题，内置选题库（TOPICS_POOL），人设"人间清醒观察家"。

## 与 unified-content-daily.py 的区别

| 维度 | wechat-article-daily.py | unified-content-daily.py |
|------|------------------------|--------------------------|
| 选题来源 | 内置固定选题库 | 实时抓取热搜+搜索真实爆款 |
| 内容风格 | 情感/家庭/婚姻，固定双故事结构 | B方案·爆款标题+真实内容生成 |
| 推送时间 | 07:00（建议） | 17:00 |
| 是否有 cron 任务 | ❌ 无（2026-05-29 时无独立任务，需单独创建） | ✅ 有（7226bc84df96） |

## 创建 07:00 公众号 cron 任务的命令

```python
# 在 Hermes 中用 cronjob(action='create') 创建
cronjob(
    action='create',
    name='公众号情感长文',
    prompt='运行 ~/.hermes/cron/scripts/wechat-article-daily.py 生成当日微信公众号情感长文，发送HTML邮件到 569545015@qq.com。发件人：权权的HERMES（公众号）。内容方向：情感/家庭/婚姻话题，使用双故事论证法。',
    schedule='0 7 * * *',
    deliver='origin'
)
```

## TOPICS_POOL 数据结构

```python
{
    "direction": "养老安全",
    "title": "70岁以上丧偶老人，千万别独居：两个邻居的血泪教训",
    "hook": "这是网友@李阿姨 的投稿，看完我沉默了很久。邻居王大妈...",
    "story_a": "王大妈住在老城区...",
    "story_a_dialogue": "小芳后来在妈的遗体前哭着说...",
    "story_a_ending": "王大妈的存折上还有8万块，一分没花。",
    "story_b": "张大爷的情况跟老刘很像...",
    "story_b_ending": "张大爷说，人老了，最蠢的做法就是逞强...",
    "viewpoint": "独居不是自由，是风险。老人学会'示弱'，才是对子女最大的体谅。",
    "action": "如果你超过65岁，子女又不在身边，别逞强。跟儿女实话实说...",
    "golden1": "独居不是自由，是风险。等出事了再说'我没事'，就晚了。",
    "golden2": "对儿女'示弱'不是矫情，是老年人的生存智慧。",
    "golden3": "存折上的钱，人没了就是废纸。活着，花了才是自己的。",
    "tags": ["养老", "独居", "安全", "子女"],
    "cover_prompt": "A documentary-style photo of an elderly Chinese woman...",
    "in_image_prompts": [
        {"num": 1, "scene": "故事A-独居场景", "desc": "...", "prompt": "..."},
        {"num": 2, "scene": "故事B-子女陪伴", "desc": "...", "prompt": "..."},
        {"num": 3, "scene": "观点场景", "desc": "...", "prompt": "..."},
    ],
}
```

## 爆款标题特征

- 具体年龄/数字/身份，不用"老年人""长辈"
- 标题公式：数字+冲突 / 反常识+情绪 / 具体场景
- 禁止双层书名号《《》》

**示例**：
- ✅ "35岁被裁员，我见了两个男人，一个废了，一个活了"
- ✅ "以为来日方长，结果连一面都没见到"
- ❌ "《《竖版粉彩盛典》：看完终于明白了"（双层书名号）