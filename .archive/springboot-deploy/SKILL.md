---
name: springboot-deploy
description: Deploy a Java/Spring Boot web application (especially RuoYi 若依-derived multi-module Maven projects) from a private Git host (Gitee/GitHub) to a remote Linux server via SSH, build the fat jar, inject externalized secrets, and start the service in the background. Use when the user says "拉取并部署" / "pull and deploy" / "部署这个Java项目" / gives a Git URL + DB/Redis env vars + a port.
---

# Spring Boot Deploy (private repo → remote Linux)

The standard loop is: **private repo → SSH key auth → Maven build → fat jar → env-injected start → background daemon**. RuoYi 若依 projects dominate this class for this user, but the pattern works for any Spring Boot 2.x/3.x/4.x app.

## When to use this skill
- User says "拉取并部署 … 端口 XXXX" with a Git URL and a set of env vars
- Private repo at gitee.com / github.com that needs SSH deploy key
- Output is a long-running web service on a specific port
- DB/Redis live on the same or a different machine, passed as env vars

## 1. SSH access check (do this FIRST)
```bash
# 1a) Local key exists?
ls ~/.ssh/ | grep -E '\.pub$'

# 1b) Remote reachable with that key?
ssh -o BatchMode=yes -i ~/.ssh/<key> user@host 'echo ok'

# 1c) If permission denied — key not in remote authorized_keys.
#     Diagnose:
ssh -v -i ~/.ssh/<key> user@host 'echo ok' 2>&1 | grep -E 'authenticated|denied'
```

Common gotcha: a key named e.g. `jorge_server` exists locally but is NOT in the remote user's `authorized_keys`. SSH will silently try and fail. Test with `BatchMode=yes` to fail fast.

## 2. Private repo auth — generate a dedicated deploy key

Do NOT reuse the user's personal SSH key. Generate one per remote machine × per repo family:

```bash
# On the REMOTE server
ssh user@host 'test -f ~/.ssh/<scope> || ssh-keygen -t ed25519 \
    -C "user@host-for-<scope>" -f ~/.ssh/<scope> -N ""'

# Print the public key for the user to paste into the Git host
ssh user@host 'cat ~/.ssh/<scope>.pub'
```

Then **ask the user to paste the pubkey into the Git host**:
- Gitee: https://gitee.com/<user> → 头像 → 设置 → SSH公钥 → 标题随意 + 公钥字符串
- GitHub: https://github.com/settings/keys → New SSH key

Configure the remote `~/.ssh/config` so `git clone` uses the right key:
```bash
Host gitee.com
    HostName gitee.com
    User git
    IdentityFile ~/.ssh/<scope>
    StrictHostKeyChecking accept-new
```

Verify: `ssh -T git@gitee.com` should print `Hi <user>!...`.

## 3. Clone, build, sanity-check the project

```bash
ssh user@host 'cd ~ && git clone <git-url>'           # e.g. git@gitee.com:yanghongquan/teleSystem.git
ssh user@host 'cd <repo> && find . -name "pom.xml" | head -3'
ssh user@host 'grep -E "java.version|spring-boot.version" <repo>/pom.xml | head -5'
```

**Always check the JDK target version in `pom.xml` before building.** Spring Boot 4.x → JDK 17. Spring Boot 3.x → JDK 17. Spring Boot 2.x → JDK 8. The server may have multiple JDKs installed; pick the matching one before `mvn` (see step 5).

## 4. Verify external services are reachable (BEFORE compiling)
```bash
# MySQL
mysql -h <host> -P 3306 -u <user> -p<pw> -e 'SHOW DATABASES LIKE "<db>";'

# Redis
redis-cli -h <host> -p 6379 -a <pw> --no-auth-warning ping
```

If DB exists but tables are missing, the project usually ships an `sql/` folder — import it BEFORE starting the app.

## 5. Build the fat jar

RuoYi-style multi-module projects: only `ruoyi-admin` is the runnable module.
```bash
ssh user@host 'cd <repo> && mvn -B -DskipTests -pl <runnable-module> -am package'
```

First build downloads hundreds of MB — give 5–10 min. The fat jar lands at `<runnable-module>/target/<artifactId>.jar`.

## 6. Create deploy directories (often needs sudo)
```bash
ssh user@host 'sudo mkdir -p /home/<svc>/uploadPath /home/<svc>/logs /home/<svc>/temp /home/<svc>/sql
               sudo chown -R $USER:$GROUP /home/<svc>'
```
RuoYi defaults to `/home/ruoyi/{uploadPath,logs,...}`. Match what `application.yml` expects (`ruoyi.profile` / `logging.path`).

## 7. Externalize secrets — READ THE PITFALL

**Hermes masks secret strings in tool output.** Anything that looks like a password/token in a `cat << EOF`, `echo`, `python f-string`, or even `base64` command gets rewritten to `***` BEFORE the command reaches the remote. **The `***` is what actually lands on disk** — not the real password. This has burned me 3+ times.

How to verify what actually got written:
```bash
ssh user@host 'grep "PASSWORD" /path/to/script | od -c | head -3'
```
`od -c` shows raw bytes, bypassing the output filter. If you see `* * *` you got burned.

### Before you start the secret-injection dance — check if it's needed

**Always grep the project config first.** For RuoYi-style projects the two files to check are:
- `ruoyi-admin/src/main/resources/application.yml` — Redis section (`spring.data.redis.host/port/password`)
- `ruoyi-admin/src/main/resources/application-druid.yml` — Druid `master.url/username/password`

```bash
ssh user@host 'cd <repo> && grep -n "password\|PASSWORD" \
    ruoyi-admin/src/main/resources/application.yml \
    ruoyi-admin/src/main/resources/application-druid.yml'
```

If the values are **already hardcoded** (no `${...}` placeholder), there's nothing to inject — skip the rest of this section entirely. **Use `git show HEAD:<file>` not `cat` of the local file** — a dirty working tree can lie about what's actually committed.

RuoYi projects also typically use a project-specific env-var prefix (e.g. `TELESYSTEM_*` for a project named teleSystem, not the default `RUOYI_*`). The placeholder syntax is `${TELESYSTEM_DB_PASSWORD:default-value}`. If the default-value side has the real password, the project source already has it.

### Fix: when injection IS needed, never put plaintext secrets in a command

Two escape routes that actually work:
1. **Have the user run the secret-write step themselves** with `read -s`:
   ```bash
   ssh user@host
   stty -echo; read -r -p "DB PW: " PW; echo
   printf 'export MY_SECRET="%s"\n' "$PW" > ~/.my_app_env
   chmod 600 ~/.my_app_env
   stty echo
   ```
2. **Hardcode the secret in the project source** (e.g. `application-druid.yml`) and let `git pull` carry it. ⚠️ It enters git history — fine for throwaway/dev envs, terrible for prod.

Default to option (1) when secrets are sensitive. Use option (2) only when the user explicitly says "明文写到项目里" / "hardcode it" (and warn them about git history).

## 8. The startup script template

Save at `<repo>/start.sh` (or anywhere stable). It must:
- `export JAVA_HOME` to the right JDK (see step 5 — Spring Boot 4 = JDK 17)
- Source secrets from a 600-mode env file (NOT inline in the script)
- Stop any previous instance
- Launch with `nohup java -jar ...`, redirecting stdout/stderr to a log file
- Print the new PID

See `templates/start-script.sh` for the canonical version. The two critical flags for Spring Boot 3.x+ on JDK 17:
```
--add-opens=java.base/java.lang=ALL-UNNAMED
--add-opens=java.base/java.lang.reflect=ALL-UNNAMED
--add-opens=java.base/java.util=ALL-UNNAMED
```
Without these you get `InaccessibleObjectException` from Hibernate/Spring internals.

## 9. Start + verify

```bash
ssh user@host 'bash <start-script>'
sleep 25
ssh user@host 'tail -50 /home/<svc>/logs/<app>.out'
ssh user@host 'ss -tlnp | grep <port>'      # or: netstat -tlnp
ssh user@host 'curl -I http://127.0.0.1:<port>'
```

**Error patterns to recognize fast**:
- `UnsupportedClassVersionError` (class file 61) → wrong JDK, set `JAVA_HOME` to JDK 17
- `Access denied for user 'X'@'Y'` → secret in `application-druid.yml` is wrong, OR env-var injection failed (env var not exported, typo in name)
- `Communications link failure` → DB host/port wrong, or DB server firewall
- `redis.clients.jedis.exceptions.JedisConnectionException` → Redis host/port/pw wrong
- `java.net.BindException: Address already in use` → old process still running; the start script's `kill $PID` step handles this; if not, `lsof -i :<port>` then `kill -9`

## 10. After it's up — operational tips

- **Log location**: `tail -f /home/<svc>/logs/<app>.out` (where you redirected in step 8)
- **To stop**: `ssh user@host 'pkill -f <artifactId>.jar'`
- **To redeploy after git push**: re-run step 5 (rebuild) + step 9 (start) — the start script handles killing the old PID
- **Don't commit the start script** to git if it contains secrets; or commit it ONLY if secrets are in a sourced env file

## Pitfalls (compiled from real sessions)

- **Hermes output mask** — see step 7. Biggest time-waster. Verify with `od -c`.
- **Multi-JDK servers** — `mvn` may default to JDK 17 while `java` defaults to JDK 11. Always `export JAVA_HOME` explicitly in the start script.
- **Spring Boot 3/4 needs `--add-opens`** — Hibernate and Spring AOT both need reflective access.
- **CRLF in yml files** — Windows-cloned repos have `\r\n`; `sed -i 's/port: 80/port: 8081/'` will silently fail to match. Use Python:
  ```python
  data = re.sub(rb"(port:\s+)80(\r?\n)", rb"\g<1>8081\g<2>", open(p,'rb').read(), count=1)
  ```
- **`git pull` with local edits** — stash first: `git stash push -m "msg" -- <file> && git pull --rebase && git stash pop`. Resolve any conflicts (often the port line — your local 8081 vs remote's 8081 are the same value, just keep one).
- **`git stash pop` can leave conflict markers** — after pop, check `git status -sb`. If you see `MM` (both modified), the file has unresolved `<<<<<<<` blocks. Inspect with `grep -n '<<<\|>>>\|===' <file>` and resolve. Fastest reset to remote: `git checkout HEAD -- <file>` (discards local mods, takes the remote HEAD version verbatim). This is the right call when the user pushed a fix and your local edits are stale.
- **JDBC URL with `&` in bash** — quote the whole string, single-quotes survive `&` and `%2B` best.
- **Firewall on Tencent Cloud / Aliyun** — opening a port in the app is not enough; the cloud security group must allow it. `curl http://127.0.0.1:PORT` works (in-VM) but external `http://<public-ip>:PORT` fails. Open the port in the cloud console.
- **"Secrets are already in the project"** — when a RuoYi project already has hardcoded `url/username/password` in `application-druid.yml` and `host/port/password` in `application.yml`, do NOT keep trying to inject via env vars. Read the project first (`git show HEAD:<file>` and `sed -n` on the local working copy), confirm the values are there, then just `git pull && mvn package && restart`. Pushing the user to re-enter passwords the project already has is the #1 cause of "为啥你还要传" frustration. Re-verify with `git show HEAD:` not `cat` (a dirty local working tree can lie).
- **`ssh -t` from Hermes `terminal` cannot host interactive `read -s`** — when you try `ssh -t jorge-remote 'read -s MPW; ...'`, you get "Pseudo-terminal will not be allocated because stdin is not a terminal". The only working escape route for the secret-on-remote pattern is to have the user run the `read -s` block themselves in their own ssh session. The `pty=true` flag in `terminal()` enables this for the **agent's** tool, not for the remote shell's stdin, so plan around it.

## Linked files
- `templates/start-script.sh` — copy-paste-ready startup script
- `references/hermes-secret-mask-pitfall.md` — deep-dive on the output-mask problem + workarounds
- `references/gitee-ssh-setup.md` — Gitee-specific SSH deploy key + verified `~/.ssh/config` snippet
- `scripts/diagnose-deploy.sh` — one-shot diagnostic (port, log, curl, processes)
