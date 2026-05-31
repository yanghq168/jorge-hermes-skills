# Cron 诊断手册

## 区分两类"失败"

Hermes cron 任务的 `last_status: error` 有两种完全不同的含义，排查方向完全不同。

### A）no_agent 脚本：误报 error（Exit 0 = 成功）

`no_agent: true` 的脚本退出码 0，但 Hermes 仍显示 `last_status: error`。这是平台的报告 bug，不是脚本问题。

**特征**：
- `last_status: error` 但 `last_run_at` 时间戳正常推进
- `last_delivery_error: null`
- 脚本自己写的 log 文件显示 ✅ 成功

**诊断命令**：
```bash
# 检查脚本自己的 log（最可信）
tail ~/.hermes/cron/logs/xhs-escape-weekend.log
tail ~/.hermes/cron/logs/wechat-article-daily.log
tail ~/.hermes/cron/logs/skill-backup.log

# 手动重跑验证
python3 ~/.hermes/cron/scripts/xhs-escape-weekend.py; echo "Exit: $?"
bash ~/.hermes/cron/scripts/skill-backup.sh; echo "Exit: $?"

# 检查 cron 系统自己的记录
cronjob(action='list')  # 看 last_run_at 是否推进
```

**已知误报任务**（Exit 0，实际成功）：
- `xhs-escape-weekend.py` — 周末出逃计划
- `wechat-article-daily.py` — 公众号情感长文
- `skill-backup.sh` — Skills 备份到 GitHub
- `agency-backup.sh` — Agency 备份到 GitHub

### B）LLM-driven 任务：真正失败

`no_agent: false`（默认）的任务，error 状态通常是真的有问题。

**诊断方向**：
```bash
# 检查 cron agent 的执行日志
tail -50 ~/.hermes/logs/agent.log | grep <job_name>
grep "<job_id>" ~/.hermes/logs/errors.log
```

---

## 快速定位任务状态

```bash
# 列出所有任务及关键字段
cronjob(action='list')

# 已知误报状态的任务，手动验证
python3 ~/.hermes/cron/scripts/xhs-escape-weekend.py 2>&1 | tail -5
python3 ~/.hermes/cron/scripts/wechat-article-daily.py 2>&1 | tail -5
```

---

## 更新日志

- **v1.0.0（2026-05-31）**：新建 — 记录 no_agent 脚本误报 error 的诊断方法