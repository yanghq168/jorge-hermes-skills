# 小红书旅游攻略输出样例

## 邮件标题
`📍 小红书旅游攻略 | {景点名}`

---

## 新版UI结构（共8个模块，严格按顺序）

### ① 导航栏
```html
<div class="nav-bar">
    <span class="back">←</span>
    <span class="more">⋮⋮⋮</span>
</div>
```

### ② Hero Banner（玫红渐变 + 底部圆角）
```html
<div class="hero">
    <div class="tag">🏮 小红书旅游攻略</div>
    <h1>每日小红书旅游攻略</h1>
    <div class="subtitle">{date} · 今日推荐：{spot_name}</div>
</div>
```
```css
.hero {
    background: linear-gradient(135deg, #FF4D6D 0%, #FF6B6B 50%, #ee5a5a 100%);
    border-radius: 0 0 20px 20px;
    padding: 30px 24px 28px;
    color: white;
}
```

### ③ 景点信息卡片
```html
<div class="spot-card">
    <div class="card-title"><span>📍</span> 景点信息</div>
    <div class="info-grid">
        <div class="info-item"><span class="key">景点：</span><span class="val">{spot_name}</span></div>
        <div class="info-item"><span class="key">省份：</span><span class="val">{province}</span></div>
        <div class="info-item"><span class="key">类型：</span><span class="val">{travel_type}</span></div>
        <div class="info-item"><span class="key">最佳季节：</span><span class="val">{best_season}</span></div>
    </div>
    <div class="trip-line">📅 建议行程：{days} · {vibe}</div>
    <div class="desc">"{spot_desc}"</div>
    <div class="tags">{spot_tags_html}</div>
</div>
```

### ④ 小红书文案区
```html
<div class="xhs-section">
    <div class="section-head"><span>📝</span> 小红书文案</div>
    <div class="xhs-title">{title}</div>            <!-- 玫红色 #FF4D6D -->
    <div class="xhs-intro">刚从{spot_name}回来，整个人都被治愈了😭</div>
    <div class="xhs-route">📍 {location} · {days}攻略</div>
    
    <!-- 行程时间轴（无彩色卡片，纯文字列表） -->
    <div class="day-block">
        <div class="day-title"><span class="day-num">Day 1</span>｜初遇丹巴</div>
        <ul class="day-items">
            <li class="day-item"><span class="time-label">上午</span> 内容...</li>
            <li class="day-item"><span class="time-label">下午</span> 内容...</li>
            <li class="day-item"><span class="time-label">晚上</span> 内容...</li>
        </ul>
    </div>
    
    <!-- Tips -->
    <div class="tips-block">
        <div class="tips-title">💡 Tips:</div>
        <div class="tip-item">提前订住宿...</div>
        <div class="tip-item">记得砍价...</div>
    </div>
    
    <!-- 金句 -->
    <div class="golden-line">"人生建议：去{spot_name}，就现在。"</div>
</div>
```

### ⑤ 话题标签（链接蓝色）
```html
<div class="hashtags-section">
    <div class="hashtags">{hashtags_html}</div>
</div>
```
```css
.hashtag { color: #576B95; font-size: 12px; font-weight: 500; }  /* 链接蓝，非玫红胶囊 */
```

### ⑥ DALL·E 海报提示词（左侧玫红竖线）
```html
<div class="prompt-section">
    <div class="section-head"><span>🎨</span> DALL·E 3 海报提示词</div>
    <div class="prompt-desc">复制以下内容到 ChatGPT image2 / DALL·E 3 生成主视角海报：</div>
    <div class="prompt-box">
        <div class="prompt-text">{cover_prompt}</div>
    </div>
</div>
```
```css
.prompt-box {
    background: #f5f5f5;
    border-radius: 10px;
    padding: 14px 16px;
    border-left: 3px solid #FF4D6D;   /* 左侧玫红竖线 */
}
```

### ⑦ 必吃美食
```css
.food-tag { background: #FFE4E8; color: #FF4D6D; padding: 5px 12px; border-radius: 12px; font-size: 12px; font-weight: 600; }
```

### ⑧ 底部账号
```html
<div class="footer">
    <div class="account">🦐 权权养的虾（小红书）每日推送</div>
    <div class="time">每天晚上11点，为你解锁一个国内宝藏目的地</div>
</div>
```

---

## 配色速查表

| 用途 | 颜色 | CSS变量 |
|------|------|--------|
| 主色/强调 | `#FF4D6D` | 标题、金句、分隔线 |
| Hero渐变 | `#FF4D6D → #FF6B6B → #ee5a5a` | Banner背景 |
| 标签底色 | `#FFE4E8` | 景点/美食标签背景 |
| 话题文字 | `#576B95` | #标签文字（链接蓝） |
| 代码背景 | `#f5f5f5` | prompt-box背景 |
| 金句框线 | `dashed #f0f0f0` | 上下虚线边框 |
| 正文黑 | `#1a1a1a` | 模块标题 |
| 正文灰 | `#555` | 正文内容 |
| 辅助灰 | `#999` | 时间标签 |
| 极浅灰 | `#bbb` | 底部极小字 |

---

## Python模板变量对照表

```python
html_content = XHS_TEMPLATE.format(
    spot_name=dest['name'],
    location=dest['location'],        # "云南 · 大理"
    date=date_str,                  # "2026年05月27日"
    days=dest['days'],              # "3天2夜"
    season=dest['season'],          # "四季皆宜，避开节假日"
    vibe=dest['vibe'],              # "慢生活、文艺、治愈"
    title=random.choice(dest['title_templates']),
    province=dest['location'].split('·')[0].strip(),
    travel_type=dest.get('travel_type', '宝藏目的地'),
    best_season=dest['season'],
    spot_desc=dest.get('spot_desc', '这是一座让人流连忘返的目的地。'),
    spot_tags_html=spot_tags_html,  # 浅粉底玫红字胶囊
    hashtags_html=hashtags_html,    # 链接蓝 #标签
    itinerary_html=itinerary_html,  # day-block 时间轴
    food_tags=food_tags,            # 浅粉底玫红字胶囊
    tips_html=tips_html,            # ✅ 对勾 + 正文
    golden_line=dest.get('golden_line', f"人生建议：去{dest['name']}，就现在。"),
    cover_prompt=dest['cover_prompt'],
)
```

---

## 话题标签生成规则（共9个）

```python
hashtags = [
    f"#{dest['name']}",                              # 景点名
    f"#{dest['location'].replace('·', '').replace(' ', '')}",  # 省份+城市
    f"#{dest['vibe'].replace('、', '#')}",           # 风格（拆分）
    f"#{dest['days']}游",                           # 天数
    "#旅行打卡", "#旅游攻略", "#小红书旅行", "#周末去哪玩", "#旅行推荐",  # 引流
]
```

---

## ⚠️ 常见踩坑

1. **f-string反斜杠**：Python 3.12禁止在f-string内使用反斜杠
   ```python
   # ❌ 报错
   text = f"{chr(10).join([...])}"
   # ✅ 正确
   lines = '\n'.join([...])
   text = f"{lines}"
   ```

2. **话题标签遗漏**：小红书内容必须有 `#话题`，检查 `hashtags_html` 是否传入

3. **新模块上线后模板变量不完整**：每次新增HTML模板占位符后，必须同步更新 `XHS_TEMPLATE.format()` 调用处的参数，否则邮件发送成功但模板渲染缺失字段