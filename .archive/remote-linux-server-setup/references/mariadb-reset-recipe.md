# MariaDB 10.3 Root Password Reset — Copy-Paste Recipe

Use when: `sudo mysql` fails with "Access denied", or you need to reset root password on a CVM.

## Why `sudo mysql` Sometimes Fails

On RHEL8 / TencentOS, MariaDB may be configured with:
- `unix_socket` auth for root@localhost (then `sudo mysql` works directly)
- OR a pre-set root password (then `sudo mysql` fails — you need the password)

If `sudo mysql` returns "Access denied (using password: NO)", root has a password OR auth_socket is misconfigured. Use the reset recipe below.

## Reset Recipe (Server: ai-worker@82.156.225.39, passwordless sudo assumed)

```bash
REMOTE="ssh -i ~/.ssh/jorge_server ai-worker@82.156.225.39"

$REMOTE 'bash -s' <<'REMOTE_SCRIPT'
# 1. Stop service cleanly
sudo systemctl stop mariadb

# 2. CRITICAL cleanup — both of these will block restart if not removed
sudo rm -f /var/lib/mysql/mysql.sock
sudo pkill -9 -f mysqld 2>/dev/null
sudo pkill -9 -f mysqld_safe 2>/dev/null
sleep 3

# 3. Start in skip-grant-tables mode (no auth, no network)
sudo mkdir -p /var/run/mysqld
sudo chown mysql:mysql /var/run/mysqld
sudo nohup mysqld_safe --skip-grant-tables --skip-networking > /tmp/mysqld_safe.log 2>&1 &
SAFEPID=$!
sleep 6

# 4. Reset password (now no auth required)
sudo mysql <<SQL
FLUSH PRIVILEGES;
ALTER USER 'root'@'localhost' IDENTIFIED BY 'NEW_PASSWORD_HERE';
CREATE USER IF NOT EXISTS 'root'@'%' IDENTIFIED BY 'NEW_PASSWORD_HERE';
GRANT ALL PRIVILEGES ON *.* TO 'root'@'%' WITH GRANT OPTION;
FLUSH PRIVILEGES;
SELECT user, host FROM mysql.user WHERE user='root';
SQL

# 5. Kill safe mode, start fresh
sudo kill $SAFEPID 2>/dev/null
sleep 2
sudo pkill -9 -f mysqld_safe 2>/dev/null
sudo pkill -9 -f mysqld 2>/dev/null
sleep 3
sudo rm -f /var/lib/mysql/mysql.sock

# 6. Start via systemd
sudo systemctl start mariadb
sleep 3
sudo systemctl is-active mariadb
sudo ss -tlnp | grep 3306

# 7. Verify
mysql -h 127.0.0.1 -uroot -pNEW_PASSWORD_HERE -e "SELECT VERSION(), user();"
REMOTE_SCRIPT
```

## Failure Modes

### "Socket file already exists"
- Cause: `rm -f /var/lib/mysql/mysql.sock` was skipped, or mysqld_safe didn't clean up
- Fix: `sudo rm -f /var/lib/mysql/mysql.sock && sudo systemctl start mariadb`

### "InnoDB: Unable to lock ./ibdata1"
- Cause: a leftover mysqld process still has the file lock
- Fix: `sudo pkill -9 -f mysqld` then retry. `fuser /var/lib/mysql/ibdata1` shows which PID holds it.

### "Got error 'Could not get an exclusive lock' on aria_log_control"
- Same root cause as InnoDB lock — kill stale processes

### systemctl start returns "code=exited status=1/FAILURE"
- Check `sudo journalctl -xeu mariadb -n 30 --no-pager` for actual error
- Check `sudo tail -40 /var/log/mariadb/mariadb.log`

### "Please consult the Knowledge Base to find out how to run mysqld as root!"
- Cause: ran `mysqld` directly without `--user=mysql`
- Fix: use `sudo -u mysql /usr/libexec/mysqld ...` or use mysqld_safe

## Verify Reset Worked

```bash
# Loopback TCP test (proves password is set, not unix_socket only)
mysql -h 127.0.0.1 -uroot -pPASSWORD -e "SELECT VERSION();"

# Show all root users
mysql -h 127.0.0.1 -uroot -pPASSWORD -e "SELECT user, host, plugin FROM mysql.user WHERE user='root';"

# Expect to see:
#   root | %         | (mysql_native_password or similar)
#   root | localhost | ...
#   root | 127.0.0.1 | ...
#   root | ::1       | ...
```
