#!/bin/bash
# verify-service.sh — Check that a service is installed, listening, and accepting auth.
# Usage: ./verify-service.sh <host> <port> <type> [password]
# Example: ./verify-service.sh 82.156.225.39 3306 mysql <db-password>
#          ./verify-service.sh 82.156.225.39 6379 redis <redis-password>

set -e

HOST="${1:?Usage: $0 <host> <port> <mysql|redis|generic> [password]}"
PORT="${2:?Need port}"
TYPE="${3:?Need type: mysql|redis|generic}"
PASSWORD="${4:-}"

echo "=== Verify $TYPE on $HOST:$PORT ==="

# 1. TCP reachable from THIS host
echo "[1] TCP probe from local..."
if timeout 3 bash -c "</dev/tcp/$HOST/$PORT" 2>/dev/null; then
    echo "    ✓ TCP $PORT reachable from here"
else
    echo "    ✗ TCP $PORT NOT reachable (check: server up? security group? firewall?)"
    exit 1
fi

# 2. Service is listening on 0.0.0.0 (not just 127.0.0.1)
echo "[2] Listening address on server..."
LISTEN=$(ssh -i ~/.ssh/jorge_server "ai-worker@$HOST" "sudo ss -tlnp | grep :$PORT" 2>/dev/null || echo "  SSH failed")
if echo "$LISTEN" | grep -q "0.0.0.0:$PORT\|\\*:$PORT"; then
    echo "    ✓ Listening on 0.0.0.0:$PORT"
elif echo "$LISTEN" | grep -q "127.0.0.1:$PORT"; then
    echo "    ✗ Bound to 127.0.0.1 only — edit config to bind 0.0.0.0"
    exit 1
else
    echo "    ? $LISTEN"
fi

# 3. Auth + functional test
echo "[3] Auth test..."
case "$TYPE" in
    mysql)
        if command -v mysql >/dev/null 2>&1; then
            mysql -h "$HOST" -P "$PORT" -uroot -p"$PASSWORD" \
                -e "SELECT VERSION() AS version, user() AS as_user;" 2>&1 | head -5
        else
            echo "    (mysql client not installed locally — skipping functional test)"
            echo "    Install with: sudo apt install default-mysql-client"
        fi
        ;;
    redis)
        if command -v redis-cli >/dev/null 2>&1; then
            redis-cli -h "$HOST" -p "$PORT" -a "$PASSWORD" PING 2>&1 | grep -v Warning
            redis-cli -h "$HOST" -p "$PORT" -a "$PASSWORD" \
                SET verify:test "ok-$(date +%s)" EX 30 2>&1 | grep -v Warning
            redis-cli -h "$HOST" -p "$PORT" -a "$PASSWORD" GET verify:test 2>&1 | grep -v Warning
        else
            echo "    (redis-cli not installed locally — skipping functional test)"
            echo "    Install with: sudo apt install redis-tools"
        fi
        ;;
    generic)
        echo "    TCP only — no protocol test"
        ;;
    *)
        echo "    Unknown type: $TYPE"
        exit 1
        ;;
esac

echo "=== Done ==="
