---
name: remote-server-deployment
description: "Deploy services, web apps, and static sites to a remote Linux server (especially Tencent Cloud CVM / Aliyun ECS / AWS EC2) via SSH. Covers the shared playbook that applies to all variants: SSH key access, the three-layer firewall model, the Hermes secret-mask pitfall, Gitee/GitHub deploy keys, transfer strategies (rsync/scp/local-clone+incremental-sync), and the post-deploy verification recipe. Variants covered as labeled subsections -- bare service (MySQL/Redis/Nginx), Spring Boot / RuoYi web app, and static HTML/CSS/JS site."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [deployment, ssh, nginx, springboot, static-site, gitee, github, tencent-cloud, devops]
    related_skills: [github-repo-management, openclaw-to-hermes-migration]
---

# Remote Server Deployment

When the user says "set up X on my server" / "拉取并部署" / "deploy this to my server" — for any service or application that needs to run on a remote cloud VM. This umbrella covers the **shared playbook** that applies across all deployment variants on a single server profile (Tencent Cloud CVM, with `ai-worker@82.156.225.39` reachable via `~/.ssh/jorge_server` and passwordless sudo).

## Variants — pick the section that matches the workload

| If the user wants to deploy… | Read this section |
|---|---|
| A bare service — MySQL/MariaDB, Redis, PostgreSQL, Nginx, or any daemon that listens on a TCP port | [§ A. Bare Service Deployment](#a-bare-service-deployment) |
| A Java/Spring Boot web app (especially RuoYi 若依 or its forks) — `mvn package` → fat jar → env-injected start → background daemon | [§ B. Spring Boot / Java Web App](#b-spring-boot--java-web-app) |
| A static HTML/CSS/JS website (landing page, SPA, marketing site) — Nginx virtual host, `try_files`, optional subdomains | [§ C. Static HTML/CSS/JS Site](#c-static-htmlcssjs-site) |

All three variants share the SSH access, firewall, secret, transfer, and verification recipes below. Read § Shared Playbook first.

---

## Shared Playbook (applies to every variant)

### 1. SSH access (do this FIRST, every time)

User's setup (from memory): `ssh -i ~/.ssh/jorge_server ai-worker@82.156.225.39` — key-based login, sudo NOPASSWD.

```bash
REMOTE="ssh -i ~/.ssh/jorge_server ai-worker@82.156.225.39"
$REMOTE "whoami; sudo -n whoami"   # verify both work; if 'Permission denied' or 'sudo: a password is required', stop and ask user
```

**SSH failure modes** (do not guess the cause — diagnose):

| Symptom | Likely cause | Action |
|---|---|---|
| `Permission denied (publickey)` | Key not in remote `authorized_keys` | Ask user to confirm key + add if missing |
| `Permission denied (publickey,password)` | Key auth failed AND no password fallback configured | Same as above; cannot proceed |
| `Host key verification failed` | `known_hosts` missing entry | `ssh-keyscan <host> >> ~/.ssh/known_hosts` then retry |
| `sudo: a password is required` | User does NOT have passwordless sudo | Stop — this skill assumes NOPASSWD sudo |

When using `ssh -t` from Hermes `terminal()` for any interactive `read -s` block: **it will fail** with "Pseudo-terminal will not be allocated because stdin is not a terminal". The `pty=true` flag enables PTY for the agent's tool, not for the remote shell's stdin. Have the user run interactive steps in their own SSH session instead.

### 2. The Three-Layer Firewall Model (CRITICAL — diagnose from outside in)

Cloud VMs have THREE independent layers. If the port is unreachable from outside but SSH (22) works, **it is almost always Layer 1** (cloud security group) — which the agent **cannot** modify from inside the VM. Tell the user clearly: "服务都配好了，22 通说明机器可达；其他端口不通但服务器内端口在监听 — 是云厂商安全组的事，需要你去控制台放行。"

```
[Client]
   ↓
┌─────────────────────────────────┐
│ Layer 1: Cloud security group    │ ← OUTSIDE the VM, console-only
│ (腾讯云/阿里云/AWS 安全组)        │
└─────────────────────────────────┘
   ↓
┌─────────────────────────────────┐
│ Layer 2: Host iptables/firewalld │ ← INSIDE the VM, sudo
└─────────────────────────────────┘
   ↓
┌─────────────────────────────────┐
│ Layer 3: Service bind-address    │ ← INSIDE the config file
└─────────────────────────────────┘
   ↓
[Service]
```

**Diagnostic recipe:**
```bash
# From a separate host (your local machine):
nc -zv <server-ip> 22               # if fails → host unreachable, not firewall
nc -zv <server-ip> 3306             # if 22 works but 3306 fails → Layer 1

# Inside the server:
sudo ss -tlnp | grep <port>        # must show 0.0.0.0:<port>, not 127.0.0.1:<port>
sudo iptables -L INPUT -n -v --line-numbers | head -30
sudo firewall-cmd --list-ports     # usually 'not running' on TencentOS
```

See `references/tencent-cvm-firewall.md` for the Tencent-specific console path, the pre-installed YJ ipset, and what NOT to do (`iptables -F` flushes Tencent's rules and may lock you out).

### 3. ⚠️ The Hermes Secret-Mask Pitfall (READ BEFORE WRITING ANY SECRET)

The Hermes tool layer (`terminal`, `execute_code`, `write_file`) automatically masks any literal sensitive string — passwords, tokens, API keys — that appears in tool input/output. The critical trap: **the mask applies to the command BEFORE execution**, so:

- `ssh host 'cat > /etc/app.conf << EOF\npassword=123456\nEOF'` → file on disk contains `***`, not `123456`
- `python3 -c "open('/etc/app.conf','w').write('password=123456')"` → file on disk contains `***`
- `echo "password=123456" > /etc/app.conf` → file on disk contains `***`
- `sed -i "s/...secret.../.../"` — same trap
- `write_file` with a literal secret in content — same trap

The result: the service starts but logs `Access denied` for a credential you "definitely set correctly" because the file on disk really does contain `***`, not the password. **This has cost 30+ minutes across multiple sessions.**

**Verify with raw bytes, NOT with `cat`:**
```bash
ssh user@host 'grep "PASSWORD" /path/to/script | od -c | head -3'
```
- Healthy output: `1 2 3 4 5 6` digit characters
- Burned output: `* * *` asterisk characters

**Workarounds (ranked):**

1. **Have the user run a `read -s` step themselves in their own SSH session** (BEST for one-off setup). The secret travels terminal → SSH → remote shell stdin, never through a Hermes tool call.
   ```bash
   stty -echo; read -r -p "DB PW: " DBPW; echo
   printf 'export DB_PASSWORD="$DBPW"
   chmod 600 ~/.app_env
   stty echo
   ```
   The start script does `source ~/.app_env` at the top. See `templates/springboot-start.sh`.

2. **Hardcode the secret in the project source** and `git push`. The secret travels through the git remote, not through Hermes. Acceptable only for dev/throwaway deploys (it enters git history).

3. **Don't pass the secret as a literal at all** — generate it on the remote (`openssl rand -base64 24`) and configure both ends in one session.

**What NOT to do:**
- ❌ `base64 -w0` then `echo $B64 | base64 -d` — the encoded form still contains the secret character sequence and triggers the filter
- ❌ `python3 -c "...literal..."` — the literal in the python source is what gets masked
- ❌ Asking the user to paste the secret back in a Hermes message — masked in your output AND now in conversation history

See `references/hermes-secret-mask-pitfall.md` for the full reproduction recipe, why base64 also fails, and the ranked mitigation list with examples.

### 4. Private-repo auth: per-project deploy keys (Gitee or GitHub)

**Do NOT reuse the user's personal SSH key.** Generate one per remote machine × per repo family. The local `~/.ssh/jorge_server` key is for the remote server, NOT for GitHub/Gitee.

**For Gitee (user has separate Gitee account `yanghongquan` / 毛毛在燃烧):**
```bash
ssh user@host 'test -f ~/.ssh/gitee_<scope> || ssh-keygen -t ed25519 \
  -C "user@host-for-<scope>" -f ~/.ssh/gitee_<scope> -N ""'
ssh user@host 'cat ~/.ssh/gitee_<scope>.pub'   # user pastes into Gitee → 设置 → SSH公钥
```
Then append to `~/.ssh/config` on the remote:
```
Host gitee.com
    HostName gitee.com
    User git
    IdentityFile ~/.ssh/gitee_<scope>
    StrictHostKeyChecking accept-new
```
Verify: `ssh user@host 'ssh -T git@gitee.com 2>&1 | head -1'` should print `Hi <displayname>(@<username>)! You've successfully authenticated, but GITEE.COM does not provide shell access.` (Gitee never provides shell — that message is normal and means auth succeeded.)

See `references/gitee-ssh-deploy-key.md` for the verified recipe including common mistakes.

**For GitHub:** same pattern but use `github.com` as host; the GitHub equivalent message is `Hi <user>! You've successfully authenticated...` (no shell-access note).

### 5. Transfer strategies (pick the slowest one that still works)

| Method | When to use | Failure mode |
|---|---|---|
| `rsync -avz --exclude='.git' -e "ssh -i KEY" LOCAL/ user@host:REMOTE/` | Initial deploy or many files changed | `rsync timeout` on large files / slow connections |
| `scp -i KEY LOCAL_FILE user@host:REMOTE_FILE` | Single file or small set | Same — hangs on slow links |
| **Local clone + incremental MD5 sync** | Server cannot `git pull` from GitHub/Gitee (HTTPS works but `git fetch` hangs) | MD5 loop is O(files) ssh round-trips — slow for large trees |
| `split -b 1M` + multiple `scp` + remote `cat` concat | rsync/scp timeout on large files over slow links | Manual reassembly |

**When server-side `git pull` fails** (Git smart-HTTP timeout — common even when `curl github.com` works fine because Git's long-polling `POST /git-upload-pack` is treated differently by some networks), don't fight it. Move the git operations to your local machine:
```bash
git clone -b master --depth 1 <repo-url> /tmp/site_source
for f in "${FILES[@]}"; do
  local_md5=$(md5sum /tmp/site_source/$f | awk '{print $1}')
  remote_md5=$(ssh -i KEY user@host "md5sum /var/www/<dir>/$f" | awk '{print $1}')
  [ "$local_md5" != "$remote_md5" ] && scp -i KEY /tmp/site_source/$f user@host:/var/www/<dir>/$f
done
```
See `references/server-git-pull-fallback.md` for the diagnosis recipe (curl works but git hangs → smart-HTTP issue) and the MD5-sync implementation.

### 6. Post-deploy verification (universal)

```bash
# Inside the server (loopback test):
curl -sS -o /dev/null -w 'http_code=%{http_code}  time=%{time_total}s\n' --max-time 5 http://127.0.0.1:<port>/

# Listening port:
ssh user@host "(ss -tlnp 2>/dev/null || netstat -tlnp 2>/dev/null) | grep ':<port> '"

# Process is alive:
ssh user@host "ps -ef | grep -v grep | grep <pattern> | head -5"
```

For MySQL/Redis/services with auth, use `scripts/verify-service.sh` — one-shot TCP probe + listening-address check + auth + functional test (auto-detects mysql vs redis).

### 7. Resource check (run before installing anything)

Many services are PRE-INSTALLED on TencentOS / Aliyun Linux / Ubuntu cloud images. Always check first:
```bash
ssh user@host "lscpu | grep -E 'Model name|CPU\(s\)'; free -h; df -h /; cat /etc/os-release | grep PRETTY"
ssh user@host "which mysql redis-cli nginx mvn java 2>&1; dpkg -l 2>/dev/null | grep -E 'mysql|redis|nginx' | head; rpm -qa 2>/dev/null | grep -E 'mysql|redis|nginx' | head"
```

### 8. Universal pitfalls (compendium)

- **Hermes secret mask** — see § 3 above. Verify with `od -c` after every secret-write step.
- **CRLF in yml/cfg files** — Windows-cloned repos have `\r\n`; naive `sed` silently fails to match. Use Python:
  ```python
  data = re.sub(rb"(port:\s+)80(\r?\n)", rb"\g<1>8081\g<2>", open(p,'rb').read(), count=1)
  ```
- **JDBC URL with `&` in bash** — quote the whole string; single-quotes survive `&` and `%2B` best.
- **`git diff --stat` showing "all files deleted"** — when a working tree was populated by non-git means (scp, rsync), Git sees them as untracked and reports them as "deleted from the index" against `origin/master`. Verify with `diff <(git show origin/master:FILE) FILE` to compare actual contents.
- **Comment-only crontab entries (silent skip)** — a migration may leave `# 23:00 - some-job` comments in `crontab -l` but no schedule line below them. The job never fires. Run `crontab -l | grep -v '^#' | grep -v '^$'` and reconcile.

---

## A. Bare Service Deployment

Trigger: user wants to install MySQL/MariaDB, Redis, PostgreSQL, Nginx, or any other daemon that listens on a TCP port. Or says "set up remote access for X".

### Service-specific config (the bind-address gotcha)

For external reachability, the service config must bind to `0.0.0.0`, not `127.0.0.1`:

```bash
# MySQL/MariaDB — create root@% with full privs
sudo mysql -e "
CREATE USER IF NOT EXISTS 'root'@'%' IDENTIFIED BY 'password';
GRANT ALL PRIVILEGES ON *.* TO 'root'@'%' WITH GRANT OPTION;
FLUSH PRIVILEGES;"

# Redis — edit /etc/redis.conf
sudo sed -i 's/^bind 127.0.0.1$/bind 0.0.0.0/' /etc/redis.conf
sudo sed -i 's/^protected-mode yes$/protected-mode no/' /etc/redis.conf
sudo sed -i 's/^requirepass .*/requirepass newpass/' /etc/redis.conf
sudo systemctl restart redis

# PostgreSQL — listen_addresses + pg_hba.conf
sudo sed -i "s/^#listen_addresses.*/listen_addresses = '*'/" /etc/postgresql/*/main/postgresql.conf
echo "host all all 0.0.0.0/0 md5" | sudo tee -a /etc/postgresql/*/main/pg_hba.conf
sudo systemctl restart postgresql

# Nginx — usually binds 0.0.0.0 by default; just verify `listen 80` in your server block
```

### MariaDB root password reset (the socket-cleanup gotcha)

If `sudo mysql` returns "Access denied" or you need to reset the root password:

```bash
sudo systemctl stop mariadb
sudo rm -f /var/lib/mysql/mysql.sock   # CRITICAL — stale socket breaks restart
sudo pkill -9 -f mysqld                # CRITICAL — stale mysqld holds ibdata1 lock
sudo pkill -9 -f mysqld_safe
sleep 3
sudo mkdir -p /var/run/mysqld && sudo chown mysql:mysql /var/run/mysqld
sudo nohup mysqld_safe --skip-grant-tables --skip-networking > /tmp/mysqld_safe.log 2>&1 &
SAFEPID=$!
sleep 6
sudo mysql <<SQL
FLUSH PRIVILEGES;
ALTER USER 'root'@'localhost' IDENTIFIED BY 'NEW_PASSWORD';
CREATE USER IF NOT EXISTS 'root'@'%' IDENTIFIED BY 'NEW_PASSWORD';
GRANT ALL PRIVILEGES ON *.* TO 'root'@'%' WITH GRANT OPTION;
FLUSH PRIVILEGES;
SQL
sudo kill $SAFEPID 2>/dev/null
sleep 2; sudo pkill -9 -f mysqld_safe; sudo pkill -9 -f mysqld
sleep 3; sudo rm -f /var/lib/mysql/mysql.sock
sudo systemctl start mariadb
mysql -h 127.0.0.1 -uroot -pNEW_PASSWORD -e "SELECT VERSION(), user();"
```

**Failure modes:**
- "Socket file already exists" → `rm -f /var/lib/mysql/mysql.sock` was skipped
- "InnoDB: Unable to lock ./ibdata1" → leftover mysqld holds the lock; `fuser /var/lib/mysql/ibdata1` to find it
- "Please consult the Knowledge Base to find out how to run mysqld as root!" → ran `mysqld` directly; use `sudo -u mysql` or mysqld_safe

See `references/mariadb-password-reset.md` for the full recipe with the systemd restart dance.

### Verify bare service

```bash
# From your local machine (proves Layer 1 — security group):
nc -zv <server-ip> <port>

# Inside server (proves Layer 3 — bind-address):
mysql -h 127.0.0.1 -uroot -ppass -e 'SELECT 1;'
redis-cli -h 127.0.0.1 -a pass PING
sudo ss -tlnp | grep -E '3306|6379'   # must show 0.0.0.0
```

Or one-shot: `scripts/verify-service.sh <host> <port> <mysql|redis|generic> [password]`.

---

## B. Spring Boot / Java Web App

Trigger: user says "拉取并部署 … 端口 XXXX" with a Git URL and a set of env vars. Especially RuoYi 若依-derived multi-module Maven projects, but the pattern works for any Spring Boot 2.x/3.x/4.x app.

The standard loop: **private repo → SSH key auth → Maven build → fat jar → env-injected start → background daemon**.

### Step 1 — SSH access & repo deploy key

Same as § Shared Playbook § 1 and § 4. For Gitee private repos, see `references/gitee-ssh-deploy-key.md`.

### Step 2 — Clone, build, JDK match

```bash
ssh user@host 'cd ~ && git clone git@gitee.com:USER/REPO.git'
ssh user@host 'cd <repo> && grep -E "java.version|spring-boot.version" pom.xml | head -5'
```

**Always check the JDK target version in `pom.xml` before building.** Spring Boot 4.x → JDK 17. Spring Boot 3.x → JDK 17. Spring Boot 2.x → JDK 8. The server may have multiple JDKs installed — pick the matching one explicitly. For RuoYi-style multi-module projects, only `<runnable-module>` (typically `ruoyi-admin`) produces the runnable artifact:

```bash
ssh user@host 'cd <repo> && export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-17.0.13.0.11-3.tl3.x86_64 && export PATH=$JAVA_HOME/bin:$PATH && mvn -B -DskipTests -pl <runnable-module> -am package'
```

First build downloads hundreds of MB — give 5–10 min. The fat jar lands at `<runnable-module>/target/<artifactId>.jar`.

### Step 3 — Externalize secrets (READ the Hermes pitfall first)

**First — check if it's even needed.** RuoYi-style projects typically have the two key files:
- `ruoyi-admin/src/main/resources/application.yml` — Redis section (`spring.data.redis.host/port/password`)
- `ruoyi-admin/src/main/resources/application-druid.yml` — Druid `master.url/username/password`

```bash
ssh user@host 'cd <repo> && grep -n "password\|PASSWORD" \
    ruoyi-admin/src/main/resources/application.yml \
    ruoyi-admin/src/main/resources/application-druid.yml'
```

If the values are **already hardcoded** (no `${...}` placeholder), there's nothing to inject — skip the rest. Use `git show HEAD:<file>` not `cat` of the local file; a dirty working tree can lie about what's actually committed.

**If injection IS needed**, follow § Shared Playbook § 3. Default to the user-driven `read -s` approach:

```bash
# User runs this on the remote in their own SSH session:
stty -echo
read -r -p "DB password: " DBPW; echo
read -r -p "Redis password: " REDPW; echo
cat > ~/.app_env <<E
export DB_PASSWORD="$DBPW"
export REDIS_PASSWORD="$REDPW"
E
chmod 600 ~/.app_env
stty echo
```

The start script does `source ~/.app_env` at the top. See `templates/springboot-start.sh` for the canonical version.

### Step 4 — Deploy directories

```bash
ssh user@host 'sudo mkdir -p /home/<svc>/uploadPath /home/<svc>/logs /home/<svc>/temp /home/<svc>/sql
               sudo chown -R $USER:$GROUP /home/<svc>'
```

RuoYi defaults to `/home/ruoyi/{uploadPath,logs,...}`. Match what `application.yml` expects (`ruoyi.profile` / `logging.path`).

### Step 5 — Start script (template)

Use `templates/springboot-start.sh` — copy to `<repo>/start.sh`, edit the four placeholders (`PROJECT_DIR`, `MODULE_NAME`, `PROJECT_NAME`, JDK path). It:
- Sets `JAVA_HOME` to the matching JDK
- Sources `~/.app_env` for secrets
- Stops any previous instance (PID file + safety-net `pkill`)
- Launches with `nohup java -jar ...`, redirects stdout/stderr to log
- Records the new PID

**Critical flags for Spring Boot 3.x+ on JDK 17:**
```
--add-opens=java.base/java.lang=ALL-UNNAMED
--add-opens=java.base/java.lang.reflect=ALL-UNNAMED
--add-opens=java.base/java.util=ALL-UNNAMED
```
Without these you get `InaccessibleObjectException` from Hibernate/Spring internals.

### Step 6 — Verify

```bash
ssh user@host 'bash <repo>/start.sh'
sleep 25   # Spring Boot startup time
ssh user@host 'tail -50 /home/<svc>/logs/<app>.out'
ssh user@host 'ss -tlnp | grep <port>'
ssh user@host 'curl -I http://127.0.0.1:<port>'
```

Or one-shot: `scripts/springboot-diagnose.sh <host-alias> <port> [log-path]` — runs Java process check + port check + log grep + HTTP probe + JDK/mem/disk/uptime in one pass.

### Error patterns to recognize fast

| Log error | Root cause | Fix |
|---|---|---|
| `UnsupportedClassVersionError` (class file 61) | Wrong JDK; running JDK 11 against JDK 17 bytecode | Set `JAVA_HOME` to JDK 17 |
| `Access denied for user 'X'@'Y' (using password: YES)` | DB password wrong OR env var injection failed (typo, not exported) | Verify with `od -c` that the file has the real password; check start script exports the right var name |
| `Communications link failure` | DB host/port wrong, or DB firewall | Test loopback; check cloud security group on the DB port |
| `JedisConnectionException` | Redis host/port/pw wrong | Test loopback; check `redis-cli -h <host> PING` |
| `BindException: Address already in use` | Old process still running | `lsof -i :<port>` then `kill -9`; start script's `kill $PID` should handle this |
| HTTPS works but app log shows `Communications link failure` | Spring Boot started, but DB unreachable | Look up — this is NOT a Spring Boot problem |

### Case study: a real RuoYi fork deploy

`references/springboot-case-study.md` walks through the full 2026-06-15 deployment of a RuoYi v4.8.3 fork (teleSystem) to `ai-worker@82.156.225.39`, including the port-80→8081 override via Python (CRLF pitfall), the `~/.ssh/gitee_telesystem` deploy key, the `/home/ruoyi/{uploadPath,logs,...}` directory layout, and the SQL bootstrap.

### Update workflow after git push

```bash
ssh user@host 'cd <repo> && git pull'
ssh user@host 'export JAVA_HOME=... && mvn -B -DskipTests package'
ssh user@host 'bash <repo>/start.sh'   # stop + start
```

`git pull` with local edits: stash first (`git stash push -m "msg" -- <file> && git pull --rebase && git stash pop`). Resolve conflicts. After `git stash pop`, if you see `MM` in `git status -sb`, check for unresolved `<<<<<<<` markers (`grep -n '<<<\|>>>\|===' <file>`). Fastest reset to remote: `git checkout HEAD -- <file>` (discards local mods, takes remote HEAD verbatim).

---

## C. Static HTML/CSS/JS Site

Trigger: user wants to deploy landing pages, marketing sites, or vanilla SPAs — no JVM, no DB, just files behind Nginx.

### Server directory layout

```
/var/www/example.com/
├── index.html
├── styles.css
├── assets/
├── chatgpt/           # subdomain content (also accessible via /chatgpt/)
│   ├── index.html
│   └── style.css
└── aivideo/           # subdomain content (also accessible via /aivideo/)
    ├── index.html
    ├── nav.js
    ├── style.css
    └── features/, solutions/, scenes/, price/, help/
```

### Unified vs. separate deployment

When a project contains multiple related sites (main + aivideo + chatgpt), there are three patterns:

| Pattern | When to use | Nginx approach |
|---|---|---|
| **Unified** (subpaths only) | All sites share one domain | Single `server` block with `location /aivideo/` aliases |
| **Separate** (subdomains only) | Each site needs its own branding/SSL | Multiple `server` blocks, one per subdomain |
| **Dual** (both) | User wants flexibility — **default to this** | Single config with BOTH subpath aliases AND subdomain server blocks |

Most users expect `example.com/aivideo/` to work AND `aivideo.example.com` to work. Default to Dual unless explicitly told otherwise.

### Transfer — see § Shared Playbook § 5

Use local clone + rsync/scp/incremental-sync, NOT `git pull` on the server (which often hangs due to Git smart-HTTP timeout). When the server has NEWER code than GitHub, `git diff --stat` will show all files as "deleted" — verify with `diff <(git show origin/master:FILE) FILE` and push the server version to update the remote, or use the MD5-sync approach to pull changes.

### Nginx config — Dual access

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

**Critical trailing-slash pitfall**: `alias /var/www/example.com/aivideo/;` MUST have the trailing slash, otherwise subpath routes return 404. And `root /var/www/example.com/aivideo;` for a subdomain server block must point at the subdirectory itself, NOT the parent — otherwise the subdomain shows the wrong content.

Enable:
```bash
sudo ln -s /etc/nginx/sites-available/example.conf /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

### SSL with Certbot

```bash
sudo certbot --nginx -d aivideo.example.com --non-interactive --agree-tos -m admin@example.com
```

### SPA smooth navigation — the offsetWidth reflow trick

When you intercept link clicks and swap `<main>` content for a SPA-style flow, CSS transitions fail because the browser optimizes away the state change if you `add()` the class AFTER `replaceWith()`. The fix:

```javascript
// BEFORE (broken — browser batches the class add+remove, no transition):
currentMain.replaceWith(nextMain);
nextMain.classList.add("is-page-entering");
requestAnimationFrame(() => nextMain.classList.remove("is-page-entering"));

// AFTER (fixed — pre-set state, force reflow, then transition):
nextMain.classList.add("is-page-entering");   // 1. set initial state BEFORE inserting
currentMain.replaceWith(nextMain);            // 2. insert
void nextMain.offsetWidth;                    // 3. force reflow (browser records initial state)
requestAnimationFrame(() => nextMain.classList.remove("is-page-entering"));  // 4. now transition fires
```

CSS required:
```css
.video-page { opacity: 1; transform: translateY(0); transition: opacity 0.18s ease, transform 0.18s ease; }
.video-page.is-page-entering { opacity: 0; transform: translateY(12px); }
.video-page.is-page-leaving  { opacity: 0; transform: translateY(12px); }
```

A complete reusable navigation script with style sync, history API, and popstate handling is at `templates/spa-nav.js`. See `references/spa-smooth-transition.md` for the full root-cause explanation.

### Static-site verification

```bash
# Subpath routes:
curl -sL -o /dev/null -w '%{http_code}\n' -H 'Host: example.com' http://127.0.0.1/aivideo/
curl -sL -o /dev/null -w '%{http_code}\n' -H 'Host: example.com' http://127.0.0.1/chatgpt/
curl -sL -o /dev/null -w '%{http_code}\n' -H 'Host: example.com' http://127.0.0.1/

# Subdomain (from inside server, set Host header):
curl -sL -o /dev/null -w '%{http_code}\n' -H 'Host: aivideo.example.com' http://127.0.0.1/

# Manual SPA test: click between tabs, verify URL updates without full page reload,
# check opacity/transform changes in DevTools.
```

---

## User Preferences (from memory)

- Prefers step-by-step with status updates (uses `todo` tool)
- Password: user chooses; doesn't need auto-generated strong passwords
- Brand: "权权的HERMES" for any automated messages
- Email: 569545015@qq.com (QQ SMTP) — not normally used for DB setup
- Language: Chinese (中文) — respond in Chinese unless asked otherwise
- Format: concise, action-oriented; show verification output, not just "done"
- Has separate Gitee (`yanghongquan` / 毛毛在燃烧) and GitHub (`yanghq168`) accounts

## Related Skills

- `github-repo-management` — clone/setup local and remote repos
- `openclaw-to-hermes-migration` — one-shot migration of OpenClaw assets to Hermes
- `hermes-agent-skill-authoring` — authoring valid SKILL.md files
