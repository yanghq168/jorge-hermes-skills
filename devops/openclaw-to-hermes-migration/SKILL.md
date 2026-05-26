---
name: openclaw-to-hermes-migration
description: "Migrate OpenClaw skills, agents, and workspaces to Hermes Agent. Covers skill format conversion, cronjob rewriting, MCP adapter changes, agent role def archiving, and compatibility assessment."
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [migration, openclaw, hermes, skills, agents, devops]
    related_skills: [hermes-agent, hermes-agent-skill-authoring]
---

# OpenClaw → Hermes Migration Guide

## Overview

OpenClaw and Hermes Agent share the same conceptual foundation (SKILL.md format, tool calling, persistent memory) but differ in CLI commands, cron scheduling, MCP invocation, and agent architecture. This skill guides systematic migration of OpenClaw assets to Hermes.

## When to Use

- User mentions OpenClaw skills/agents they want to use in Hermes
- Migrating a workspace from OpenClaw to Hermes
- Assessing compatibility of external skill repos
- Converting `openclaw cron` jobs to Hermes `cronjob` format

## Compatibility Matrix

| OpenClaw Feature | Hermes Equivalent | Compatibility |
|-----------------|-------------------|---------------|
| `openclaw cron` | `cronjob` tool / `hermes cron` CLI | ⚠️ Rewrite needed |
| `clawhub install` | `hermes skills install` | ❌ Different registry |
| `mcp: service` | Native MCP client (`hermes mcp`) | ⚠️ Format differs |
| `mcporter` | `hermes mcp` | ⚠️ Command differs |
| `SKILL.md` format | Same YAML frontmatter | ✅ Compatible |
| `skills/<name>/` dir | `~/.hermes/skills/<name>/` | ✅ Compatible |
| `AGENTS.md` | No direct equivalent | ❌ Not compatible |
| `SOUL.md` / `USER.md` | No direct equivalent | ❌ Not compatible |
| `HEARTBEAT.md` | No direct equivalent | ❌ Not compatible |
| Agent role `.md` files | Reference docs only | ⚠️ Convert to ref |

## Migration Workflow

### 1. Assess the Source Repo

```bash
# Clone and inspect
git clone <repo-url> /tmp/source-repo
cd /tmp/source-repo

# Identify skill directories
find . -name "SKILL.md" -not -path "*/node_modules/*" | sort

# Identify agent directories
find . -path "*/agents/*.md" -o -path "*/agency-agents/*.md" | wc -l

# Check for OpenClaw-specific files
grep -r "openclaw\|clawhub\|mcporter" --include="*.md" --include="*.py" --include="*.sh" .
```

### 2. Classify Each Skill

| Category | Action | Example |
|----------|--------|---------|
| Pure docs (no CLI calls) | Copy directly | `github`, `summarize`, `weather` |
| Has `openclaw cron` | Rewrite for `cronjob` | `ai-news-daily`, `daily-report` |
| Has `mcporter` / MCP | Rewrite for `hermes mcp` | `tencent-docs` |
| Has `clawhub` commands | Remove / replace | `self-improving` |
| OpenClaw-specific scripts | Rewrite or archive | `push_feishu.py` with `openclaw` refs |

### 3. Rewrite Cron-Based Skills

**Before (OpenClaw):**
```python
# In SKILL.md or Python:
"""安装后自动创建 OpenClaw 定时任务"""
# Python creates cron via openclaw API
```

**After (Hermes):**
```markdown
# In SKILL.md:
使用 Hermes `cronjob` 工具创建定时任务：

```bash
hermes cron create \
  --name "skill-name" \
  --schedule "0 9 * * *" \
  --script "~/.hermes/skills/skill-name/run.sh"
```

或在对话中使用 `cronjob` 工具创建。
```

**Key changes:**
- Replace `openclaw cron create` with `hermes cron create` or `cronjob` tool
- Replace `openclaw cron list/run/remove` with `hermes cron` equivalents
- Update documentation references
- Create `run.sh` wrapper script if not present

**For standalone cron job repos** (not embedded in skills):
- See `references/cron-job-migration-patterns.md` for detailed path mapping, config loading, LLM replacement decisions, and directory layout.
- Typical structure: `~/.hermes/cron/{scripts,config,logs}/`
- Unified `config_loader.py` for shared email/database settings
- All scripts must be executable (`chmod +x`)
- Log files go to `~/.hermes/cron/logs/`, not `/var/log/`

### 4. Rewrite MCP-Dependent Skills

**Before (OpenClaw):**
```markdown
```
mcp: tencent-docs
tool: create_smartcanvas_by_markdown
arguments: { ... }
```
```

**After (Hermes):**
```markdown
通过 `hermes mcp` 配置 MCP 服务器：

```bash
hermes mcp add tencent-docs --url https://docs.qq.com/openapi/mcp
```

然后使用原生工具调用（具体取决于 Hermes MCP 集成方式）。
```

**Key changes:**
- Replace inline `mcp:` blocks with `hermes mcp add` configuration
- Update tool invocation examples
- Note that exact MCP tool calling may vary by Hermes version

### 5. Handle Agent Role Definitions

OpenClaw's `agents/` and `agency-agents/` directories contain 100+ `.md` role definition files. These are **not directly loadable** in Hermes (no `AGENTS.md` / `SOUL.md` / `USER.md` system).

**Recommended approach:**
1. Copy all `.md` files to `~/.hermes/skills/agent-roles/references/`
2. Create a `SKILL.md` that catalogs them as a reference library
3. The skill serves as documentation, not executable agents

```bash
# Copy agent definitions
mkdir -p ~/.hermes/skills/agent-roles/references
cp -r source-repo/agents/* ~/.hermes/skills/agent-roles/references/

# Create catalog skill (see templates/agent-roles-catalog.md)
```

### 6. Clean Up OpenClaw-Specific References

Search and replace in all migrated files:

| Pattern | Replacement |
|---------|-------------|
| `openclaw` | `hermes` (context-dependent) |
| `clawhub install` | `hermes skills install` |
| `clawhub sync` | `hermes skills update` |
| `mcporter` | `hermes mcp` |
| `~/.openclaw/` | `~/.hermes/` |
| `/root/.openclaw/` | `/home/ubuntu/.hermes/` or `~/.hermes/` |

### 7. Post-Migration Permissions Audit

After code migration, credentials and permissions do NOT transfer automatically. SSH keys, SMTP auth codes, API tokens, and remote server access must be explicitly reconfigured.

**Audit checklist:**
- [ ] Email/SMTP auth code configured and tested (send test email)
- [ ] GitHub SSH key or token configured and tested (`git ls-remote` or `ssh -T git@github.com`)
- [ ] Remote server SSH key recreated and tested (`ssh -i <key> user@host 'uptime'`)
- [ ] API tokens (Feishu, etc.) configured

**Extracting hidden config from original repo:**
```bash
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
```

**When remote server uses password auth (not key auth):**
If `ssh` fails with "Permission denied (publickey,password)", the remote server hasn't been configured for key auth. The user must:
1. Log into the remote server
2. Create `~/.ssh/authorized_keys` with the new public key
3. Set correct permissions: `chmod 700 ~/.ssh; chmod 600 ~/.ssh/authorized_keys`

After the user confirms they've deployed the key, re-test the connection.

**Note:** Some users pre-configure `sudoers.d` for the remote user (e.g., `ai-worker ALL=(ALL) NOPASSWD:ALL`). This is useful for scripts that run `sudo` commands over SSH, but does NOT replace SSH key authentication. Both are needed.

**Collaborative configuration pattern:**
When the user says "协助我一起配置" (help me configure together) or similar:
1. Present clear options for each permission (2-3 methods)
2. Ask for credentials securely; never log them in output
3. Verify immediately after each step (test email, SSH, git push)
4. Report status in table format with ✅/❌ and blocking impact
5. Handle partial completion — proceed with what we have, queue the rest

**GitHub Token Type Pitfall:**
GitHub Fine-Grained PATs (`github_pat_*`) do NOT work for Git HTTPS operations (push/clone). They only work for API calls (`curl` with `Authorization: token`). For Git operations, you MUST use either:
- **Classic PAT** (`ghp_*`) with `repo` scope — works for both Git and API
- **SSH key** — works for Git, separate from API tokens
- **GitHub CLI (`gh`)** with device flow or classic token

If the user provides a `github_pat_*` token and Git push fails with "Password authentication is not supported", explain this limitation and ask for a Classic PAT or SSH key instead.

## Common Pitfalls

1. **Assuming full compatibility.** The SKILL.md format is compatible, but anything calling `openclaw` CLI or APIs needs rewriting.

2. **Forgetting to update paths.** OpenClaw workspaces often hardcode `/root/.openclaw/` — these break on Hermes which uses `~/.hermes/`.

3. **Trying to load Agent roles as skills.** The 177 agent `.md` files are role definitions, not executable skills. They go in `references/`, not as top-level skills.

4. **Missing `run.sh` wrappers.** Hermes cron jobs expect executable scripts. Create a `run.sh` that `cd`s to the skill dir and runs the Python script.

5. **Not replacing `openclaw infer model run` calls.** Scripts that used OpenClaw's LLM inference need a new approach: either template-based generation (pure Python), `delegate_task` subagents, or direct LLM API calls. See `references/cron-job-migration-patterns.md` for the decision tree.

6. **Not checking for Node.js dependencies.** Some OpenClaw skills bundle `node_modules` (e.g., Playwright). These are often not needed in Hermes — evaluate before copying.

7. **Leaving `__pycache__` and `.pyc` files.** Clean these before installing skills to avoid clutter.

8. **Not auditing permissions after migration.** SSH keys, email auth codes, API tokens, and Git credentials do NOT transfer with code. Always run the permissions audit checklist (see section 7 above).

9. **Using Fine-Grained PAT for Git operations.** GitHub Fine-Grained PATs (`github_pat_*`) do NOT work for `git push`/`git clone`. They only work for API calls. For Git operations, use Classic PAT (`ghp_*`) or SSH keys.

## Verification Checklist

- [ ] All `openclaw` / `clawhub` / `mcporter` references removed or updated
- [ ] Cron jobs converted to `hermes cron` or `cronjob` tool format
- [ ] MCP configurations converted to `hermes mcp` format
- [ ] Agent roles archived in `references/`, not installed as skills
- [ ] `run.sh` wrappers created for cron-scheduled skills
- [ ] Paths updated from `~/.openclaw/` to `~/.hermes/`
- [ ] `__pycache__` and `.pyc` files cleaned
- [ ] `node_modules` evaluated and either included or excluded
- [ ] SKILL.md frontmatter validated (starts with `---`, has `name` + `description`)
- [ ] Test with `skill_view(name)` to confirm skill loads
- [ ] **Permissions audit completed** (see section 7 above):
  - [ ] Email/SMTP auth code configured and tested
  - [ ] GitHub SSH key or token configured and tested
  - [ ] Remote server SSH key recreated and tested
  - [ ] API tokens (Feishu, etc.) configured

## One-Shot Recipe: Full Repo Migration

```bash
# 1. Clone source
git clone https://github.com/user/openclaw-repo /tmp/migrate-src

# 2. Create target structure
mkdir -p ~/.hermes/skills/{new-skill-1,new-skill-2,agent-roles/references}

# 3. Copy pure doc skills
cp /tmp/migrate-src/skills/github/SKILL.md ~/.hermes/skills/github/
cp /tmp/migrate-src/skills/summarize/SKILL.md ~/.hermes/skills/summarize/

# 4. Rewrite cron skills
cp -r /tmp/migrate-src/skills/ai-news-daily ~/.hermes/skills/
# Edit SKILL.md: replace openclaw cron with hermes cron
# Create run.sh wrapper

# 5. Archive agent roles
cp -r /tmp/migrate-src/agents/* ~/.hermes/skills/agent-roles/references/

# 6. Verify
find ~/.hermes/skills -name "SKILL.md" | sort
hermes skills list
```

## Cron Job Migration (Detailed)

For step-by-step cron job migration patterns, see:
- `references/cron-job-migration-patterns.md` — Categorization, path mapping, config loading, LLM replacement decisions, email patterns, directory layout, verification.
- `references/qq-email-smtp-setup.md` — QQ Mail SMTP configuration (common in Chinese OpenClaw workspaces for content distribution).
- `references/post-migration-permissions-audit.md` — Systematic audit of SSH keys, email auth, Git credentials, API tokens, and remote server access after migration.
- `references/github-token-types.md` — GitHub Fine-Grained vs Classic PAT differences for Git operations vs API calls.

## Templates

- `templates/cron-config-loader.py` — Unified config loader for migrated cron jobs. Copy to `~/.hermes/cron/scripts/config_loader.py` and customize paths.
- `templates/cron-config.yaml` — Unified configuration template. Copy to `~/.hermes/cron/config/config.yaml` and fill in your credentials.
- `templates/backup-repo-setup.sh` — Script to create new GitHub backup repos (skills + agency) with SSH auth. Run after migration to set up separate backup targets that do NOT overwrite existing OpenClaw repos.
- `references/github-token-types.md` — GitHub Fine-Grained vs Classic PAT differences. Critical: Fine-Grained PATs (`github_pat_*`) do NOT work for Git operations (push/clone). Use SSH keys or Classic PATs for backup scripts.

## Related

- `hermes-agent` — Hermes setup, CLI, and configuration
- `hermes-agent-skill-authoring` — Writing valid SKILL.md files
