# Hermes Output Mask — the secret-string pitfall

## What happens

When you call a Hermes tool (terminal, write_file, etc.) and your command contains a string that looks like a password, token, API key, or other credential, **the tool layer rewrites that string to `***` in the command output** that comes back to you.

**The trap**: it doesn't just hide the string from the agent's eyes — the masked value (`***`) is what actually gets sent to the remote system. So if you `cat > start.sh << EOF ... export DB_PASSWORD="123456" ... EOF`, the file on disk contains `export DB_PASSWORD="***"`, not the real password.

This affects:
- `cat << EOF` / `cat << 'EOF'` / `<< INNER_EOF` (any heredoc)
- `echo "secret=..."`, `printf "..."`
- `python3 -c "...secret..."` and `python << PYEOF ... PYEOF`
- `sed -i "s/...secret.../.../"` 
- `base64` of a string containing a secret (the encoded output still triggers the filter)
- `write_file` with literal secret in content

**It does NOT affect**:
- `read -s` (real stdin from user keyboard)
- The actual contents of files already on disk (reading is safe, only WRITING the literal into a command is the problem)
- Output of `od -c` (raw bytes, which is why we use it to verify)

## How to detect you got burned

**Verify with raw bytes, not with `cat`**:

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

## How to work around it

### Option A: User runs the secret-write step themselves (RECOMMENDED)

The user pastes a small `read -s` snippet into their own terminal session against the remote host. The secret travels terminal → SSH → remote shell stdin, never through a Hermes tool call.

```bash
# On the user's local terminal:
ssh user@host

# In the remote shell, the user pastes:
stty -echo; read -r -p "DB PW: " MPW; echo
printf 'export DB_PASSWORD=%s\nexport REDIS_PASSWORD=%s\n' "$MPW" "$RPW" > ~/.app_env
chmod 600 ~/.app_env
stty echo
```

The start script does `source ~/.app_env` at the top.

### Option B: Hardcode the secret in the project source

The user edits `application-druid.yml` (or equivalent) and `git push`es. The secret travels through the git remote, not through Hermes.

```yaml
spring:
  datasource:
    druid:
      master:
        password: 123456    # hardcoded for this env
```

Pros: works without user intervention. Cons: secret in git history forever; visible to anyone with repo read access. Only acceptable for dev/throwaway deploys.

### Option C: Store on remote, fetch via `curl` from a pre-shared URL

Put the secret in a private gist / password manager's CLI, then `curl` it into the env file on the remote. Only useful if there's already a secrets backend in play.

### Option D: Generate the secret on the remote

If the DB / Redis doesn't yet have a password, generate one and configure both ends in one session — never passing the literal through Hermes. Only works for greenfield deploys.

## What NOT to do (waste of time)

- ❌ `base64 -w0` then `echo $B64 | base64 -d` — the encoded form still contains the secret character sequence
- ❌ `python3 -c "open('/tmp/file','w').write('secret=123456')"` — the literal in the python source is what gets masked
- ❌ `printf` with a literal — same problem
- ❌ `expect` script with a hardcoded send — same problem
- ❌ Asking the user to paste the secret back to you in a Hermes message — it gets masked in your own output, but worse, it's now in conversation history

The only reliable path is **A or B**. Pick A by default.
