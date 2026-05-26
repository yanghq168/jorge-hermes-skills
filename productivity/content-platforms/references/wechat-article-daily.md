# 公众号文章生成器 wechat-article-daily.py

## 脚本路径
`~/.hermes/cron/scripts/wechat-article-daily.py`

## 定时任务
每天 07:00 运行

## 核心数据结构

### 选题库 TOPICS_POOL

每个选题包含：
```python
{
    "direction": "养老安全",           # 选题方向标签
    "title": "70岁以上丧偶老人...",   # 文章标题（含具体年龄/数字）
    "hook": "这是网友@李阿姨的投稿...",  # 开篇钩子（网友投稿格式）
    "story_a": "...",                 # 故事A内容（含\n\n分段）
    "story_a_dialogue": "...",        # 故事A关键对话
    "story_a_ending": "...",          # 故事A结尾句
    "story_b": "...",
    "story_b_ending":...",
    "viewpoint": "...",              # 作者观点（反共识）
    "action": "...",                 # 给读者的行动建议
    "golden1/2/3": "...",            # 三句金句
    "tags": ["养老", "独居"...],     # 话题标签（4-5个）
    "cover_prompt": "...",           # 封面图英文提示词（no text, 16:9）
    "in_image_prompts": [            # 3张文中配图提示词
        {"num": 1, "scene": "故事A-xxx", "desc": "...", "prompt": "..."},
        ...
    ]
}
```

### 模板变量（HTML_TEMPLATE.format 调用）

```python
html_content = HTML_TEMPLATE.format(
    title=topic['title'],
    date=date_str,              # "2026年05月27日"
    direction=topic['direction'],
    gen_time=gen_time,          # "01:04"
    hook=topic['hook'],
    story_a_content=story_a_content,  # 分段后的<p>标签
    story_a_dialogue=topic['story_a_dialogue'],
    story_a_ending=topic['story_a_ending'],
    story_b_content=story_b_content,
    story_b_ending=topic['story_b_ending'],
    viewpoint=topic['viewpoint'],
    action=topic['action'],
    golden1/2/3=topic['golden1/2/3'],
    question=question,          # 随机选取的互动问题
    tags_html=tags_html,        # <span class="hashtag">#xxx</span>
    hashtags_html=hashtags_html,
    cover_prompt=topic['cover_prompt'],
    in_image_prompts_html=in_image_prompts_html,  # 拼接的HTML字符串
    checklist_html=checklist_html,
)
```

### 检查清单 CHECKLIST_ITEMS

```python
CHECKLIST_ITEMS = [
    "开头是不是「网友投稿/邻居的事/亲戚家的事」？",
    "标题有没有具体年龄/数字/身份？（禁用「老年人」「长辈」）",
    "有没有两个故事？（故事A+故事B，不是只有一个案例）",
    "故事里有没有具体数字？（存款、房产、退休金、随礼金额）",
    "有没有对话或心理描写？（不是干巴巴叙述）",
    "观点是不是反共识？（挑战「养儿防老」「勤俭是德」等传统观念）",
    "结尾有没有给读者「情绪出口」和「行动台阶」？",
    "互动问题是不是争议性的？（能让两拨人想转发讨论）",
    "3个金句位置对不对？（故事A结尾、故事B结尾、文章结尾）",
    "配图提示词有没有「无文字/no text」？",
]
```

## 邮件发送格式

```python
msg['From'] = f"围炉家常话 <{SMTP_USER}>"
msg['Subject'] = f"【{direction}】{subject}"
```

## 关键实现细节

1. **故事分段**：用 `split('\n\n')` 分段，再用 `<p>{p.strip()}</p>` 包裹
2. **CSS大括号双写**：HTML模板内的CSS必须 `{{` `}}`，因为Python `.format()` 会消耗单大括号
3. **配图提示词**：英文为主，结尾加 `--ar 16:9 --v 6`，内容描述要有情绪张力
4. **互动问题**：从 QUESTION_TEMPLATES 随机选取，要有争议性
5. **金句高亮**：金句中的关键词用 `<strong>` 标签包裹，CSS颜色 #FF4D6D