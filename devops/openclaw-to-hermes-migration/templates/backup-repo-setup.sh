#!/bin/bash
# 备份仓库设置脚本 - Hermes 迁移后使用
# 创建新的 GitHub 仓库用于备份，不覆盖原有 OpenClaw 仓库

set -e

GITHUB_USER="${GITHUB_USER:-yanghq168}"
SSH_KEY="${SSH_KEY:-/home/ubuntu/.ssh/jorge_server}"
TOKEN="${GITHUB_TOKEN:-}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "📦 Hermes 备份仓库设置"
echo "============================================================"

# Check SSH key
if [ ! -f "$SSH_KEY" ]; then
    echo -e "${YELLOW}⚠️ SSH密钥不存在，生成新密钥...${NC}"
    ssh-keygen -t ed25519 -C "hermes-backup@$(hostname)" -f "$SSH_KEY" -N ""
    echo -e "${GREEN}✅ 已生成SSH密钥${NC}"
    echo "📋 请将此公钥添加到GitHub:"
    cat "${SSH_KEY}.pub"
    echo ""
    echo "访问: https://github.com/settings/keys"
    echo "然后重新运行此脚本"
    exit 0
fi

# Create repos via API (works with Fine-Grained PAT)
create_repo() {
    local repo_name="$1"
    local description="$2"
    
    echo "📝 创建仓库: ${repo_name}"
    
    if [ -n "$TOKEN" ]; then
        curl -s -H "Authorization: token ${TOKEN}" \
            -H "Accept: application/vnd.github.v3+json" \
            https://api.github.com/user/repos \
            -d "{\"name\":\"${repo_name}\",\"description\":\"${description}\",\"private\":false}" \
            2>/dev/null | grep -E '"name"|"html_url"' | head -4
    else
        echo -e "${YELLOW}⚠️ 未设置 GITHUB_TOKEN，跳过API创建${NC}"
        echo "   请手动创建: https://github.com/new"
    fi
}

# Create backup repos
create_repo "jorge-hermes-skills" "Hermes平台 skills 每日备份"
create_repo "jorge-hermes-agency" "Hermes平台 agency/agent配置 每日备份"

# Configure local backup directories
echo ""
echo "🔧 配置本地备份目录..."

mkdir -p ~/.hermes/skills-backup ~/.hermes/agency-backup

# Init skills-backup
cd ~/.hermes/skills-backup
if [ ! -d ".git" ]; then
    git init
    git remote add origin "git@github.com:${GITHUB_USER}/jorge-hermes-skills.git"
fi
git config user.name "Hermes Backup"
git config user.email "backup@hermes.local"

# Init agency-backup
cd ~/.hermes/agency-backup
if [ ! -d ".git" ]; then
    git init
    git remote add origin "git@github.com:${GITHUB_USER}/jorge-hermes-agency.git"
fi
git config user.name "Hermes Backup"
git config user.email "backup@hermes.local"

echo ""
echo -e "${GREEN}✅ 备份仓库配置完成${NC}"
echo ""
echo "📁 本地目录:"
echo "   ~/.hermes/skills-backup  →  jorge-hermes-skills"
echo "   ~/.hermes/agency-backup  →  jorge-hermes-agency"
echo ""
echo "🔑 SSH密钥: ${SSH_KEY}"
echo "   公钥: ${SSH_KEY}.pub"
echo ""
echo "⚠️  重要: 确保已将公钥添加到GitHub!"
echo "   https://github.com/settings/keys"
