# Server Git Pull Fallback Strategy

## Problem

Remote servers often cannot `git pull` from GitHub due to:
- HTTPS timeout (slow/unstable server-to-GitHub connection)
- Missing SSH deploy keys
- GitHub host verification failures
- Firewall restrictions

## Symptoms

```bash
# git fetch origin master
# ... hangs for 60+ seconds then times out
fatal: unable to access 'https://github.com/...': Connection timed out
```

Or:

```bash
ssh -T git@github.com
git@github.com: Permission denied (publickey).
```

## Solution: Local Clone + Incremental Sync

When server-side git operations fail, fall back to this workflow:

### Step 1: Clone Locally

```bash
cd /tmp
rm -rf site_source
git clone -b master --depth 1 https://github.com/user/repo.git site_source
```

### Step 2: Identify Changed Files

Compare local (GitHub latest) vs remote (server current) using MD5:

```bash
# Define files to check
FILES=(
  "index.html"
  "styles.css"
  "aivideo/index.html"
  "aivideo/nav.js"
  "aivideo/style.css"
  "chatgpt/index.html"
  "chatgpt/style.css"
)

# Compare and collect changed files
CHANGED=()
for f in "${FILES[@]}"; do
  local_md5=$(md5sum /tmp/site_source/$f 2>/dev/null | awk '{print $1}')
  remote_md5=$(ssh -i ~/.ssh/key user@server "md5sum /var/www/example.com/$f 2>/dev/null" | awk '{print $1}')
  if [ "$local_md5" != "$remote_md5" ]; then
    CHANGED+=("$f")
    echo "CHANGED: $f"
  fi
done
```

### Step 3: Sync Only Changed Files

```bash
for f in "${CHANGED[@]}"; do
  # Ensure parent directory exists
  dir=$(dirname "$f")
  if [ "$dir" != "." ]; then
    ssh -i ~/.ssh/key user@server "mkdir -p /var/www/example.com/$dir"
  fi
  # Copy file
  scp -i ~/.ssh/key "/tmp/site_source/$f" "user@server:/var/www/example.com/$f"
  echo "Synced: $f"
done
```

### Step 4: Verify

```bash
# Re-check MD5s
for f in "${CHANGED[@]}"; do
  local_md5=$(md5sum /tmp/site_source/$f | awk '{print $1}')
  remote_md5=$(ssh -i ~/.ssh/key user@server "md5sum /var/www/example.com/$f" | awk '{print $1}')
  if [ "$local_md5" == "$remote_md5" ]; then
    echo "✅ Verified: $f"
  else
    echo "❌ Mismatch: $f"
  fi
done
```

## Diagnosing Server-to-GitHub Connectivity

When `git fetch` fails, run these checks in order to identify the root cause:

### Check 1: Basic Network Connectivity

```bash
ping -c 3 github.com
# Should resolve and respond (typical: 100-300ms)
```

### Check 2: HTTPS Access (curl)

```bash
curl --http1.1 -s -o /dev/null -w '%{http_code} %{time_total}s' https://github.com
# Expected: 200 2-5s
```

**If this works but git fails → Git smart HTTP protocol issue (see below)**

### Check 3: Git Smart HTTP Endpoint

```bash
curl -I --http1.1 https://github.com/user/repo.git/info/refs?service=git-upload-pack
# Expected: 200 with Content-Type: application/x-git-upload-pack-advertisement
```

**If this hangs → GitHub may block or throttle Git protocol from this IP**

### Check 4: Git Protocol Port

```bash
nc -zv github.com 9418
# Git protocol port (optional, often blocked)
```

### Check 5: SSH Access (if using deploy keys)

```bash
ssh -T git@github.com
# Expected: "Hi user/repo! You've successfully authenticated..."
```

## The Git Smart HTTP Timeout Mystery

**Symptom:** `curl https://github.com` works fine (4 seconds), but `git fetch` hangs indefinitely.

**Root Cause:** Git uses the "smart HTTP" protocol which involves a long-polling POST request to `/git-upload-pack`. Some network environments (certain cloud providers, regions, or firewalls) handle this differently from regular HTTPS GET requests:

- Connection may be kept open but data transfer stalls
- HTTP/2 negotiation may hang with certain Git versions
- TLS handshake completes but application-layer data doesn't flow

**Verification:**

```bash
# This works (regular HTTPS GET)
curl --http1.1 https://github.com/yanghq168/wannengai.git/info/refs?service=git-upload-pack

# But git fetch hangs at the same endpoint
GIT_CURL_VERBOSE=1 GIT_TRACE=1 git fetch origin master
# Stalls after "POST /git-upload-pack HTTP/1.1"
```

**Solution:** Don't waste time debugging — use the local clone + sync fallback immediately.

## Advanced: Tracing Git Fetch

If you must debug, use Git's trace flags:

```bash
cd /var/www/example.com
GIT_TRACE_PACKET=1 GIT_TRACE=1 GIT_CURL_VERBOSE=1 \
  timeout 30 git fetch --depth=1 origin master 2>&1 | tail -50
```

Look for:
- `> POST /git-upload-pack HTTP/1.1` — request sent
- `< HTTP/1.1 200 OK` — response received
- If nothing after the POST → network stalls at application layer

## When to Use This Approach

| Scenario | Approach |
|----------|----------|
| Server has stable GitHub access + SSH key | `git pull` on server |
| Server HTTPS to GitHub works but slow | `git fetch --depth=1` on server |
| `curl github.com` works but `git fetch` hangs | **Local clone + incremental sync** |
| Server cannot reach GitHub at all | Local clone + full rsync |
| Large file transfer over slow connection | Split + concat (see main skill) |
| Only 1-2 files changed | Direct scp of changed files |

## Key Insight

**Don't fight the network.** If server-to-GitHub is unreliable, move the git operations to your local machine (which likely has better connectivity) and use scp/rsync for deployment. MD5 comparison ensures you only transfer what actually changed.
