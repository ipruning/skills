# SSH Access

SSH work decides who can log in, how root logs in, how many keys the server lets a client try, and how to change `sshd` without losing access.

## Contents

- Read effective state
- Single-owner VPS
- 1Password and multi-key agents
- Change SSH config
- Team admin transition
- SSH settings that need a reason
- Anti-brute-force

## Read Effective State

Start with the effective config:

```bash
sshd -T | awk '$1 ~ /^(port|listenaddress|permitrootlogin|passwordauthentication|kbdinteractiveauthentication|pubkeyauthentication|maxauthtries|maxsessions|logingracetime|allowusers|allowgroups|authenticationmethods|permituserrc|x11forwarding)$/ { print }'
grep -i '^Match' /etc/ssh/sshd_config /etc/ssh/sshd_config.d/*.conf 2>/dev/null
sshd -T -C user=root,addr=0.0.0.0,host= | awk '$1 ~ /^(permitrootlogin|passwordauthentication|kbdinteractiveauthentication|permituserrc)$/ { print }'
ls -la /etc/ssh/sshd_config.d/ 2>/dev/null
```

Match blocks can override global settings. Check them before concluding that a global setting applies to a user or source.

## Single-Owner VPS

On personal VPS and proxy nodes, keep this shape:

```text
PubkeyAuthentication yes
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
MaxAuthTries 20
```

`PermitRootLogin prohibit-password` means root can still log in by key, but root password login is blocked.

Do not add `PermitRootLogin no`, `AllowUsers`, or `AllowGroups` unless the user wants that model and an alternate admin path has been verified from a fresh session.

## 1Password And Multi-Key Agents

1Password SSH agent and other loaded-key agents can offer many candidate keys. A low server-side `MaxAuthTries` can close the connection before the correct key is attempted.

Set on single-owner VPS hosts when the user uses 1Password SSH agent or another multi-key agent:

```text
MaxAuthTries 20
```

When server-side `MaxAuthTries` cannot be raised, or when the user wants fewer offered keys, add a host-specific client rule:

```sshconfig
Host <HOST_ALIAS>
  HostName <HOSTNAME_OR_IP>
  User root
  IdentityAgent "~/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"
  IdentityFile ~/.ssh/<HOST_ALIAS>.pub
  IdentitiesOnly yes
```

Use host-specific rules or `ssh -i` when debugging. Do not lower `MaxAuthTries` merely because password auth is disabled.

## Change SSH Config

Write an override file rather than editing packaged defaults:

Read existing drop-ins before writing:

```bash
ls -la /etc/ssh/sshd_config.d/
sed -n '1,200p' /etc/ssh/sshd_config.d/*.conf 2>/dev/null
```

Persistent impact: writes `/etc/ssh/sshd_config.d/90-linux-server-access.conf` and changes effective SSH authentication policy until the drop-in is removed or replaced and `sshd` is reloaded.

```bash
install -d -m 755 -o root -g root /etc/ssh/sshd_config.d
cp -a /etc/ssh/sshd_config.d/90-linux-server-access.conf /etc/ssh/sshd_config.d/90-linux-server-access.conf.bak.$(date +%Y%m%d%H%M%S) 2>/dev/null || true
cat >/etc/ssh/sshd_config.d/90-linux-server-access.conf <<'EOF'
PubkeyAuthentication yes
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
MaxAuthTries 20
EOF
sshd -t
systemctl reload ssh
sshd -T | awk '$1 ~ /^(permitrootlogin|passwordauthentication|kbdinteractiveauthentication|pubkeyauthentication|maxauthtries)$/ { print }'
```

After reload, open a new SSH connection before closing the current one.

## Team Admin Transition

Use this only when several people administer the machine or the user wants to stop sharing root.

Persistent impact: creates a local admin account, copies root authorized keys, and changes sudo-capable access until the user and files are removed.

```bash
useradd -m -s /bin/bash -G sudo <ADMIN_USER>
mkdir -p /home/<ADMIN_USER>/.ssh
cp /root/.ssh/authorized_keys /home/<ADMIN_USER>/.ssh/authorized_keys
chown -R <ADMIN_USER>:<ADMIN_USER> /home/<ADMIN_USER>/.ssh
chmod 700 /home/<ADMIN_USER>/.ssh
chmod 600 /home/<ADMIN_USER>/.ssh/authorized_keys
```

Verify from a fresh session:

```bash
ssh <ADMIN_USER>@host
sudo -i
```

Set a password only when the user explicitly wants password-based sudo or console login. Do not put the password literal in shell history.

Persistent impact: changes the local password hash for `<ADMIN_USER>` until another password change or account removal.

```bash
read -r -s ADMIN_PASSWORD
printf '%s:%s\n' '<ADMIN_USER>' "$ADMIN_PASSWORD" | chpasswd
unset ADMIN_PASSWORD
passwd -e <ADMIN_USER>
```

Only after verification add:

```text
PermitRootLogin no
AllowUsers <ADMIN_USER>
```

If `AllowUsers` is set, add every intended admin before reloading. Diagnosis for accidental lockout: `journalctl -u ssh` often shows `not allowed because not listed in AllowUsers`.

## SSH Settings That Need A Reason

Do not add these to a personal VPS unless the condition is true:

- `X11Forwarding no`: set when SSH X11 forwarding is not in use.
- `PermitUserRC no`: disables `~/.ssh/rc`, which can be a persistence path.
- `AllowUsers` / `AllowGroups`: add for team or compliance models after the complete intended user list is known.
- SSH `KexAlgorithms`, `Ciphers`, and `MACs`: leave unchanged unless the user explicitly asks for crypto policy. Algorithm lists can break older clients and are not required for ordinary VPS security.

## Anti-Brute-Force

`fail2ban` or CrowdSec is not a single-owner VPS default when SSH is key-only and source-restricted. Add active banning when password login is temporarily enabled, logs show repeated brute-force attempts, or the user wants active banning.

Persistent impact: installing or enabling active banning changes future SSH reachability for sources that match ban rules.

Read before changing:

```bash
systemctl is-active fail2ban 2>/dev/null
fail2ban-client status sshd 2>/dev/null
journalctl -u ssh --since "24 hours ago" --no-pager | tail -200
```
