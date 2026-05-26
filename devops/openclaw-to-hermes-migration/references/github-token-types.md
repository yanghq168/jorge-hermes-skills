# GitHub Token Types for Automation

## Quick Reference

| Token Type | Prefix | Git Operations | API Calls | Best For |
|-----------|--------|---------------|-----------|----------|
| **Classic PAT** | `ghp_` | ✅ Yes | ✅ Yes | General automation, CI/CD |
| **Fine-Grained PAT** | `github_pat_` | ❌ No | ✅ Yes | API-only integrations, third-party apps |
| **GitHub App Token** | `ghs_` | ✅ Yes | ✅ Yes | Production automation, org-level |
| **OAuth Token** | Varies | ✅ Yes | ✅ Yes | User-facing integrations |

## The Fine-Grained PAT Trap

GitHub Fine-Grained PATs (`github_pat_*`) **do NOT work for Git HTTPS operations**.

When you try `git push` or `git clone` with a Fine-Grained PAT:
```
remote: Invalid username or token.
remote: Password authentication is not supported for Git operations.
fatal: Authentication failed for 'https://github.com/...'
```

This is by design — Fine-Grained PATs are API-only.

## Solutions

### Option 1: Use SSH Keys (Recommended for Servers)

```bash
# Generate key
ssh-keygen -t ed25519 -C "hermes@server" -f ~/.ssh/github_backup -N ""

# Add public key to GitHub: https://github.com/settings/keys
cat ~/.ssh/github_backup.pub

# Configure SSH host alias
cat >> ~/.ssh/config << 'EOF'
Host github-backup
    HostName github.com
    User git
    IdentityFile ~/.ssh/github_backup
    StrictHostKeyChecking no
EOF

# Use SSH URL for repos
git remote set-url origin git@github.com:USER/REPO.git
```

### Option 2: Use Classic PAT

1. Go to https://github.com/settings/tokens/new
2. Select **Classic token** (NOT Fine-Grained)
3. Scope: `repo` (full repository access)
4. Generate and use `ghp_xxx` token

```bash
# Store in git credentials
echo "https://USER:ghp_xxx@github.com" > ~/.git-credentials
git config --global credential.helper store
```

### Option 3: GitHub CLI

```bash
# Install gh CLI
# Login with device flow (for Fine-Grained) or token
echo "TOKEN" | gh auth login --with-token  # Classic only

# For Fine-Grained, use device flow:
gh auth login --web
```

## Testing

```bash
# Test Git HTTPS with stored credentials
git ls-remote https://github.com/USER/REPO.git HEAD

# Test SSH
git ls-remote git@github.com:USER/REPO.git HEAD

# Test API with Fine-Grained PAT
curl -H "Authorization: token github_pat_xxx" \
  https://api.github.com/user/repos
```

## Migration Context

When migrating OpenClaw workspaces to Hermes:
- Old repos may have used Classic PATs or SSH keys
- If the user provides a `github_pat_*` token, expect Git operations to fail
- Immediately explain the limitation and offer SSH or Classic PAT
- Do NOT waste time trying URL variations (`oauth2:`, `x-access-token:`, etc.) — they don't work
