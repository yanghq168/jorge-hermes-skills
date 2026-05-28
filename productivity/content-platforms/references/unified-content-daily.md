# `unified-content-daily.py` 参考实现

> 脚本路径：`~/.hermes/cron/scripts/unified-content-daily.py`
> 创建时间：2026-05-28
> 用途：每天17:00从抖音热搜采集，一套脚本生成公众号+头条+小红书+抖音四条内容

---

## 核心数据流

```
抖音热搜API (TOP 50)
    ↓ classify_word() 分类
life_emotion / work_money / science
    ↓ 取前2条/类 = 6个选题词
generate_content(word, category, hot_value)
    ↓ 每个词生成4条内容
公众号长文 + 头条长文 + 小红书图文 + 抖音口播
    ↓
公众号/头条/小红书 → HTML邮件发送
抖音口播 → 直接 print 到 stdout（Lark 对话）
```

---

## 关键函数

### `classify_word(word, label=0)`

精准分类抖音热搜词，三分类体系：

| 分类 | 关键词示例 | label 兜底 |
|------|-----------|-----------|
| `life` | 高考、亲情、爱情、宠物、美食、旅行、治愈 | label in [1, 5, 8, 9] |
| `work` | 职场、工作、赚钱、副业、618、清单 | — |
| `science` | 为什么、揭秘、科普、世界、最大、神舟 | label in [0, 16] |
| `other` | 游戏等 | label in [3] |

### `generate_image_prompt(topic_word, platform, image_slot)`

生成 ChatGPT Image2 生图提示词：

```python
def generate_image_prompt(topic_word, platform, image_slot):
    if image_slot == 'cover':
        # 封面：9:16竖版，大字标题词+暖橙渐变背景
        return (
            f"A bold typographic poster with Chinese text '{topic_word}' "
            f"in large impact font, dark background with warm orange gradient, "
            f"modern design, high contrast, cinematic lighting, --ar 9:16 --v 6"
        )
    elif image_slot == 'body':
        # 正文：根据话题类型选择场景
        if '高考' in topic_word:
            return "Warm photo of exam preparation scene, Chinese high school students, ..."
        elif any(k in topic_word for k in ['美食', '厨房', '烹饪']):
            return "Beautiful Chinese home-cooked dish on ceramic plate, ..."
        elif any(k in topic_word for k in ['旅行', '旅游', '风景']):
            return "Stunning travel photograph of scenic location, golden hour, ..."
        elif any(k in topic_word for k in ['宠物', '猫咪', '狗', '萌']):
            return "Adorable pet photo, fluffy cat or dog, cozy home environment, ..."
        elif any(k in topic_word for k in ['职场', '工作', '赚钱']):
            return "Modern office workspace, laptop and coffee, clean desk setup, ..."
        else:
            return "Relatable lifestyle photo, warm and cozy atmosphere, ..."
    else:  # ending
        # 结尾：情感落点场景
        return "Emotional reunion photo, family waiting, warm lighting, ..."
```

### `should_add_cover_text(topic_word, platform)`

判断封面图是否需要手动配文（而非让 Image2 自动生成）：

```python
def should_add_cover_text(topic_word, platform):
    cover_text_map = {
        '高考': '高考倒计时',
        '618': '年中好物清单',
        '职场': '打工人必看',
        '赚钱': '搞钱必读',
    }
    for kw, text in cover_text_map.items():
        if kw in topic_word:
            return text  # 返回配文内容
    return None  # 返回 None 表示由 Image2 自动加上话题词
```

---

## 图文素材表格结构（邮件HTML中渲染）

```python
image_prompts = [
    ("封面", generate_image_prompt(topic_word, platform, 'cover')),
    ("配图1", generate_image_prompt(topic_word, platform, 'body')),
    ("配图2", generate_image_prompt(topic_word, platform, 'ending')),
]
# image_count = len(image_prompts)
```

HTML中渲染为表格：
```html
<h3>🖼️ 图文素材（ChatGPT Image2 生图提示词）</h3>
<table>
  <tr>
    <td style="width:80px;font-weight:bold;">封面</td>
    <td><code>提示词内容...</code></td>
  </tr>
  ...
</table>
```

---

## 邮件 HTML 模板结构

```python
def build_html_email(platform, title, cover_text, body, image_count, image_prompts):
    color = {
        '公众号': '#FF6B35',
        '头条号': '#4A90D9',
        '小红书': '#FF4D6D',
    }.get(platform, '#FF6B35')

    # 渐变色头部 + 标题 + 标签
    # 正文区域（section 卡片）
    # 图文素材表格（image_prompts 时）
    # 底部品牌 footer
```

---

## 邮件发送失败的处理

```python
def send_email(subject, html_content, platform):
    _mail = get_mail_config()  # 从 config_loader 读取
    SMTP_SERVER = _mail.get('smtp_server', 'smtp.qq.com')
    # ... 构造 MIMEMultipart ...
    try:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, context=context) as server:
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.sendmail(SENDER_EMAIL, SENDER_EMAIL, msg.as_string())
        return True
    except Exception as e:
        print(f"  ❌ {platform} 邮件发送失败: {e}")
        return False
```

> ⚠️ 若 SMTP 持续失败（腾讯云 IP 被 QQ 邮箱拒绝），内容通过 Lark `deliver=origin` 直接输出，不依赖邮件发送。

---

## 品牌配置

```python
BRANDS = {
    '公众号': '围炉家常话',
    '头条号': '围炉家常话',
    '小红书': '权权的HERMES',
    '抖音': '权权管家',
}
```

---

## 定时任务配置

```python
# cronjob create
{
    "name": "全平台内容生成（选题+爆款）",
    "job_id": "7226bc84df96",
    "schedule": "0 17 * * *",
    "deliver": "origin",
    "prompt": "运行 unified-content-daily.py ..."
}
```

旧任务状态：
- 头条号文章 `406529dd5f2e` → ⏸️ 已暂停
- 抖音热搜选题 `42fe9944998e` → ⏸️ 已暂停
- 小红书旅游攻略 `efc670929cf1` → ▶️ 保留（21:30）