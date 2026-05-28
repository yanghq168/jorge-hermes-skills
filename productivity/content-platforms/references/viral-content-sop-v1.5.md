# 抖音热搜→爆款文章 SOP v1.5

**核心原则：先搜索真实爆款，再生成内容。禁止不搜索就直接套模板。**

## 工作流

```
热搜词 → search_real_viral_content() 搜索 → analyze_viral_content() 分析 → _detect_real_topic() 判断类型 → 基于真实主题生成内容
```

## 搜索实现（unified-content-daily.py）

### search_real_viral_content(word)

用两个搜索引擎抓取真实爆款标题：

1. **搜狗微信搜索** `https://wx.sogou.com/weixin?type=2&query={word}`
   - 返回公众号/小红书文章标题，是最相关的真实内容
   - 正则提取：`<h3[^>]*>(.*?)</h3>` 取标题，`<p[^>]*class="[^"]*s-p[^"]*"[^>]*>(.*?)</p>` 取摘要

2. **百度搜索** `https://www.baidu.com/s?wd={word}&rn=10`
   - 用手机UA (`Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)`) 避免被拦截
   - 正则提取：`<h3[^>]*class="[^"]*line[^"]*"[^>]*>(.*?)</h3>`

### analyze_viral_content(word, search_results)

分析搜索结果，返回：
```python
{
    'word': word,
    'category': 'work'/'life'/'science',
    'titles': [真实爆款标题列表],
    'hot_words': [热词列表],
    'angle': 'story'/'advice'/'review'/'emotion',
    'key_emotion': '触动、思考、认同',
}
```

### _detect_real_topic()

基于搜索到的 `titles` 判断真实主题类型：

| 类型 | 判定关键词 | 生成内容方向 |
|------|-----------|------------|
| `kpop_entertainment` | T-ara、女团、韩团、偶像、爱豆、reaction | 韩娱评论/安利入坑 |
| `beauty` | 护肤、美妆、穿搭、显白、测评、种草 | 变美经验分享 |
| `family` | 孩子、父母、家长、教育、亲子、家庭 | 家庭教育/亲情故事 |
| `work` | 工作、职场、赚钱、工资、老板 | 职场干货/经历 |
| `love` | 感情、恋爱、婚姻、分手 | 情感故事 |
| `life`（默认） | 其他 | 通用生活情感 |

### 生成函数适配

每个平台生成函数（`generate_gongzhonghao`/`generate_toutiao`/`generate_xiaohongshu`/`generate_douyin_script`）都必须：
1. 调用 `_detect_real_topic()` 获取真实主题
2. 在模板分支判断中优先判断 `real_topic`（如 `if real_topic == 'kpop_entertainment':`）
3. 再 fallback 到旧的 `story_style` 判断逻辑

## 典型案例

**热搜词**：`竖版粉彩盛典对我眼睛太友好了`

**错误做法（v4.0之前）**：
- 不搜索，直接套"家庭情感"模板
- 生成内容："前两天我妈给我打了一个电话..."

**正确做法（v1.5.0）**：
1. 搜索发现真实爆款是 T-ara reaction 视频
2. 判断类型为 `kpop_entertainment`
3. 公众号钩子：`"前几天看到一个视频，整个人愣住了——T-ara的reaction合集，我看了三遍停不下来"`
4. 小红书标题：`"T-ara的reaction合集✨我也入坑了！"`
5. 抖音开场：`"你们有没有刷到T-ara的reaction合集？我看了三遍停不下来"`

## 敏感词规范

| 原词 | 替换为 |
|------|--------|
| 拉黑 | 屏蔽 |
| 逼 | 让 |
| 滚 | 走 |

## 搜索失败处理

如果两个搜索引擎都抓不到内容（返回空），`analyze_viral_content` 返回 `None`，生成函数 fallback 到旧模板。此时日志会显示"真实爆款标题: ..."为空。