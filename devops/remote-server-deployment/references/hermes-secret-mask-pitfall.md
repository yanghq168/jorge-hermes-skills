# Hermes Output Mask — the secret-string pitfall

## What happens

When you call a Hermes tool (`terminal`, `execute_code`, `write_file`) and your command contains a string that looks like a password, token, API key, or other credential, **the tool layer rewrites that string to `***` in the command output** that comes back to you.

**The trap**: it doesn't just hide the string from the agent's eyes — the masked value (`***`) is what actually gets sent to the remote system. So if you try to write a file containing `export DB_PASSWORD="ABC123"`, the file on disk contains `export DB_PASSWORD="***"` instead of the real password.

This affects:
- `cat << EOF` / `cat << 'EOF'` / `<< INNER_EOF` (any heredoc)
- `echo "secret=..."`, `printf "..."`
- `python3 -c "...secret..."` and `python << PYEOF ... PYEOF`
- `sed -i "s/...secret.../.../"`
- `base64 -w0` of a string containing a secret (the encoded output still triggers the filter)
- `write_file` with a literal secret in content

**It does NOT affect**:
- `read -s` (real stdin from user keyboard)
- The actual contents of files already on disk (reading is safe, only WRITING the literal into a command is the problem)
- Output of `od -c` (raw bytes, which is why we use it to verify)

## Why this pitfall exists

Hermes (and many LLM agent frameworks) treat user secrets as a privacy concern and apply output filtering. The filter was designed to prevent secrets from **appearing in chat history**, but the implementation also filters them **out of the executed command** — which is a bug, not a feature. Until the upstream fix, treat this as a hard constraint of the tool environment.

## How to detect you got burned

**Verify with raw bytes, NOT with `cat`:**

```bash
ssh user@host 'grep "PASSWORD" /path/to/script | od -c | head -3'
```

Healthy output looks like:
```
0000000   e   x   p   o   r   t       D   B   _   P   A   S   S   W   O
0000020   R   D   =   "   1   2   3   4   5   6  \n
```

Burned output looks like:
```
0000000   e   x   p   o   r   t       D   B   _   P   A   S   S   W   O
0000020   R   D   =   "   *   *   *  \n
```

A second verification: run the app, and look at the actual exception. `Access denied for user 'X'@'Y' (using password: YES)` with the correct username/host almost always means the password value never made it.

Other burned-error signatures:
- JDBC: `Communications link failure` followed by `Access denied for user 'X'@'Y' (using password: YES)` — classic signature
- Redis: `NOAUTH Authentication required.` — auth value was empty/asterisks
- HTTPS / API: `401 Unauthorized` with a key that's clearly not what you set

The giveaway is the error is **consistent** (every retry fails the same way) and the password field is "definitely right" — that's when to suspect the mask.

## Reproduction recipe

```bash
# Try to write a file with a literal password (use any obvious-looking password)
ssh jorge-remote 'cat > /tmp/test.sh << EOF
export DB_PASSWORD=ABCDEFG12345
EOF'
ssh jorge-remote 'cat /tmp/test.sh'  # shows: export DB_PASSWORD=*** (the mask ate it!)
```

The file on disk has `***`, not `ABCDEFG12345`. Verified via `od -c` (shows `* * *` bytes, not digit characters).

## Workarounds (ranked)

### 1. User-driven interactive `read -s` (RECOMMENDED for one-off setup)

Generate a small `set_passwords.sh` script that uses `read -s` (silent, no echo), then writes the config. User runs it interactively on the server. Masking doesn't apply to TTY stdin.

The user pastes a `read -s` snippet into their own terminal session against the remote host. The secret travels terminal → SSH → remote shell stdin, never through a Hermes tool call:

```bash
# On the user's local terminal:
ssh user@host

# In the remote shell, the user pastes:
stty -echo; read -r -p "DB PW: " MPW; echo
printf 'export DB_PASSWORD=%s\n' "$MPW" > ~/.app_env
chmod 600 ~/.app_env
stty echo
```

The start script does `source ~/.app_env` at the top. See `templates/springboot-start.sh`.

### 2. Hardcode the secret in the project source

Edit `application-druid.yml` (or equivalent) and `git push`. The secret travels through the git remote, not through Hermes.

```yaml
spring:
  datasource:
    druid:
      master:
        password: ABCDEFG12345    # hardcoded for this env
```

Pros: works without user intervention. Cons: secret in git history forever; visible to anyone with repo read access. Only acceptable for dev/throwaway deploys.

### 3. Generate the secret on the remote

If the DB / Redis doesn't yet have a password, generate one and configure both ends in one session — never passing the literal through Hermes. Only works for greenfield deploys.

```bash
ssh user@host 'NEW_PW=$(openssl rand -base64 24) && \
  sudo mysql -e "CREATE USER ... IDENTIFIED BY \"$NEW_PW\"; ..." && \
  cat > ~/.app_env <<EOF
export DB_PASSWORD=$NEW_PW
EOF
chmod 600 ~/.app_env'
```

The `openssl rand` output does NOT trigger the password filter (no recognizable password pattern), and `$NEW_PW` is only ever a shell variable — never a literal in the tool input.

## What NOT to do (waste of time)

- ❌ `base64 -w0` then `echo $B64 | base64 -d` — the encoded form still contains the secret character sequence
- ❌ `python3 -c "open('/tmp/file','w').write('secret=ABCDEFG12345')"` — the literal in the python source is what gets masked
- ❌ `printf` with a literal — same problem
- ❌ `expect` script with a hardcoded send — same problem
- ❌ Asking the user to paste the secret back to you in a Hermes message — it gets masked in your own output, but worse, it's now in conversation history

The only reliable paths are **1, 2, or 3**. Pick 1 by default.
