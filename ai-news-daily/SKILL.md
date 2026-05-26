---
name: ai-news-daily
description: AI 新闻日报 - 自动抓取全球 AI 行业最新动态，每日推送精选新闻。支持英文标题/内容自动翻译、中文摘要、失败重试、智能去重。使用 Hermes cronjob 定时任务每天早上 9:00 自动推送。
---

# AI 新闻日报

自动抓取全球 AI 行业最新动态，每日推送精选新闻。

## ✨ 功能特性

1. **自动推送** - 使用 Hermes `cronjob` 定时任务，每天早上 9:00 推送到对话框
2. **AI 生成摘要** - 中文摘要，内容详细
3. **英文自动翻译** - 英文标题和内容自动翻译成中文
4. **外部配置** - 所有参数移到 `config/config.yaml`，方便自定义
5. **失败重试** - 自动重试失败的请求，指数退避机制
6. **智能去重** - URL 归一化 + 标题相似度检测，避免重复新闻

## 🚀 快速开始

### 安装依赖

```bash
pip install feedparser beautifulsoup4 requests pyyaml trafilatura
```

### 配置定时任务

使用 Hermes `cronjob` 创建定时任务：

```bash
hermes cron create \
  --name "ai-news-daily" \
  --schedule "0 9 * * *" \
  --script "~/.hermes/skills/ai-news-daily/run.sh"
```

或在对话中使用 `cronjob` 工具创建。

### 手动运行

```bash
# 立即抓取并推送
~/.hermes/skills/ai-news-daily/run.sh
```

## ⚙️ 配置

编辑 `config/config.yaml`：

```yaml
# 抓取配置
fetch:
  max_workers: 4          # 并发线程数
  request_timeout: 15     # 请求超时（秒）
  max_retries: 3          # 失败重试次数
  retry_delay: 2          # 重试间隔（秒）

# 摘要配置  
summary:
  target_min: 400         # 摘要最小中文字数
  target_max: 500         # 摘要最大中文字数

# 输出配置
output:
  top_n: 10               # 每天推送几条新闻

# 推送配置
push:
  enabled: true
  output_file: data/openclaw_message.txt
```

## 📅 定时任务管理

使用 Hermes 内置 `cronjob` 工具管理：

```bash
# 查看所有定时任务
hermes cron list

# 手动立即运行一次
hermes cron run <job-id>

# 暂停任务
hermes cron pause <job-id>

# 删除任务
hermes cron remove <job-id>
```

## 📁 文件结构

```
ai-news-daily/
├── SKILL.md              # 本文件
├── config/
│   └── config.yaml       # 配置文件
├── src/
│   ├── daily_fetch.py    # 主程序（抓取新闻 + 生成摘要）
│   ├── translator.py     # 翻译模块（支持多语言）
│   └── generate_summary.py  # 摘要生成
├── data/
│   ├── news.db           # SQLite 数据库（自动创建）
│   ├── fetch.log         # 运行日志
│   └── openclaw_message.txt  # 生成的消息
├── requirements.txt      # Python 依赖列表
└── run.sh                # 运行脚本
```

## 📰 新闻源

| 权重 | 来源 |
|------|------|
| 1.3 | 量子位、机器之心、36 氪、新智元、智东西、InfoQ |
| 1.2 | TechCrunch AI、The Verge AI、MIT Tech Review |
| 1.1 | 雷锋网、钛媒体、极客公园 |
| 1.0 | 虎嗅 |

## 📤 输出格式

```
📰 AI 每日新闻 - 2026 年 03 月 03 日

共 10 条精选
──────────────────────────────

**1. [量子位] 英伟达放弃 GPU 上 LPU：新推理芯片被曝 Groq 即买即用**

英伟达放弃 GPU 上 LPU：新推理芯片被曝 Groq 即买即用，OpenAI 第一个吃螃蟹...
🔗 [阅读原文](url)

...

🤖 AI News Aggregator | 每日更新
```

## 🛠️ 故障排除

### 定时任务未创建
使用 `cronjob` 工具手动创建定时任务。

### 依赖安装失败
```bash
pip install --break-system-packages feedparser beautifulsoup4 requests pyyaml
```

### 新闻抓取失败
```bash
# 查看日志
tail -f data/fetch.log
```

### 翻译失败
翻译使用 MyMemory 免费 API，如果失败会保留原文。可配置其他翻译服务：
```bash
export TRANSLATE_API_KEY="your_api_key"  # DeepL/百度翻译
```

## 🔧 工作原理

1. **抓取阶段** (`daily_fetch.py`)
   - 并发抓取多个 RSS 源
   - 保存完整原始内容到数据库
   - 智能去重，避免重复

2. **翻译阶段** (`translator.py`)
   - 自动检测英文标题和内容
   - 使用 MyMemory API 翻译成中文
   - 支持 DeepL/百度翻译（需配置 API Key）

3. **摘要阶段** (`generate_summary.py`)
   - 从数据库读取原始内容
   - 生成中文摘要

4. **推送阶段** (Hermes cronjob)
   - 每天 9:00 自动触发
   - 生成摘要并推送到对话框

## 📝 更新日志

### v1.0.0 (Hermes 适配版)
- ✅ 适配 Hermes cronjob 定时任务系统
- ✅ 移除 OpenClaw 依赖
- ✅ 更新文档和配置说明

## 📄 License

MIT
