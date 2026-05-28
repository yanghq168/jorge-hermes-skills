---
name: static-site-deployment
description: "Deploy static HTML/CSS/JS sites to remote servers via Nginx. Covers multi-subdomain setups, SPA smooth navigation fixes, and rsync/scp transfer strategies."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [nginx, static-site, deployment, subdomain, spa, rsync, scp]
    related_skills: [github-repo-management, openclaw-to-hermes-migration]
---

# Static Site Deployment

Deploy static HTML/CSS/JS websites to remote Linux servers using Nginx. Covers single-site and multi-subdomain configurations.

## Related Files

- `references/spa-transition-fix.md` — Detailed explanation of the CSS transition timing fix
- `references/server-git-pull-fallback.md` — When remote server cannot `git pull` from GitHub: local clone + incremental MD5 sync strategy
- `templates/nav-spa.js` — Complete working SPA navigation script with smooth transitions

## When to Use

- Deploying landing pages, marketing sites, or SPAs built with vanilla HTML/CSS/JS
- Setting up subdomains (e.g., `chatgpt.example.com`, `aivideo.example.com`)
- Fixing SPA navigation issues (smooth transitions, history API)
- Projects that need BOTH subpath (`/aivideo/`) AND subdomain (`aivideo.example.com`) access

## Prerequisites

- Remote server with Nginx installed
- SSH access to the server
- Domain DNS configured (A records pointing to server IP)

## Server Directory Structure

```
/var/www/example.com/
├── index.html          # Main site
├── styles.css
├── assets/
├── chatgpt/            # Subdomain content (also accessible via /chatgpt/)
│   ├── index.html
│   └── style.css
└── aivideo/            # Subdomain content (also accessible via /aivideo/)
    ├── index.html
    ├── nav.js
    ├── style.css
    ├── features/
    ├── solutions/
    ├── scenes/
    ├── price/
    └── help/
```

## Unified vs. Separate Deployment

When a project contains multiple related sites (e.g., main + aivideo + chatgpt), you have two architectural choices:

| Pattern | When to Use | Nginx Approach |
|---------|-------------|----------------|
| **Unified** (subpaths only) | All sites share one domain | Single `server` block with `location /aivideo/` aliases |
| **Separate** (subdomains only) | Each site needs its own branding/SSL | Multiple `server` blocks, one per subdomain |
| **Dual** (both) | User wants flexibility — this is common | Single config with BOTH subpath aliases AND subdomain server blocks |

**Default to Dual** unless the user explicitly asks for one or the other. Most users expect `example.com/aivideo/` to work AND `aivideo.example.com` to work.

## Deployment Steps

### 0. Verify SSH Access

Before deploying, confirm the SSH connection and locate the correct key:

```bash
# Check SSH config for the target host
grep -A5 "Host.*server\|HostName.*server_ip" ~/.ssh/config

# Test connection
ssh -i ~/.ssh/the_key -o StrictHostKeyChecking=no user@server "echo 'SSH OK'"
```

**If SSH key is not in GitHub account's SSH Keys:** `git clone git@github.com` will fail with "Host key verification failed". Use HTTPS with token instead, or ask the user to add the public key to GitHub.

**Key location pattern for this user:**
- Remote server SSH key: `~/.ssh/jorge_server` → connects to `ai-worker@82.156.225.39`
- This key is for the **remote server**, NOT for GitHub
- GitHub operations should use HTTPS with PAT, or a separate GitHub-deploy key

### 1. Prepare Local Source

Clone the repository locally (not on the remote server):

```bash
git clone -b <branch> --depth 1 <repo-url> /tmp/site_source
cd /tmp/site_source
```

**Why locally?** Remote servers often cannot reach GitHub (HTTPS timeout, no SSH key, firewall). Cloning locally avoids these issues.

### 2. Transfer to Server

**Option A: rsync (preferred for initial deploy or many changes)**

```bash
rsync -avz --exclude='.git' -e "ssh -i ~/.ssh/key" \
  /tmp/site_source/ user@server:/var/www/example.com/
```

**Option B: scp for single files**

```bash
scp -i ~/.ssh/key /tmp/site_source/file.html user@server:/var/www/example.com/
```

### Option C: Incremental sync (recommended when server git pull fails)

When the remote server cannot `git pull` from GitHub (HTTPS timeout, no SSH key, or network issues):

```bash
# Step 1: Clone locally
rm -rf /tmp/site_source && git clone -b master --depth 1 https://github.com/user/repo.git /tmp/site_source

# Step 2: Compare and sync ONLY changed files
for f in index.html styles.css aivideo/index.html aivideo/nav.js; do
  local_md5=$(md5sum /tmp/site_source/$f | awk '{print $1}')
  remote_md5=$(ssh -i ~/.ssh/key user@server "md5sum /var/www/example.com/$f" | awk '{print $1}')
  if [ "$local_md5" != "$remote_md5" ]; then
    scp -i ~/.ssh/key /tmp/site_source/$f user@server:/var/www/example.com/$f
    echo "Updated: $f"
  fi
done
```

**Why incremental:**
- Avoids transferring unchanged files (saves bandwidth)
- Works around unreliable server-to-GitHub connectivity
- MD5 verification ensures correctness
- Faster than full rsync when only a few files changed

**Common cause of server git pull failure:** Git smart HTTP protocol timeout. Even when `curl https://github.com` works, `git fetch` may hang because Git uses a long-polling POST to `/git-upload-pack` that some networks handle poorly. See `references/server-git-pull-fallback.md` for detailed diagnosis.

**Option D: Split + concat for unreliable connections**

When rsync/scp times out on larger files over slow/unreliable connections:

```bash
# Local: split into 1MB chunks
split -b 1M /tmp/archive.tar.gz /tmp/part_

# Transfer each chunk (resume-friendly)
for f in /tmp/part_*; do
  scp -i ~/.ssh/key "$f" user@server:/tmp/upload/
done

# Remote: reassemble and extract
ssh -i ~/.ssh/key user@server "cat /tmp/upload/part_* > /tmp/archive.tar.gz && tar -xzf /tmp/archive.tar.gz -C /var/www/example.com/"
```
```bash
# Local: split into 1MB chunks
split -b 1M /tmp/archive.tar.gz /tmp/part_

# Transfer each chunk (resume-friendly)
for f in /tmp/part_*; do
  scp -i ~/.ssh/key "$f" user@server:/tmp/upload/
done

# Remote: reassemble and extract
ssh -i ~/.ssh/key user@server "cat /tmp/upload/part_* > /tmp/archive.tar.gz && tar -xzf /tmp/archive.tar.gz -C /var/www/example.com/"
```

### 3. Nginx Configuration

#### Option A: Dual Access (Recommended)

Both subpaths AND subdomains work:

```nginx
# /etc/nginx/conf.d/example.com.conf

# Main site + subpath aliases
server {
    server_name example.com www.example.com;
    root /var/www/example.com;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    location /aivideo/ {
        alias /var/www/example.com/aivideo/;
        try_files $uri $uri/ /aivideo/index.html;
    }

    location /chatgpt/ {
        alias /var/www/example.com/chatgpt/;
        try_files $uri $uri/ /chatgpt/index.html;
    }

    listen 443 ssl;
    ssl_certificate /etc/letsencrypt/live/example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/example.com/privkey.pem;
}

server {
    listen 80;
    server_name example.com www.example.com;
    return 301 https://$host$request_uri;
}

# aivideo subdomain
server {
    server_name aivideo.example.com;
    root /var/www/example.com/aivideo;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    listen 443 ssl;
    ssl_certificate /etc/letsencrypt/live/aivideo.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/aivideo.example.com/privkey.pem;
}

server {
    listen 80;
    server_name aivideo.example.com;
    return 301 https://$host$request_uri;
}

# chatgpt subdomain (same pattern)
```

#### Option B: Subdomains Only

```nginx
server {
    listen 80;
    server_name aivideo.example.com;
    root /var/www/example.com/aivideo;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

Enable:

```bash
sudo ln -s /etc/nginx/sites-available/example.conf /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

### 4. SSL with Certbot

```bash
sudo certbot --nginx -d aivideo.example.com --non-interactive --agree-tos -m admin@example.com
```

## SPA Smooth Navigation Fix

### The Problem

When using JavaScript to intercept link clicks and swap page content (SPA-style navigation), CSS transitions may not trigger if the DOM element is replaced before the browser registers the initial state.

### The Fix

**Before (broken):**

```javascript
currentMain.replaceWith(nextMain);
nextMain.classList.add("is-page-entering");  // Too late — browser skips transition

requestAnimationFrame(function () {
    nextMain.classList.remove("is-page-entering");
});
```

**After (fixed):**

```javascript
nextMain.classList.add("is-page-entering");  // Set initial state BEFORE inserting
currentMain.replaceWith(nextMain);

void nextMain.offsetWidth;  // Force reflow so browser records the initial state

requestAnimationFrame(function () {
    nextMain.classList.remove("is-page-entering");  // Now transition triggers
});
```

### Key Points

1. **Set initial state before DOM insertion** — `classList.add()` before `replaceWith()`
2. **Force reflow** — `void element.offsetWidth` forces the browser to calculate layout
3. **Then trigger transition** — remove the class in `requestAnimationFrame`

### CSS Transition Setup

```css
.video-page {
    opacity: 1;
    transform: translateY(0);
    transition: opacity 0.18s ease, transform 0.18s ease;
}

.video-page.is-page-entering {
    opacity: 0;
    transform: translateY(12px);
}

.video-page.is-page-leaving {
    opacity: 0;
    transform: translateY(12px);
}
```

## Multi-Site Sync

When deploying multiple related sites (main + subdomains), ensure all copies are updated:

```bash
# Update main site
rsync -avz --exclude='.git' -e "ssh -i ~/.ssh/key" \
  ./main/ user@server:/var/www/example.com/

# Update subdomain
rsync -avz --exclude='.git' -e "ssh -i ~/.ssh/key" \
  ./aivideo/ user@server:/var/www/example.com/aivideo/

# Update shared nav.js to all aivideo subdirectories
for dir in features solutions scenes price help; do
  scp -i ~/.ssh/key ./aivideo/nav.js user@server:/var/www/example.com/aivideo/$dir/
done
```

## Verification

After deployment:

1. Check site loads: `curl -I https://aivideo.example.com/`
2. Verify SPA navigation: Click between tabs, check URL updates without full page reload
3. Check transition animation: Look for opacity/transform changes in DevTools

## Troubleshooting

| Issue | Cause | Fix |
|-------|-------|-----|
| 500 Internal Server Error | Missing directory or wrong permissions | Check `root` path in Nginx config |
| SPA navigation falls back to full page load | `nav.js` not intercepting clicks | Check `rootPath` matches URL path |
| CSS transitions not animating | Browser optimizes away the transition | Add `void element.offsetWidth` reflow |
| scp/rsync timeout | Large files over slow connection | Use split + concat method |
| Git clone fails on server | No GitHub SSH key on server | Clone locally, then rsync |
| `git fetch` hangs but `curl github.com` works | Git smart HTTP protocol timeout | Use local clone + incremental sync |
| Subpath returns 404 | `alias` directive missing trailing slash | Ensure `alias /path/dir/;` has trailing slash |
| Subdomain shows wrong content | `root` path points to parent instead of subdirectory | Set `root /var/www/example.com/aivideo;` not `/var/www/example.com;` |

### Git Status Misleading: "All files deleted"

**Symptom:** `git diff --stat origin/master` shows every file as deleted (e.g., `aivideo/index.html | 180 -------`), even though the files exist on disk and the site works.

**Root Cause:** The working directory was populated by non-git means (scp, rsync, manual upload), so Git sees them as untracked local files. When comparing against the remote branch, Git reports them as "deleted from the index" — but the actual file **contents may match perfectly**.

**Verification — don't trust `git diff` alone:**

```bash
# Compare actual content, not git status
diff <(git show origin/master:chatgpt/index.html) chatgpt/index.html

# Or use MD5 for binary files
git show origin/master:assets/logo.png | md5sum
md5sum assets/logo.png
```

**Key Lesson:** `git diff --stat` showing deletions does NOT mean the server is missing files. It means Git doesn't know about them. Always verify by comparing actual file contents before deciding which direction to sync.

**When server has newer code than GitHub:**
1. Use `diff <(git show origin/master:FILE) FILE` to see real differences
2. If server is newer, commit locally and push to update the remote
3. If remote is newer, use the incremental sync approach to pull changes

**When GitHub has newer code and user wants to overwrite server:**
1. First verify with `diff` that remote really IS different
2. Then use `git reset --hard origin/master` + `git clean -fd` to force match
3. Reload Nginx and verify all endpoints respond with 200

### Detecting Which Side Is Newer

```bash
cd /var/www/example.com

# Check remote commit history
git log --oneline origin/master -5

# Check if local has uncommitted changes
git status --short

# Compare specific files
diff <(git show origin/master:aivideo/index.html) aivideo/index.html

# If diff shows additions in local (lines prefixed with >), local is newer
# If diff shows additions in remote (lines prefixed with <), remote is newer
```

### Forcing Server to Match Remote (Discard Local Changes)

When the user explicitly asks to **pull latest GitHub code and overwrite server** (discard all local modifications):

```bash
cd /var/www/example.com

# Reset working tree to match origin/master exactly
git reset --hard origin/master

# Remove any untracked files/directories not in the repo
git clean -fd

# Verify clean state
git status
# Expected: "nothing to commit, working tree clean"
```

**⚠️ Warning:** This permanently destroys any local changes. Only use when the user explicitly requests a fresh pull from GitHub.

**After reset, reload Nginx:**
```bash
sudo nginx -t && sudo systemctl reload nginx
```

**Verification:**
```bash
# Check all pages respond
curl -sL -o /dev/null -w '%{http_code}' -H 'Host: example.com' http://127.0.0.1/aivideo/
curl -sL -o /dev/null -w '%{http_code}' -H 'Host: example.com' http://127.0.0.1/chatgpt/
curl -sL -o /dev/null -w '%{http_code}' -H 'Host: example.com' http://127.0.0.1/
```
