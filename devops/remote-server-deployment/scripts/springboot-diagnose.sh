#!/bin/bash
# springboot-diagnose.sh — one-shot post-deploy health check for Spring Boot apps
# Usage:  ./springboot-diagnose.sh <host-alias> <port> [log-path]
# Example: ./springboot-diagnose.sh jorge-remote 8081 /home/ruoyi/logs/teleSystem.out

set -u
HOST="${1:?usage: $0 <host-alias> <port> [log-path]}"
PORT="${2:?usage: $0 <host-alias> <port> [log-path]}"
LOG="${3:-/home/ruoyi/logs/app.out}"

echo "=== [1/5] Java process ==="
ssh "$HOST" "ps -ef | grep -v grep | grep -E 'ruoyi|java -jar' | head -5" || echo "  (no java process found)"

echo
echo "=== [2/5] Port $PORT listening? ==="
ssh "$HOST" "(ss -tlnp 2>/dev/null || netstat -tlnp 2>/dev/null) | grep \":$PORT \" || echo '  PORT NOT LISTENING'"

echo
echo "=== [3/5] Last 25 log lines (looking for ERROR / Exception / Started) ==="
ssh "$HOST" "tail -25 $LOG 2>/dev/null | grep -E 'ERROR|Exception|Started|Started RuoyiApplication|Tomcat started|FATAL' | head -10"

echo
echo "=== [4/5] HTTP probe ==="
ssh "$HOST" "curl -sS -o /dev/null -w '  http_code=%{http_code}  time=%{time_total}s\n' --max-time 5 http://127.0.0.1:$PORT/ 2>&1"

echo
echo "=== [5/5] Quick checks ==="
ssh "$HOST" "echo '  jdk=' \$(/usr/lib/jvm/java-17-openjdk-17.0.13.0.11-3.tl3.x86_64/bin/java -version 2>&1 | head -1) && \
  echo '  mem_free=' \$(free -m | awk '/Mem:/ {print \$7}')MB && \
  echo '  disk_free=' \$(df -BG /home | awk 'NR==2 {print \$4}') && \
  echo '  uptime=' \$(uptime -p)"

echo
echo "=== If you see issues ==="
echo "  - Port not listening + 'Class file version 61' → wrong JDK, set JAVA_HOME to JDK 17"
echo "  - Port not listening + 'Access denied' in log → DB password wrong (see hermes-secret-mask-pitfall.md)"
echo "  - Port not listening + 'Connection refused' to DB/Redis → firewall or wrong host/port"
echo "  - 200 OK but errors in log → app is up, specific request failed (check log)"
echo "  - Public IP fails but 127.0.0.1 works → cloud security group blocks the port"
