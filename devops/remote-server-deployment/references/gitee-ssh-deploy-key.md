# Gitee private repo — SSH deploy key setup (verified recipe)

## When the repo is private

`git clone https://gitee.com/user/repo.git` will prompt for credentials and hang in non-interactive shells. **Switch to SSH** by giving the remote machine its own deploy key.

## Step 1 — generate a dedicated key on the remote server

Don't reuse the user's personal SSH key. One key per machine × per scope:

```bash
# From your local machine, run on the remote:
ssh user@host 'test -f ~/.ssh/gitee_<scope> || ssh-keygen -t ed25519 \
    -C "user@host-for-<scope>" -f ~/.ssh/gitee_<scope> -N ""'
```

The `-C` comment is just a label so the user can identify it later in Gitee's UI.

## Step 2 — user pastes the public key into Gitee

Print the pubkey:
```bash
ssh user@host 'cat ~/.ssh/gitee_<scope>.pub'
```

The user goes to:
- Gitee: https://gitee.com/<user> → 右上角头像 → **设置** → **SSH公钥**
- Click "添加公钥"
- Title: anything recognizable (e.g. `teleSystem-deploy-on-82.156.225.39`)
- Public key: paste the entire line printed above (including the `ssh-ed25519 ...` prefix and the trailing comment)
- Click 确定

## Step 3 — tell SSH to use the right key for gitee.com

Edit the remote's `~/.ssh/config` (create it if missing):

```
Host gitee.com
    HostName gitee.com
    User git
    IdentityFile ~/.ssh/gitee_<scope>
    StrictHostKeyChecking accept-new
```

`accept-new` auto-accepts gitee.com's host key on first connect but refuses if it changes later — safer than `no`.

## Step 4 — verify

```bash
ssh user@host 'ssh -T git@gitee.com -o StrictHostKeyChecking=accept-new 2>&1 | head -3'
```

Expected output:
```
Warning: Permanently added 'gitee.com,180.76.199.13' (ECDSA) to the list of known hosts.
Hi <displayname>(@<username>)! You've successfully authenticated, but GITEE.COM does not provide shell access.
```

If you see `Permission denied (publickey)`:
- The pubkey wasn't actually saved on Gitee (typo, wrong account, forgot to click 保存)
- Wrong `IdentityFile` path in `~/.ssh/config`
- Wrong username (must be `git`, not the user's account name)

## Step 5 — clone

```bash
ssh user@host 'cd ~ && git clone git@gitee.com:USER/REPO.git'
```

URL format: `git@gitee.com:USER/REPO.git` (note: no `https://`, no `.git` for the path, just `:`).

## Local-side gotcha

If you ALSO want to clone from your **local** machine (not the remote), the key needs to be on **your local** `~/.ssh/`, not the remote's. The user either:
- Pastes the **same** pubkey into Gitee twice (it accepts duplicate keys fine)
- Generates a separate key on the local machine and adds that one too

This is because Gitee identifies keys by their public half, not by which machine sent the request.

## GitHub equivalent

Same pattern but:
- Host: `github.com`
- User: `git`
- Public-key URL: https://github.com/settings/keys
- Verify message: `Hi <user>! You've successfully authenticated, but GitHub does not provide shell access.`

## Common mistakes

- ❌ `git clone https://gitee.com/...` — still asks for password
- ❌ `IdentityFile ~/.ssh/id_rsa` — wrong key, falls back to none
- ❌ `StrictHostKeyChecking no` — accepts MITM; use `accept-new` instead
- ❌ User's Gitee account is **different** from the repo owner (e.g. fork or org repo) — must add the deploy key under the **owner's** account, not the user's own account
- ❌ `gitee.com` host key not yet in `known_hosts` — the first `ssh -T` will prompt or fail; pre-add it with `ssh-keyscan gitee.com >> ~/.ssh/known_hosts`
