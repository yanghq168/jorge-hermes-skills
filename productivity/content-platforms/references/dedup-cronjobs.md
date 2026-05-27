# 排查重复内容推送任务

## 问题现象

用户收到**重复的内容推送**（如两封小红书邮件），或收到**旧品牌名**的内容（如"权权养的虾"而非"权权的HERMES"）。

## 根因分析

内容推送任务可能存在于多个地方：

1. **Hermes cronjob** (`~/.hermes/cron/jobs.json`) — 新系统
2. **系统 crontab** (`crontab -l`) — 旧系统遗留
3. **远程服务器 crontab** (如果脚本部署在远程服务器)
4. **不同文件名的同一功能脚本** — 如 `xiaohongshu-travel-daily.py` 和 `xhs-travel-daily.py`

当迁移或重建任务时，旧任务可能未被清理，导致重复运行。特别注意：**不同文件名的脚本可能实现相同功能**，需要检查脚本内容而不仅是文件名。

## 排查步骤

### 1. 检查 Hermes cronjob

```bash
# 列出所有 Hermes 定时任务
cronjob(action='list')

# 或查看 jobs.json
cat ~/.hermes/cron/jobs.json | python3 -m json.tool
```

关注字段：
- `name` — 任务名称
- `schedule` — 定时表达式
- `script` — 执行的脚本路径
- `last_run_at` — 上次运行时间

### 2. 检查系统 crontab

```bash
crontab -l | grep -E "xhs|xiaohongshu|toutiao|wechat|content"
```

### 3. 检查脚本目录中的重复功能脚本

```bash
# 列出所有内容相关脚本
ls -la ~/.hermes/cron/scripts/ | grep -E "xhs|xiaohongshu|toutiao|wechat"

# 检查是否有不同文件名但相同功能的脚本
# 例如：xiaohongshu-travel-daily.py 和 xhs-travel-daily.py
head -10 ~/.hermes/cron/scripts/xiaohongshu-travel-daily.py | grep "发件人\|品牌"
head -10 ~/.hermes/cron/scripts/xhs-travel-daily.py | grep "发件人\|品牌"
```

### 4. 检查远程服务器（如适用）

```bash
ssh -i ~/.ssh/key user@server "crontab -l | grep -E 'xhs|xiaohongshu|toutiao|wechat'"
```

### 5. 检查脚本内容中的品牌名

```bash
# 搜索旧品牌名
grep -r "权权养的虾" ~/.hermes/cron/scripts/

# 搜索发件人配置
grep -r "From.*权权" ~/.hermes/cron/scripts/
```

## 修复步骤

### 场景 A：Hermes cronjob 和系统 crontab 重复

**保留 Hermes cronjob，删除系统 crontab：**

```bash
# 查看当前 crontab
crontab -l > /tmp/crontab_backup.txt

# 删除旧的小红书任务
crontab -l | grep -v "xiaohongshu-travel-daily.py" | crontab -

# 验证
crontab -l | grep xiaohongshu  # 应该无输出
```

### 场景 B：不同文件名的重复脚本（如 `xiaohongshu-travel-daily.py` + `xhs-travel-daily.py`）

**检查两个脚本的功能和品牌名，保留新版，删除旧版：**

```bash
# 检查两个脚本的发件人（品牌名）
grep -n "发件人\|From" ~/.hermes/cron/scripts/xiaohongshu-travel-daily.py
grep -n "发件人\|From" ~/.hermes/cron/scripts/xhs-travel-daily.py

# 检查 crontab 引用的是哪个
 crontab -l | grep -E "xiaohongshu|xhs"

# 检查 jobs.json 引用的是哪个
grep -A5 -B5 "xhs\|xiaohongshu" ~/.hermes/cron/jobs.json

# 删除旧版脚本（确认新版运行正常后）
rm ~/.hermes/cron/scripts/xiaohongshu-travel-daily.py

# 如果 crontab 引用了旧脚本，更新为新版
crontab -l | sed 's/xiaohongshu-travel-daily/xhs-travel-daily/g' | crontab -
```

### 场景 C：旧品牌名脚本仍在运行

**更新脚本品牌名：**

```bash
# 找到旧脚本
find ~/.hermes/cron/scripts/ -name "*xiaohongshu*" -o -name "*xhs*"

# 检查发件人
head -20 ~/.hermes/cron/scripts/xiaohongshu-travel-daily.py | grep -i "发件人\|from"

# 替换品牌名（谨慎操作，先备份）
cp ~/.hermes/cron/scripts/xiaohongshu-travel-daily.py \
   ~/.hermes/cron/scripts/xiaohongshu-travel-daily.py.bak

sed -i 's/权权养的虾/权权的HERMES/g' \
    ~/.hermes/cron/scripts/xiaohongshu-travel-daily.py
```

### 场景 D：推送时间需要调整

```bash
# 修改 Hermes cronjob 时间
cronjob(action='update', job_id='<job_id>', schedule='30 21 * * *')

# 或修改系统 crontab
# 编辑 crontab，将 0 23 * * * 改为 0 21 * * *
```

## 验证清单

修复后，确认以下检查项：

- [ ] `crontab -l` 中无旧任务
- [ ] `jobs.json` 中只有预期的任务
- [ ] 脚本中的发件人是新品牌名「权权的HERMES」
- [ ] 各平台推送时间错开（至少间隔30分钟）
- [ ] 手动运行脚本测试：`python3 ~/.hermes/cron/scripts/xhs-travel-daily.py`

## 预防建议

1. **迁移时清理旧任务** — 从 OpenClaw 或其他系统迁移时，先列出所有旧任务再创建新任务
2. **统一使用 Hermes cronjob** — 避免混用系统 crontab 和 Hermes cronjob
3. **品牌名集中配置** — 将发件人名称放在配置文件中，而非硬编码在脚本里
