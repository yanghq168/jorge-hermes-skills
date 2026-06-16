#!/bin/bash
# Canonical start script for a RuoYi / Spring Boot app.
# Secrets come from a 600-mode env file (~/.app_env) — never inline.
#
# First-time setup (the USER runs this on the remote host, not Hermes):
#   stty -echo
#   read -r -p "DB password: " DBPW; echo
#   read -r -p "Redis password: " REDPW; echo
#   cat > ~/.app_env <<E
#   export MYAPP_DB_PASSWORD="$DBPW"
#   export MYAPP_REDIS_PASSWORD="$REDPW"
#   E
#   chmod 600 ~/.app_env
#   stty echo

# ---- 1. JDK selection (Spring Boot 4.x / 3.x need JDK 17; 2.x needs JDK 8) ----
# Adjust path to the JDK on your server. List installed: ls /usr/lib/jvm/
export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-17.0.13.0.11-3.tl3.x86_64
export PATH=$JAVA_HOME/bin:$PATH

# ---- 2. Load secrets (skip if hardcoded in application-druid.yml) ----
[ -f "$HOME/.app_env" ] && source "$HOME/.app_env"

# ---- 3. Non-secret env (safe to hardcode / commit) ----
#    Match the placeholders in application.yml (e.g. ${MYAPP_DB_URL:...})
export MYAPP_DB_URL='jdbc:mysql://HOST:3306/DB?useUnicode=true&characterEncoding=utf8&zeroDateTimeBehavior=convertToNull&useSSL=false&serverTimezone=GMT%2B8&allowPublicKeyRetrieval=true'
export MYAPP_DB_USERNAME='DB_USER'
# MYAPP_DB_PASSWORD comes from ~/.app_env (or hardcoded in yml)

export MYAPP_REDIS_HOST='REDIS_HOST'
export MYAPP_REDIS_PORT='6379'
# MYAPP_REDIS_PASSWORD comes from ~/.app_env

export MYAPP_PROFILE='/home/MYSVC/uploadPath'
export MYAPP_LOG_PATH='/home/MYSVC/logs'

# ---- 4. Paths ----
APP_HOME=/home/ai-worker/PROJECT_DIR        # where git clone lives
APP_JAR=$APP_HOME/MODULE_NAME/target/MODULE_NAME.jar   # the fat jar
LOG_FILE=/home/MYSVC/logs/PROJECT_NAME.out
APP_PID_FILE=/home/MYSVC/logs/PROJECT_NAME.pid

mkdir -p /home/MYSVC/logs
cd "$APP_HOME" || exit 1

# ---- 5. Stop previous instance ----
if [ -f "$APP_PID_FILE" ] && kill -0 "$(cat "$APP_PID_FILE")" 2>/dev/null; then
    OLD_PID=$(cat "$APP_PID_FILE")
    echo "[stop] stopping pid=$OLD_PID"
    kill "$OLD_PID"
    sleep 3
    kill -0 "$OLD_PID" 2>/dev/null && kill -9 "$OLD_PID"
fi
# Safety net: kill any orphan
pkill -9 -f "$APP_JAR" 2>/dev/null

# ---- 6. Launch in background ----
echo "[start] starting on port 8080 ..."
nohup java -jar -Dfile.encoding=UTF-8 \
    --add-opens=java.base/java.lang=ALL-UNNAMED \
    --add-opens=java.base/java.lang.reflect=ALL-UNNAMED \
    --add-opens=java.base/java.util=ALL-UNNAMED \
    -Xms512m -Xmx1024m \
    "$APP_JAR" \
    --spring.profiles.active=druid \
    > "$LOG_FILE" 2>&1 &

NEW_PID=$!
echo "$NEW_PID" > "$APP_PID_FILE"
echo "[ok] pid=$NEW_PID  log=$LOG_FILE"
echo "[hint] tail -f $LOG_FILE  |  kill \$(cat $APP_PID_FILE)"

# Placeholders to substitute before use:
#   PROJECT_DIR    — directory created by `git clone` (e.g. teleSystem)
#   MODULE_NAME    — Maven runnable module artifactId (e.g. ruoyi-admin)
#   PROJECT_NAME   — short slug for log/pid filename (e.g. teleSystem)
#   MYSVC          — Linux user/group owning /home/MYSVC (e.g. ruoyi)
#   HOST / DB / DB_USER / REDIS_HOST — your actual DB/Redis endpoints
