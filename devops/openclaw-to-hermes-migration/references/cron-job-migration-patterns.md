# Cron Job Migration Patterns

Session-specific detail from migrating jorge-cron-jobs (github.com/yanghq168/jorge-agency).

## Problem

OpenClaw cron jobs live in a separate repo (`jorge-cron-jobs/`) with:
- A `crontab.txt` file using system crontab format
- Python scripts that call `openclaw infer model run` for LLM content generation
- Hardcoded paths like `/root/.openclaw/workspace/`
- Mixed concerns: content generation, system monitoring, backups

## Migration Approach

### 1. Categorize Scripts

| Type | Scripts | Migration Strategy |
|------|---------|-------------------|
| Content generation (LLM) | xiaohongshu, wechat, douyin | Rewrite as template-based (no LLM) or use `delegate_task` |
| System monitoring | health_check, heartbeat, collect_metrics | Rewrite for Hermes paths |
| Reporting | daily/weekly/monthly_report | Rewrite for Hermes memory paths |
| Backup | site_backup, memory_archive, skill-backup | Rewrite paths |
| External API | bithappy_email, push_feishu | Keep logic, update config loading |

### 2. Path Mapping

| OpenClaw Path | Hermes Path |
|---------------|-------------|
| `/root/.openclaw/workspace/` | `/home/ubuntu/.hermes/` or `~/.hermes/` |
| `/root/.openclaw/workspace/scripts/` | `~/.hermes/cron/scripts/` |
| `/root/.openclaw/workspace/skills/` | `~/.hermes/skills/` |
| `/root/.openclaw/workspace/memory/` | `~/.hermes/memory/` |
| `/var/log/*.log` | `~/.hermes/cron/logs/*.log` |

### 3. Config Loading Pattern

Create a unified `config_loader.py`:

```python
import yaml
from pathlib import Path

CONFIG_PATH = Path("/home/ubuntu/.hermes/cron/config/config.yaml")

def get_config():
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, 'r') as f:
            return yaml.safe_load(f) or {}
    return {}

def get_mail_config():
    return get_config().get('mail', {})
```

### 4. Crontab → Hermes cronjob Conversion

**System crontab format:**
```
0 23 * * * python3 /root/.openclaw/workspace/scripts/xiaohongshu.py >> /var/log/xiaohongshu.log
```

**Hermes cronjob (recommended):**
```bash
hermes cron create \
  --name "xiaohongshu-travel" \
  --schedule "0 23 * * *" \
  --script "~/.hermes/cron/scripts/xiaohongshu-travel-daily.py"
```

**Or use the `cronjob` tool in conversation.**

### 5. LLM Content Generation Decision Tree

Scripts that called `openclaw infer model run` need a new approach:

```
Does the script generate content via LLM?
│
├─ Simple template-based content (fixed formats, random selection)
│   └─ Rewrite as pure Python with templates and random.choice()
│
├─ Complex content requiring LLM creativity
│   └─ Use delegate_task with a subagent prompt
│   └─ Or use execute_code with LLM API calls
│
└─ Content that can be pre-generated
    └─ Generate batch content and store in SQLite/JSON
```

### 6. Email Sending Pattern

All scripts share the same email pattern. Extract to config:

```yaml
mail:
  smtp_server: "smtp.qq.com"
  smtp_port: 465
  smtp_user: "569545015@qq.com"
  smtp_pass: "AUTH_CODE"
  to_email: "569545015@qq.com"
```

Then in each script:
```python
try:
    from config_loader import get_mail_config
    mail = get_mail_config()
    SMTP_PASS = mail.get('smtp_pass', '')
except:
    SMTP_PASS = ""
```

## Directory Layout (Target)

```
~/.hermes/cron/
├── scripts/           # All executable scripts
├── config/
│   └── config.yaml    # Unified config
├── logs/              # All log files
├── crontab.txt        # System crontab backup
└── README.md          # Documentation
```

## Verification

After migration:
```bash
# Check all scripts are executable
ls -la ~/.hermes/cron/scripts/*.py

# Test a script
python3 ~/.hermes/cron/scripts/health_check.py

# Check logs are writable
ls -la ~/.hermes/cron/logs/

# Verify config loads
python3 -c "from config_loader import get_config; print(get_config())"
```
