---
name: remote-linux-server-setup
description: Deploy and configure services (MySQL/MariaDB, Redis, PostgreSQL, Nginx, etc.) on a remote Linux server (especially Tencent Cloud CVM / Aliyun ECS / AWS EC2) with key-based SSH access and passwordless sudo. Covers the three-layer firewall model (cloud security group → host iptables/firewalld → service bind-address), MariaDB skip-grant-tables cleanup pitfalls, and verification recipe.
---

# Remote Linux Server Setup

When the user says "set up X on my server" / "我服务器上装个 Y" / "configure remote access for Z" — for any service that needs to be reachable from outside the host.

## Trigger Conditions

- User wants to install/configure a service on their remote cloud server
- "Configure remote access" / "远程访问" / "外部能连"
- SSH key-based login to a Tencent Cloud CVM, Aliyun ECS, AWS EC2, or similar
- Tasks involving port changes, bind-address, security groups

## Three-Layer Firewall Model (CRITICAL)

Cloud VMs have THREE independent layers that all must allow the port. **Diagnose from outside in**:

1. **Cloud security group** (腾讯云安全组 / Aliyun 安全组 / AWS SG) — the OUTERMOST layer. If this blocks, NO traffic reaches the host. **Cannot be controlled from inside the VM.** The agent MUST tell the user to add an inbound rule in the cloud console.
2. **Host iptables / firewalld** — server-side OS firewall. Check with `sudo iptables -L INPUT -n` and `sudo firewall-cmd --list-ports`.
3. **Service bind-address** — the service config (e.g. `bind 127.0.0.1` in redis.conf, `bind-address` in my.cnf). Must be `0.0.0.0` (or specific IP) for external access.

**Diagnostic recipe when "port not reachable from outside":**
```bash
# From a separate host (e.g. local machine):
nc -zv <server-ip> <port>          # or: timeout 3 bash -c '</dev/tcp/<ip>/<port>'

# If fails but SSH (22) works → it's the CLOUD SECURITY GROUP, not host firewall
# Then check service is even listening on 0.0.0.0:
ssh server 'sudo ss -tlnp | grep <port>'

# Identify the cloud provider by metadata service:
curl -s http://100.100.100.200/latest/meta-data/instance-id  # Tencent
curl -s http://100.100.100.200/latest/meta-data/uin          # Tencent account
```

**Communicate this clearly to the user**: "服务都配好了，22 通说明机器可达；3306/6379 不通但服务器内端口在监听 — 是云厂商安全组的事，需要你去控制台放行。"

## Standard Workflow

### 1. SSH Access (key-based with passwordless sudo)

User's setup (memory): `ssh -i ~/.ssh/jorge_server ai-worker@82.156.225.39` — key-based, sudo NOPASSWD.

```bash
REMOTE="ssh -i ~/.ssh/jorge_server ai-worker@82.156.225.39"
$REMOTE "whoami; sudo -n whoami"  # verify both work
```

If SSH fails with "Permission denied" → key may be missing or user changed it. Ask user to confirm before guessing.

### 2. Resource Check (before installing anything)

```bash
$REMOTE "lscpu | grep -E 'Model name|CPU\(s\)'; free -h; df -h /; cat /etc/os-release | grep PRETTY"
```

Many services are PRE-INSTALLED on TencentOS / Aliyun Linux / Ubuntu cloud images. Always check `which`/`dpkg -l`/`rpm -qa` before installing.

### 3. Service Configuration (MySQL/MariaDB example)

**MariaDB root password reset gotcha** (Pitfall): if `mysql` command without `-p` fails with "Access denied", root may already have a password OR uses `unix_socket` auth. To reset:
```bash
sudo systemctl stop mariadb
sudo rm -f /var/lib/mysql/mysql.sock  # CRITICAL — stale socket breaks restart
sudo pkill -9 -f mysqld              # CRITICAL — stale mysqld holds ibdata1 lock
sleep 3
sudo mysqld_safe --skip-grant-tables --skip-networking &
sleep 5
sudo mysql -e "FLUSH PRIVILEGES; ALTER USER 'root'@'localhost' IDENTIFIED BY 'newpass';"
# Then kill safe mode, start systemctl fresh:
sudo kill $SAFEPID 2>/dev/null
sleep 3
sudo pkill -9 -f mysqld_safe
sudo systemctl start mariadb
```

If `systemctl start` fails with "Socket file exists" — the socket wasn't cleaned. Always `rm -f` before restart.

### 4. Remote Access Setup

```bash
# MySQL: create root@% user with all privs
sudo mysql -e "
CREATE USER IF NOT EXISTS 'root'@'%' IDENTIFIED BY 'password';
GRANT ALL PRIVILEGES ON *.* TO 'root'@'%' WITH GRANT OPTION;
FLUSH PRIVILEGES;"

# Redis: edit /etc/redis.conf
sudo sed -i 's/^bind 127.0.0.1$/bind 0.0.0.0/' /etc/redis.conf
sudo sed -i 's/^protected-mode yes$/protected-mode no/' /etc/redis.conf
sudo sed -i 's/^requirepass .*/requirepass newpass/' /etc/redis.conf
sudo systemctl restart redis
```

### 5. Verification

Verify from INSIDE the server (TCP loopback):
```bash
mysql -h 127.0.0.1 -uroot -ppass -e 'SELECT 1;'
redis-cli -h 127.0.0.1 -a pass PING
sudo ss -tlnp | grep -E '3306|6379'  # must show 0.0.0.0
```

Verify from OUTSIDE requires the user to add the security group rule first. Don't waste time on this until they confirm.

## User Preferences (from memory)

- Prefers step-by-step with status updates (uses `todo` tool)
- Password: user chooses; doesn't need auto-generated strong passwords
- Brand: "权权的HERMES" for any automated messages
- Email: 569545015@qq.com (QQ SMTP) — but DB setup doesn't normally email
- Language: Chinese (中文) — respond in Chinese unless asked otherwise
- Format: concise, action-oriented; show verification output, not just "done"

## Files in This Skill

- `references/tencent-cvm-firewall.md` — detailed cloud security group notes, screenshots, console URL paths
- `references/mariadb-reset-recipe.md` — copy-pasteable password reset script
- `scripts/verify-service.sh` — quick TCP/listening/auth check for any port
