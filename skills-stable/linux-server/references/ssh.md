# SSH Access

SSH work decides who can log in, how root logs in, how many keys the server lets a client try, and how to change `sshd` without losing access.

## Contents

- Read effective state
- Client aliases with RemoteCommand
- Single-owner VPS
- Multi-key agents
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
Before a write, enumerate every intended admin user/source pair affected by existing `Match` blocks and run `sshd -T -C user=<USER>,host=<HOST>,addr=<SOURCE_IP>` for each. The change recipe below asserts the current SSH source plus a root baseline; those two checks do not cover additional team contexts.

## Client Aliases With RemoteCommand

Inspect the resolved client configuration before using an alias for automation:

```bash
ssh -G <HOST_ALIAS> | awk '$1 ~ /^(hostname|user|remotecommand|requesttty)$/ { print }'
```

An alias with `RemoteCommand` cannot also accept a command from the command line. OpenSSH fails before reaching the server. Disable the alias command for non-interactive SSH and SCP:

```bash
ssh -o RemoteCommand=none -o RequestTTY=no <HOST_ALIAS> '<READ_ONLY_COMMAND>'
scp -o RemoteCommand=none <SOURCE> <HOST_ALIAS>:<DESTINATION>
```

## Single-Owner VPS

On single-owner VPS and proxy nodes, keep this shape:

```text
PubkeyAuthentication yes
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
MaxAuthTries <N>
```

`PermitRootLogin prohibit-password` means root can still log in by key, but root password login is blocked.

Do not add `PermitRootLogin no`, `AllowUsers`, or `AllowGroups` unless the user wants that model and an alternate admin path has been verified from a fresh session.

## Multi-Key Agents

Loaded-key agents can offer many candidate keys. A low server-side
`MaxAuthTries` can close the connection before the correct key is attempted.

Raise `MaxAuthTries` on single-owner VPS hosts only when the user's SSH agent
can exhaust the server-side attempt limit:

```text
MaxAuthTries <N>
```

When server-side `MaxAuthTries` cannot be raised, or when the user wants fewer offered keys, use one of two explicit client shapes.

For a key held by an SSH agent, point `IdentityAgent` at that agent and use the
public key as the identity selector:

```sshconfig
Host <HOST_ALIAS>
  HostName <HOSTNAME_OR_IP>
  User root
  IdentityAgent "<agent-socket>"
  IdentityFile ~/.ssh/<HOST_ALIAS>.pub
  IdentitiesOnly yes
```

Use host-specific rules or `ssh -i` when debugging. Do not lower `MaxAuthTries` merely because password auth is disabled.

For a local private key, disable the agent so a locked or slow agent cannot
block the connection. OpenSSH rejects private keys readable by group or other
users:

```sshconfig
Host <HOST_ALIAS>
  HostName <HOSTNAME_OR_IP>
  User root
  IdentityAgent none
  IdentityFile ~/.ssh/<PRIVATE_KEY>
  IdentitiesOnly yes
```

```bash
chmod 600 ~/.ssh/<PRIVATE_KEY>
ssh -G <HOST_ALIAS> | awk '$1 ~ /^(identityagent|identityfile|identitiesonly)$/ { print }'
```

## Change SSH Config

OpenSSH uses the first obtained value for each keyword. A lexically late `90-` file is not an override when an earlier file already set the keyword. Read the main file, include order, and existing drop-ins before writing:

```bash
ls -la /etc/ssh/sshd_config.d/
sed -n '1,200p' /etc/ssh/sshd_config.d/*.conf 2>/dev/null
```

Set `MAX_AUTH_TRIES` to an integer that fits the observed SSH agent and the operator policy before writing the drop-in.

The recipe uses an early `00-` drop-in, then asserts both global and root Match-context effective values. If another setting still wins, it restores the original and stops; change the actual first setter only after identifying it.

Persistent impact: writes `/etc/ssh/sshd_config.d/00-linux-server-access.conf` and changes effective SSH authentication policy until the drop-in is removed or replaced and `sshd` is reloaded.

```bash
: "${MAX_AUTH_TRIES:?set MAX_AUTH_TRIES before writing SSH config}"
case "$MAX_AUTH_TRIES" in *[!0-9]*|'') exit 1;; esac
: "${SSH_CONNECTION:?run from the SSH session whose Match context must remain reachable}"
SSH_TEST_USER=${SSH_TEST_USER:-$(id -un)}
SSH_TEST_ADDR=${SSH_TEST_ADDR:-${SSH_CONNECTION%% *}}
SSH_TEST_HOST=${SSH_TEST_HOST:-$(hostname -f)}
install -d -m 755 -o root -g root /etc/ssh/sshd_config.d
target=/etc/ssh/sshd_config.d/00-linux-server-access.conf
candidate=$(mktemp /run/sshd-candidate.XXXXXX)
backup=''
ssh_unit=$(systemctl list-unit-files 'ssh.service' 'sshd.service' --no-legend | awk 'NR == 1 { print $1 }')
test -n "$ssh_unit" || { echo "SSH systemd unit not found" >&2; exit 1; }
trap 'rm -f "$candidate"' EXIT
cat >"$candidate" <<EOF
PubkeyAuthentication yes
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
MaxAuthTries $MAX_AUTH_TRIES
EOF
chmod 600 "$candidate" || exit 1
if test -e "$target"; then
  backup=$(mktemp /run/sshd-original.XXXXXX)
  chmod 600 "$backup" || exit 1
  cp -a "$target" "$backup" || exit 1
fi
restore_target() {
  if test -n "$backup"; then
    install -o root -g root -m 0644 "$backup" "$target" || return 1
  else
    rm -f "$target" || return 1
  fi
  sshd -t
}
check_effective() {
  effective=$(mktemp /run/sshd-effective.XXXXXX) || return 1
  if ! "$@" >"$effective"; then rm -f "$effective"; return 1; fi
  for expected in \
    'pubkeyauthentication yes' \
    'passwordauthentication no' \
    'kbdinteractiveauthentication no' \
    "maxauthtries $MAX_AUTH_TRIES"; do
    grep -Fqx "$expected" "$effective" || { rm -f "$effective"; return 1; }
  done
  grep -Eq '^permitrootlogin (without-password|prohibit-password)$' "$effective" \
    || { rm -f "$effective"; return 1; }
  rm -f "$effective"
}
if ! install -o root -g root -m 0644 "$candidate" "$target" \
  || ! sshd -t \
  || ! check_effective sshd -T \
  || ! check_effective sshd -T -C user="$SSH_TEST_USER",host="$SSH_TEST_HOST",addr="$SSH_TEST_ADDR" \
  || ! check_effective sshd -T -C user=root,host=localhost,addr=127.0.0.1; then
  restore_target || echo "CRITICAL: original SSH config could not be restored and validated" >&2
  exit 1
fi
if ! systemctl reload "$ssh_unit"; then
  if ! restore_target || ! systemctl reload "$ssh_unit"; then
    echo "CRITICAL: SSH reload failed and rollback did not restore service" >&2
  fi
  exit 1
fi
check_effective sshd -T || exit 1
check_effective sshd -T -C user="$SSH_TEST_USER",host="$SSH_TEST_HOST",addr="$SSH_TEST_ADDR" || exit 1
check_effective sshd -T -C user=root,host=localhost,addr=127.0.0.1 || exit 1
printf 'ssh_backup=%s\n' "${backup:-none; original target absent}"
```

After reload, open a new SSH connection before closing the current one.

## Team Admin Transition

Use this only when several people administer the machine or the user wants to stop sharing root.

Persistent impact: creates a local admin account, copies root authorized keys, and changes sudo-capable access until the user and files are removed.

```bash
if id <ADMIN_USER> >/dev/null 2>&1; then
  echo "admin user already exists; inspect it instead of overwriting access" >&2
  exit 1
fi
test -s /root/.ssh/authorized_keys || { echo "root authorized_keys is absent or empty" >&2; exit 1; }
getent group sudo >/dev/null || { echo "sudo group is unavailable" >&2; exit 1; }
useradd -m -s /bin/bash -G sudo <ADMIN_USER> || exit 1
rollback_admin() {
  userdel -r <ADMIN_USER> || echo "CRITICAL: failed to remove partial admin account" >&2
}
if ! install -d -o <ADMIN_USER> -g <ADMIN_USER> -m 0700 /home/<ADMIN_USER>/.ssh \
  || ! install -o <ADMIN_USER> -g <ADMIN_USER> -m 0600 \
    /root/.ssh/authorized_keys /home/<ADMIN_USER>/.ssh/authorized_keys; then
  rollback_admin
  exit 1
fi
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
if ! printf '%s:%s\n' '<ADMIN_USER>' "$ADMIN_PASSWORD" | chpasswd; then
  unset ADMIN_PASSWORD
  exit 1
fi
unset ADMIN_PASSWORD
```

Expire the password with `passwd -e` only when it is a temporary handoff the user will replace at first interactive login; an expired password can block PAM's account check for sudo before that login happens.

Only after verification add:

```text
PermitRootLogin no
AllowUsers <ADMIN_USER>
```

If `AllowUsers` is set, add every intended admin before reloading. For accidental lockout, query the actual SSH unit as shown below and search for `not allowed because not listed in AllowUsers`; `_COMM=sshd` alone misses `sshd-session` on current OpenSSH.

## SSH Settings That Need A Reason

Do not add these to a single-owner VPS unless the condition is true:

- `X11Forwarding no`: set when SSH X11 forwarding is not in use.
- `PermitUserRC no`: disables `~/.ssh/rc`, which can be a persistence path.
- `AllowUsers` / `AllowGroups`: add for team or compliance models after the complete intended user list is known.
- SSH `KexAlgorithms`, `Ciphers`, and `MACs`: leave unchanged unless the user explicitly asks for crypto policy; verification commands are in [performance-tuning.md](performance-tuning.md). Algorithm lists can break older clients and are not required for ordinary VPS security.

## Anti-Brute-Force

`fail2ban` or CrowdSec is not a single-owner VPS default when SSH is key-only and source-restricted. Add active banning when password login is temporarily enabled, logs show repeated brute-force attempts, or the user wants active banning. Query the SSH unit instead of filtering only `_COMM=sshd`; OpenSSH 9.8 moves session work into `sshd-session`.

Persistent impact: installing or enabling active banning changes future SSH reachability for sources that match ban rules.

Read before changing:

```bash
systemctl is-active fail2ban 2>/dev/null
fail2ban-client status sshd 2>/dev/null
ssh_unit=$(systemctl list-unit-files 'ssh.service' 'sshd.service' --no-legend | awk 'NR == 1 { print $1 }')
ssh_log=$(mktemp)
if journalctl -u "$ssh_unit" --since "24 hours ago" --no-pager >"$ssh_log"; then
  tail -200 "$ssh_log"
else
  echo "SSH journal unavailable; not verified" >&2
fi
rm -f "$ssh_log"
```
