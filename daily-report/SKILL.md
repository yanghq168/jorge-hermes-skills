---
name: daily-report
description: 每日工作日报 - 自动生成并推送工作日报，包含权权管家工作模块、Agent优化追踪、全体Agent工作表格。使用 Hermes cronjob 定时任务系统。
---

# 每日工作日报

自动生成并推送工作日报。

## ✨ 功能特性

1. **自动推送** - 使用 Hermes `cronjob` 定时任务，每天早上 9:00 推送到对话框
2. **权权管家工作模块** - 自动提取工作记录
3. **Agent优化追踪** - 追踪Agent变更和优化
4. **全体Agent工作表格** - 展示所有Agent工作状态

## 🚀 快速开始

### 配置定时任务

使用 Hermes `cronjob` 创建定时任务：

```bash
hermes cron create \
  --name "daily-report" \
  --schedule "0 9 * * *" \
  --script "~/.hermes/skills/daily-report/run.sh"
```

或在对话中使用 `cronjob` 工具创建。

### 手动运行

```bash
~/.hermes/skills/daily-report/run.sh
```

## ⚙️ 配置

编辑 `config.json`：

```json
{
  "email": {
    "enabled": false,
    "smtp_server": "smtp.gmail.com",
    "smtp_port": 587,
    "username": "",
    "password": "",
    "to": []
  },
  "feishu": {
    "enabled": true,
    "webhook": ""
  }
}
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
daily-report/
├── SKILL.md              # 本文件
├── config.json           # 配置文件
├── daily_report.py       # 主程序
├── email_templates.py    # 邮件模板
├── push_feishu.py        # 飞书推送
└── run.sh                # 运行脚本
```

## 📝 更新日志

### v1.0.0 (Hermes 适配版)
- ✅ 适配 Hermes cronjob 定时任务系统
- ✅ 移除 OpenClaw 依赖
- ✅ 更新文档和配置说明

## 📄 License

MIT
