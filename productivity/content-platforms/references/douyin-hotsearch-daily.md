# 抖音热搜选题日报 douyin-hotsearch-daily.py

## 脚本路径
`~/.hermes/cron/scripts/douyin-hotsearch-daily.py`

## 定时任务
每天 17:00 运行

## 核心流程

```python
1. curl 抓取抖音热搜 API → /tmp/douyin_hot.json
2. Python 解析 + 分类（关键词匹配 + label 兜底）
3. 每类取 TOP10，格式化热度（万/亿）
4. 生成 HTML 邮件（渐变色头部、卡片布局、标签）
5. QQ SMTP 发送邮件
```

## API 响应结构

```json
{
  "active_time": "2026-05-28 17:27:11",
  "status_code": 0,
  "word_list": [
    {
      "word": "神舟二十一号乘组即将回家",
      "hot_value": 12047115,
      "label": 3
    }
  ]
}
```

## Label 字段含义（观察值）

| Label | 含义 | 兜底分类 |
|-------|------|---------|
| 0 | 社会新闻/综合 | 轻科普 |
| 1 | 娱乐/综艺 | 职场/搞钱 |
| 3 | 娱乐/内容 | 生活情感 |
| 5 | 文化/艺术 | 轻科普 |
| 8 | 影视/电影 | 职场/搞钱 |
| 9 | 生活/搞笑 | 生活情感 |
| 16 | 新闻 | 轻科普 |

## 分类关键词表

### 生活情感类
```python
life_emotion_keywords = [
    '亲情', '爱情', '友情', '成长', '治愈', '情感', '温暖', '感动', '陪伴',
    '家人', '父母', '爸爸', '妈妈', '阿嬷', '情书', '纯爱', '浪漫', '幸福',
    '生活', '日常', '烟火气', '人间', '温柔', '美好', '回忆', '童年',
    '猫咪', '宠物', '动物', '幼崽', '孩子', '小朋友', '大朋友', '亲子',
    '穿搭', '美食', '旅行', '大理', '梦核', '夏天', '空调', '家居',
    '高考', '加油', '学子', '毕业', '青春', '校园', '考试',
    '攀岩', '运动', '健身', '618', '清单', '攻略',
    '聊天记录', '十二生肖', '灵机一动', '判官'
]
```

### 职场/搞钱类
```python
work_money_keywords = [
    '工作', '职场', '创业', '副业', '理财', '赚钱', '搞钱', '收入', '薪资',
    '老板', '同事', '加班', '辞职', '跳槽', '面试', '简历', '招聘',
    '项目', '合作', '合同', '客户', '业绩', 'KPI', '晋升', '升职',
    '出版社', '编辑', '改稿', '写作', '文案', '内容', '运营',
    '电影', '定档', '票房', '剧组', '拍摄', '试戏', '演员', '明星',
    '综艺', '节目组', '乘风', '白玉兰', '获奖', '预测',
    '年会', '咸鱼', '飞升'
]
```

### 轻科普/冷知识类
```python
knowledge_keywords = [
    '科普', '知识', '科学', '健康', '医学', '生物', '物理', '化学',
    '历史', '文化', '非遗', '博物馆', '文物', '考古', '传统',
    '攻略', '教程', '技巧', '方法', '步骤', '指南', '测评', '对比',
    '世界最大', '规模', '技术', '工程', '航天', '神舟', '换流站',
    '英歌舞', '粉彩', '御窑', '瓷器', '龙舟', '猎德', '端午',
    '三角洲', '游戏', '版本', '更新', '王者荣耀', '和平精英',
    '金铲铲', '海克斯', '大乱斗', '羁绊', '光遇', '狼尾',
    '巴萨', '足球', '安东尼', '戈登', '水晶宫', '欧协联', '冠军'
]
```

## 热度格式化

```python
def format_hot(value):
    if value >= 100000000:
        return f"{value/100000000:.2f}亿"
    elif value >= 10000:
        return f"{value/10000:.1f}万"
    else:
        return str(value)
```

## 敏感词替换

```python
def sanitize_word(word):
    replacements = {
        '拉黑': '屏蔽',
        '逼': '让',
        '滚': '走'
    }
    for old, new in replacements.items():
        word = word.replace(old, new)
    return word
```

## 话题标签生成

按内容类型匹配3个标签：

```python
def generate_tags(word):
    w = word.lower()
    tags = []
    # 生活情感
    if any(x in w for x in ['高考', '学子', '加油', '考试', '毕业']):
        tags.extend(['#高考加油', '#毕业季', '#青春记忆'])
    if any(x in w for x in ['爸爸', '妈妈', '阿嬷', '家人', '亲情']):
        tags.extend(['#亲情', '#家人', '#温暖瞬间'])
    if any(x in w for x in ['情书', '纯爱', '爱情', '浪漫']):
        tags.extend(['#纯爱', '#爱情故事', '#治愈系'])
    if any(x in w for x in ['成长', '攀岩', '运动']):
        tags.extend(['#成长记录', '#挑战自我', '#运动生活'])
    if any(x in w for x in ['猫咪', '宠物', '动物', '幼崽']):
        tags.extend(['#萌宠', '#猫咪日常', '#治愈'])
    if any(x in w for x in ['美食', '烟火气', '生活']):
        tags.extend(['#人间烟火', '#美食日常', '#生活美学'])
    if any(x in w for x in ['穿搭', '时尚']):
        tags.extend(['#穿搭', '#时尚', '#OOTD'])
    if any(x in w for x in ['大理', '旅行', '梦核']):
        tags.extend(['#旅行', '#大理', '#梦核'])
    # 职场/搞钱
    if any(x in w for x in ['出版社', '编辑', '改稿', '写作']):
        tags.extend(['#出版行业', '#编辑日常', '#写作'])
    if any(x in w for x in ['电影', '定档', '预告', '观后感']):
        tags.extend(['#电影', '#影评', '#新片推荐'])
    if any(x in w for x in ['综艺', '节目组', '乘风']):
        tags.extend(['#综艺', '#娱乐圈', '#幕后'])
    if any(x in w for x in ['白玉兰', '获奖', '演员', '试戏']):
        tags.extend(['#白玉兰奖', '#演技', '#影视圈'])
    if any(x in w for x in ['非遗', '英歌舞', '文化']):
        tags.extend(['#非遗文化', '#英歌舞', '#传统文化'])
    # 轻科普
    if any(x in w for x in ['神舟', '航天', '科技']):
        tags.extend(['#航天', '#中国科技', '#神舟'])
    if any(x in w for x in ['博物馆', '御窑', '瓷器', '粉彩', '文物']):
        tags.extend(['#博物馆', '#文物', '#传统文化'])
    if any(x in w for x in ['换流站', '工程', '世界最大']):
        tags.extend(['#超级工程', '#科技', '#中国制造'])
    if any(x in w for x in ['游戏', '和平精英', '王者荣耀', '三角洲']):
        tags.extend(['#游戏', '#手游', '#电竞'])
    if any(x in w for x in ['巴萨', '足球', '冠军']):
        tags.extend(['#足球', '#巴萨', '#体育'])
    if any(x in w for x in ['造谣', '谣言']):
        tags.extend(['#辟谣', '#真相', '#网络安全'])
    if not tags:
        tags = ['#热门话题', '#今日关注']
    return ' '.join(tags[:3])
```

## 邮件发送代码

```python
import smtplib, re
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# 从 .env 读取 QQ 邮箱配置
with open('/home/ubuntu/.hermes/.env', 'r') as f:
    content = f.read()
auth_match = re.search(r'QQ_EMAIL_AUTH_CODE=(.+)', content)
user_match = re.search(r'QQ_EMAIL_USER=(.+)', content)
auth_code = auth_match.group(1).strip()
user = user_match.group(1).strip()

msg = MIMEMultipart('alternative')
msg['Subject'] = '🔥 抖音今日热搜选题日报 - YYYY年MM月DD日'
msg['From'] = f'=?utf-8?b?5pe26pe25ZCb5LqRSEVSTUVT77yI6YKu5aKZ77yJ?=<{user}>'
msg['To'] = '569545015@qq.com'

html_part = MIMEText(html_body, 'html', 'utf-8')
msg.attach(html_part)

server = smtplib.SMTP_SSL('smtp.qq.com', 465, timeout=30)
server.login(user, auth_code)
server.sendmail(user, ['569545015@qq.com'], msg.as_string())
server.quit()
```

## HTML 模板关键样式

```css
.header {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 50%, #f093fb 100%);
    border-radius: 16px;
    padding: 40px 30px;
    text-align: center;
    color: white;
    box-shadow: 0 10px 40px rgba(102, 126, 234, 0.3);
}
.rank-1 { background: linear-gradient(135deg, #FFD700, #FFA500); color: white; }
.rank-2 { background: linear-gradient(135deg, #C0C0C0, #A0A0A0); color: white; }
.rank-3 { background: linear-gradient(135deg, #CD7F32, #B87333); color: white; }
.hot-value { font-weight: 600; color: #ff6b6b; }
.rec-card {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    border-radius: 16px;
    padding: 30px;
    color: white;
}
```

## 今日趋势总结生成要点

基于三类热搜 TOP10 数据，总结 3-5 个趋势要点：

1. 找出每类最高热度话题，说明其代表的趋势
2. 关注跨类别的关联（如高考话题同时出现在生活和知识类）
3. 指出内容创作的时间窗口（如高考季、暑期游戏更新）
4. 标注传统文化/国风内容的活跃度
5. 标注游戏/电竞内容的持续热度

## 推荐选题建议生成规则

基于热搜数据，生成 3-5 个内容创作方向：

1. **结合最高热度话题** — 如航天科普、高考情感
2. **跨平台适配** — 同一话题可制作短视频、图文、直播等不同形式
3. **时效性** — 标注最佳发布时间窗口
4. **差异化** — 避免与已有大量内容的话题直接竞争
5. **标签建议** — 每个方向附带 3 个推荐话题标签
