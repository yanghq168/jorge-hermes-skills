# Tencent Cloud CVM — Security Group / Firewall Notes

## Three-Layer Model on Tencent Cloud CVM

```
[Client]
   ↓
┌─────────────────────────────────┐
│ Tencent Cloud Security Group    │  ← Layer 1: cloud console only
│ (控制台 → 安全组 → 入站规则)      │
└─────────────────────────────────┘
   ↓
┌─────────────────────────────────┐
│ Host iptables / firewalld        │  ← Layer 2: inside VM, sudo
│ (YJ-FIREWALL-INPUT chain present│
│  + ipset YJ-GLOBAL-INBLOCK for  │
│  Tencent's known-bad-IP list)    │
└─────────────────────────────────┘
   ↓
┌─────────────────────────────────┐
│ Service bind-address             │  ← Layer 3: redis.conf, my.cnf, etc.
└─────────────────────────────────┘
   ↓
[Service]
```

**Layer 1 is OUTSIDE the VM. The agent has NO way to modify it from inside.**

## Diagnosing Which Layer is Blocking

```bash
# From your LOCAL machine (NOT the server):
nc -zv <server-ip> 22        # if fails → server unreachable, not firewall
nc -zv <server-ip> 3306      # if 22 works but 3306 fails → Layer 1 (security group)
```

```bash
# From INSIDE the server, verify layers 2 & 3:
sudo iptables -L INPUT -n -v --line-numbers | head -30
sudo firewall-cmd --list-ports   # usually 'not running' on TencentOS
sudo ss -tlnp | grep <port>      # must show 0.0.0.0:<port>
```

If layer 3 is `127.0.0.1:<port>` only → service isn't bound to external. Fix config.
If layer 3 is `0.0.0.0:<port>` but external still fails → layer 1.

## Tencent Cloud Console Path

1. https://console.cloud.tencent.com/cvm → Instances
2. Click instance ID (e.g. `ins-jnoozcsv`)
3. Right sidebar → **Security groups** tab → click the group
4. **Inbound rules** → **Add rule**:
   - Type: `Custom` or `MySQL (3306)` / `Redis (6379)` from dropdown
   - Source: `0.0.0.0/0` (open) or `<your-ip>/32` (restricted — safer)
   - Protocol: TCP, Port: 3306
   - Policy: Allow
5. **Apply now** (sometimes a separate button)

## Tencent Server Identification

```bash
# From inside the server:
curl -s http://100.100.100.200/latest/meta-data/instance-id
# → ins-jnoozcsv (or similar)

curl -s http://100.100.100.200/latest/meta-data/uin
# → Tencent account UIN

curl -s http://100.100.100.200/latest/meta-data/local-ipv4
# → 10.0.x.x (private IP)
```

## Tencent Pre-installed YJ Rules

TencentOS / some CVM images ship with a pre-loaded ipset:
- `YJ-GLOBAL-INBLOCK` (hash:ip, ~11000 entries) — Tencent's blocklist of known-bad IPs
- `YJ-FIREWALL-INPUT` chain — auto-populated from the ipset

**Don't fight these.** They are correct. The issue is almost always the security group.

## Common Mistakes

- ❌ Editing `/etc/iptables.rules` or running `iptables -F` (flush) — wipes Tencent's rules, may lock you out
- ❌ Assuming `firewall-cmd` is the firewall (it's not running on TencentOS by default)
- ❌ Restarting the service 5 times hoping it'll work (it won't — security group is external)
- ✅ Tell the user clearly: "服务都配好了，差最后一步去控制台放行安全组"
