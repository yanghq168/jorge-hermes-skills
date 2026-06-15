# teleSystem Deployment Recipe

Server: `ai-worker@82.156.225.39` (Tencent Cloud CVM, user has passwordless sudo).
Stack: RuoYi v4.8.3 fork with patrol module, Spring Boot 4.0.6 + JDK 17, MySQL + Redis on same host.
Gitee repo: `https://gitee.com/yanghongquan/teleSystem` (user: 毛毛在燃烧).

## Architecture (from deployment on 2026-06-15)

```
┌──────────────────────────────────────────────┐
│  ai-worker@82.156.225.39                     │
│  ├─ /home/ai-worker/teleSystem/              │
│  │   └─ ruoyi-admin/target/ruoyi-admin.jar   │
│  ├─ /home/ruoyi/uploadPath  (file uploads)   │
│  ├─ /home/ruoyi/logs/                        │
│  │   └─ teleSystem.out  (nohup stdout)       │
│  └─ java -jar  (port 8081, profile druid)    │
│                                                │
│  82.156.225.39:3306  MySQL  (DB: teleSystem)  │
│  82.156.225.39:6379  Redis  (auth: yes)       │
└──────────────────────────────────────────────┘
```

## Step 1: SSH Access & Key Setup

The local `~/.ssh/jorge_server` key is **not** in `yanghongquan`'s Gitee SSH keys. Generate a dedicated deploy key on the server:

```bash
ssh jorge-remote 'test -f ~/.ssh/gitee_telesystem || ssh-keygen -t ed25519 \
  -C "ai-worker@82.156.225.39-for-gitee-telesystem" \
  -f ~/.ssh/gitee_telesystem -N ""'
ssh jorge-remote 'cat ~/.ssh/gitee_telesystem.pub'   # user adds to Gitee → 设置 → SSH公钥
```

After user confirms key is added on Gitee:

```bash
# Append host config on server
ssh jorge-remote 'cat >> ~/.ssh/config << EOF
Host gitee.com
    HostName gitee.com
    User git
    IdentityFile ~/.ssh/gitee_telesystem
    StrictHostKeyChecking accept-new
EOF'

# Verify auth
ssh jorge-remote 'ssh -T git@gitee.com 2>&1 | head -1'
# Expected: Hi 毛毛在燃烧(@yanghongquan)! You've successfully authenticated, but GITEE.COM does not provide shell access.
```

## Step 2: Clone & Build

```bash
ssh jorge-remote 'cd /home/ai-worker && git clone git@gitee.com:yanghongquan/teleSystem.git'
# Build (Spring Boot 4.0.6 needs JDK 17; verify mvn reports 17)
ssh jorge-remote 'mvn -B -DskipTests -f /home/ai-worker/teleSystem/pom.xml clean package'
# Output jar: /home/ai-worker/teleSystem/ruoyi-admin/target/ruoyi-admin.jar  (~102 MB)
```

## Step 3: Create /home/ruoyi Directories

```bash
ssh jorge-remote 'sudo mkdir -p /home/ruoyi/{uploadPath,logs,sql,temp} && sudo chown -R ai-worker:ai-worker /home/ruoyi'
```

## Step 4: Override Default Port (80 → 8081)

The upstream `application.yml` is CRLF (Windows) — naive `sed` will fail. Use Python:

```bash
ssh jorge-remote 'python3 -c "
import re
p = \"/home/ai-worker/teleSystem/ruoyi-admin/src/main/resources/application.yml\"
with open(p, \"rb\") as f: data = f.read()
new = re.sub(rb\"(port:\s+)80(\r?\n)\", rb\"\g<1>8081\g<2>\", data, count=1)
with open(p, \"wb\") as f: f.write(new)
print(\"ok\")
"'
ssh jorge-remote 'grep -n "port: 8081" /home/ai-worker/teleSystem/ruoyi-admin/src/main/resources/application.yml'
```

After port change, **rebuild**:
```bash
ssh jorge-remote 'mvn -B -DskipTests -f /home/ai-worker/teleSystem/pom.xml package'
```

## Step 5: Verify Database Exists & Has Tables

```bash
ssh jorge-remote 'mysql -h 82.156.225.39 -P 3306 -u system -p<pw> -e "SHOW DATABASES LIKE \"teleSystem\";"'
ssh jorge-remote 'mysql -h 82.156.225.39 -P 3306 -u system -p<pw> -D teleSystem -e "SHOW TABLES;" | wc -l'
# Expected: ~30+ tables including sys_*, gen_*, QRTZ_*, sms_patrol_*
```

If DB is empty, initialize from `/home/ai-worker/teleSystem/sql/`:
```bash
ssh jorge-remote 'mysql -h 82.156.225.39 -P 3306 -u system -p<pw> teleSystem \
  < /home/ai-worker/teleSystem/sql/ry_*.sql \
    /home/ai-worker/teleSystem/sql/quartz.sql \
    /home/ai-worker/teleSystem/sql/teleSystem_base.sql \
    /home/ai-worker/teleSystem/sql/teleSystem_patrol.sql \
    /home/ai-worker/teleSystem/sql/teleSystem_seed.sql'
```

## Step 6: Create Start Script (CRITICAL — see sensitive-string-mask.md)

**Cannot** use `cat > start.sh << EOF` with literal password in the heredoc — the mask corrupts the file. Use the `read -s` interactive approach or base64 round-trip. Template:

```bash
#!/bin/bash
# /home/ai-worker/teleSystem/start.sh
export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-17.0.13.0.11-3.tl3.x86_64
export PATH=$JAVA_HOME/bin:$PATH

export TELESYSTEM_DB_URL="jdbc:mysql://82.156.225.39:3306/teleSystem?useUnicode=true&characterEncoding=utf8&zeroDateTimeBehavior=convertToNull&useSSL=false&serverTimezone=GMT%2B8&allowPublicKeyRetrieval=true"
export TELESYSTEM_DB_USERNAME="system"
export TELESYSTEM_DB_PASSWORD="<DB_PW>"

export TELESYSTEM_REDIS_HOST="82.156.225.39"
export TELESYSTEM_REDIS_PORT="6379"
export TELESYSTEM_REDIS_PASSWORD="<REDIS_PW>"

export TELESYSTEM_PROFILE="/home/ruoyi/uploadPath"
export TELESYSTEM_LOG_PATH="/home/ruoyi/logs"

APP_HOME=/home/ai-worker/teleSystem
APP_JAR=$APP_HOME/ruoyi-admin/target/ruoyi-admin.jar
LOG_FILE=/home/ruoyi/logs/teleSystem.out

mkdir -p /home/ruoyi/logs
cd $APP_HOME

# Stop existing
PID=$(ps -ef | grep -v grep | grep "ruoyi-admin.jar" | awk '{print $2}')
if [ -n "$PID" ]; then
    echo "[stop] stopping pid=$PID"
    kill $PID 2>/dev/null
    sleep 3
fi

# Start
nohup java -jar -Dfile.encoding=UTF-8 \
    --add-opens=java.base/java.lang=ALL-UNNAMED \
    --add-opens=java.base/java.lang.reflect=ALL-UNNAMED \
    --add-opens=java.base/java.util=ALL-UNNAMED \
    -Xms512m -Xmx1024m \
    $APP_JAR \
    --spring.profiles.active=druid \
    > $LOG_FILE 2>&1 &

echo "[ok] pid=$!  log: $LOG_FILE"
```

Generate via:
```bash
ssh jorge-remote 'cat > /tmp/set_pw.sh << "OUTER"
#!/bin/bash
read -s -p "DB password: " DB_PW; echo
read -s -p "Redis password: " REDIS_PW; echo
# (write the script above with python, substituting $DB_PW and $REDIS_PW)
OUTER
chmod +x /tmp/set_pw.sh'
```

## Step 7: Verify Startup

```bash
ssh jorge-remote 'bash /home/ai-worker/teleSystem/start.sh'
sleep 30

# Check process
ssh jorge-remote 'ps -ef | grep -v grep | grep ruoyi-admin.jar'
# Check port
ssh jorge-remote 'ss -tlnp | grep 8081'
# Check logs (last 30 lines, look for "Started ... in X seconds" or any error)
ssh jorge-remote 'tail -30 /home/ruoyi/logs/teleSystem.out'
# Smoke test endpoint
ssh jorge-remote 'curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8081/login'
# Expected: 200
```

## Common Failures (from this session)

| Symptom in log | Cause | Fix |
|---|---|---|
| `UnsupportedClassVersionError: class file version 61.0, ... up to 55.0` | Spring Boot 4.0.6 needs JDK 17, but `java` ran on JDK 11 | Set `JAVA_HOME` to JDK 17 in start script |
| `Access denied for user 'system'@'82.156.225.39' (using password: YES)` | The DB password in start script got masked to `***` during file write | Use `read -s` interactive or base64 round-trip; verify with `od -c` |
| `redis.clients.jedis.exceptions.JedisDataException: NOAUTH Authentication required.` | Redis password masked to `***` | Same as above |

## Project Defaults (RuoYi v4.8.3)

- Default admin login: `admin / admin123`
- Druid console: `http://host:8081/druid/` (login: `ruoyi / 123456`)
- API docs (springdoc): `http://host:8081/swagger-ui.html`
- Default `ruoyi.profile` (upload path) honors `TELESYSTEM_PROFILE` env var
- `spring.profiles.active=druid` enables the `application-druid.yml` data source config

## Update Workflow

```bash
ssh jorge-remote 'cd /home/ai-worker/teleSystem && git pull'
ssh jorge-remote 'mvn -B -DskipTests clean package'
ssh jorge-remote 'bash /home/ai-worker/teleSystem/start.sh'  # stop + start
```

## Notes

- The repo's `ry.sh` is the upstream RuoYi start script (Windows-style); ignore it, use the template above.
- The `bin/` and `dir/` directories in the repo are empty; ignore.
- `ruoyi-patrol` module adds the SMS patrol business tables (`sms_patrol_*`).
