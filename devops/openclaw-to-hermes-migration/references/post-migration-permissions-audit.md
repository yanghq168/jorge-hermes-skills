# Post-Migration Permissions Audit

After migrating OpenClaw assets to Hermes, critical permissions and credentials from the original environment do NOT transfer automatically. This reference documents the systematic audit process.

## The Problem

OpenClaw workspaces often contain:
- SSH private keys in `~/.ssh/` (e.g., `jorge_server` for remote server access)
- Git credentials (SSH keys or HTTPS tokens)
- Email SMTP authorization codes
- API tokens in environment variables or config files
- Hardcoded remote server addresses in scripts

These are **outside the git repo** and are lost during migration unless explicitly checked.

## Audit Checklist

### 1. Email / SMTP Credentials

**Check locations:**
- Original `~/.openclaw/workspace/scripts/*.py` for hardcoded `SMTP_PASS`
- Original crontab or environment files
- Original `config.yaml` or `.env`

**Hermes target:**
- `~/.hermes/cron/config/config.yaml` → `mail.smtp_pass`
- Or `~/.hermes/.env` → `EMAIL_PASSWORD`

**Verify:**
```bash
python3 -c "
import smtplib
from config_loader import get_mail_config
m = get_mail_config()
with smtplib.SMTP_SSL(m['smtp_server'], m['smtp_port']) as s:
    s.login(m['smtp_user'], m['smtp_pass'])
    print('OK')
"
```

### 2. GitHub / Git Credentials

**Check locations:**
- `~/.ssh/` for existing keys (`id_rsa`, `id_ed25519`, `github_*`)
- `~/.ssh/config` for Host entries
- `git config --global credential.helper`
- Original scripts referencing `github.com` repos

**Hermes target:**
- `~/.ssh/` (same location, but new VM may be empty)
- Or `~/.hermes/.env` → `GITHUB_TOKEN`

**Verify:**
```bash
ssh -T git@github.com
# Or: gh auth status
```

### 3. Remote Server SSH Access

**Check locations:**
- `~/.ssh/` for custom-named keys (e.g., `jorge_server`)
- Original scripts for `ssh -i` commands
- Original `health_check.py`, `push_feishu.py` for host addresses

**Extraction technique** (when key file is missing but scripts reference it):
```bash
# From original repo, grep for SSH patterns
grep -r "ssh -i\|ssh_key\|@.*\.[0-9]" scripts/ --include="*.py"
# Example output: ssh_key = "~/.ssh/jorge_server"; host = "ai-worker@82.156.225.39"
```

**Hermes target:**
- Recreate `~/.ssh/jorge_server` with correct permissions (600)
- Add to `~/.ssh/config`:
  ```
  Host jorge-remote
      HostName 82.156.225.39
      User ai-worker
      IdentityFile ~/.ssh/jorge_server
      StrictHostKeyChecking no
  ```

**Verify:**
```bash
ssh -i ~/.ssh/jorge_server ai-worker@82.156.225.39 'uptime'
```

### 4. API Tokens (Feishu, Bithappy, etc.)

**Check locations:**
- Original `config.yaml` or `.env`
- Original scripts for `os.getenv()` calls
- Webhook URLs in push scripts

**Hermes target:**
- `~/.hermes/cron/config/config.yaml` → per-script sections
- Or `~/.hermes/.env`

## Extraction from Original Repo

When the original workspace is gone but the git repo remains, extract hidden config:

```bash
git clone https://github.com/user/repo /tmp/original
cd /tmp/original

# Find all hardcoded hosts/IPs
grep -rE "[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+|@[a-z0-9.-]+\.[a-z]{2,}" \
  --include="*.py" --include="*.sh" --include="*.yaml" --include="*.md" .

# Find SSH references
grep -r "ssh -i\|ssh_key\|IdentityFile\|StrictHostKeyChecking" \
  --include="*.py" --include="*.sh" --include="*.md" .

# Find email/SMTP references
grep -r "smtp\|SMTP\|email\|EMAIL" \
  --include="*.py" --include="*.sh" --include="*.yaml" --include="*.md" .

# Find GitHub references
grep -r "github.com\|ghp_\|GITHUB" \
  --include="*.py" --include="*.sh" --include="*.yaml" --include="*.md" .

# Find webhook URLs
grep -r "https://open.feishu.cn\|https://oapi.dingtalk.com\|webhook" \
  --include="*.py" --include="*.sh" --include="*.yaml" --include="*.md" .
```

## Report Template

After audit, present findings in this format:

| Permission | Status | Source Found | Hermes Target | Blocking Impact |
|-----------|--------|-------------|---------------|-----------------|
| QQ邮箱授权码 | ❌ 未配置 | 脚本硬编码 | config.yaml | 所有邮件脚本 |
| GitHub SSH | ❌ 未配置 | 无 | ~/.ssh/ | 备份推送 |
| 远程服务器 | ❌ 未配置 | 脚本提取 | ~/.ssh/jorge_server | 监控/报告 |

## Common Pitfalls

1. **Assuming credentials transfer with code.** They don't. SSH keys, env vars, and local configs are outside git.

2. **Not checking for custom-named SSH keys.** Look for `~/.ssh/jorge_server`, not just `id_rsa`.

3. **Missing remote server references in HTML/dashboard files.** `dashboard.html` may contain IP addresses not found in `.py` files.

4. **Not verifying after migration.** Always test: send a test email, `ssh` to remote, `git push` to GitHub.
