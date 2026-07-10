# Firewall

Firewall work decides which listening services are reachable from the network and which tool owns the rules.

## Contents

- Read runtime state
- One rule owner
- Small VPS with UFW
- nftables
- Rollback for risky rule changes
- Port and rule match
- UDP

## Read Runtime State

```bash
ss -tulpen
if command -v ufw >/dev/null 2>&1; then ufw status verbose; fi
if command -v nft >/dev/null 2>&1; then nft list ruleset 2>/dev/null; fi
iptables -S 2>/dev/null
ip6tables -S 2>/dev/null
```

Map every public listener to a user-confirmed or configured service before changing rules:

```bash
ss -H -tulpen | sort -k5,5
systemctl --no-pager --type=service --state=running
```

## One Rule Owner

Use one firewall manager per host.

- If nftables is already configured and persistent, continue with nftables.
- If UFW is already in use, manage rules through UFW.
- Do not install UFW on a host that already has a clear nftables policy unless the user explicitly wants migration.
- If Docker is present, inspect Docker rules and published ports per [containers.md](containers.md) before trusting UFW output.

## Small VPS With UFW

For a single-owner VPS with SSH and one service port, identify values before applying:

```bash
sshd -T | awk '$1 == "port" { print }'
ss -H -tulpen | sort -k5,5
ss -H -ulpen | sort -k5,5
```

Persistent impact: installs UFW if absent, enables it at boot, and changes inbound policy to default deny with explicit allow rules.

```bash
export DEBIAN_FRONTEND=noninteractive
if ! apt-get update || ! apt-get install -y ufw; then exit 1; fi
ufw_backup=$(mktemp /run/ufw-original.XXXXXX.tar)
chmod 600 "$ufw_backup" || exit 1
tar -C / -cpf "$ufw_backup" etc/ufw etc/default/ufw || exit 1
tar -tf "$ufw_backup" >/dev/null || exit 1
ufw_status=$(LC_ALL=C ufw status) || exit 1
case "$ufw_status" in
  'Status: active'*) ufw_was_active=1 ;;
  'Status: inactive'*) ufw_was_active=0 ;;
  *) echo "unrecognized UFW state; refusing mutation" >&2; exit 1 ;;
esac
restore_ufw() {
  restore_failed=0
  rm -rf /etc/ufw || restore_failed=1
  rm -f /etc/default/ufw || restore_failed=1
  tar -C / -xpf "$ufw_backup" || restore_failed=1
  if test "$ufw_was_active" -eq 1; then
    ufw --force enable || restore_failed=1
  else
    ufw --force disable || restore_failed=1
    rm -rf /etc/ufw || restore_failed=1
    rm -f /etc/default/ufw || restore_failed=1
    tar -C / -xpf "$ufw_backup" || restore_failed=1
  fi
  test "$restore_failed" -eq 0
}
if ! ufw default deny incoming \
  || ! ufw default allow outgoing \
  || ! ufw allow <SSH_PORT>/tcp comment ssh \
  || ! ufw allow <SERVICE_PORT>/tcp comment <SERVICE_NAME> \
  || ! ufw --force enable \
  || ! ufw status verbose; then
  restore_ufw || echo "CRITICAL: UFW change failed and rollback was incomplete" >&2
  exit 1
fi
printf 'ufw_backup=%s previous_active=%s\n' "$ufw_backup" "$ufw_was_active"
```

Add UDP only when the service configuration or `ss -ulpen` shows a UDP listener:

Persistent impact: adds an inbound UDP allow rule until the rule is deleted.

```bash
udp_backup=$(mktemp /run/ufw-udp-original.XXXXXX.tar)
chmod 600 "$udp_backup" || exit 1
tar -C / -cpf "$udp_backup" etc/ufw etc/default/ufw || exit 1
tar -tf "$udp_backup" >/dev/null || exit 1
udp_status=$(LC_ALL=C ufw status) || exit 1
case "$udp_status" in
  'Status: active'*) udp_was_active=1 ;;
  'Status: inactive'*) udp_was_active=0 ;;
  *) echo "unrecognized UFW state; refusing mutation" >&2; exit 1 ;;
esac
restore_ufw_udp() {
  udp_restore_failed=0
  rm -rf /etc/ufw || udp_restore_failed=1
  rm -f /etc/default/ufw || udp_restore_failed=1
  tar -C / -xpf "$udp_backup" || udp_restore_failed=1
  if test "$udp_was_active" -eq 1; then
    ufw --force enable || udp_restore_failed=1
  else
    ufw --force disable || udp_restore_failed=1
    rm -rf /etc/ufw || udp_restore_failed=1
    rm -f /etc/default/ufw || udp_restore_failed=1
    tar -C / -xpf "$udp_backup" || udp_restore_failed=1
  fi
  test "$udp_restore_failed" -eq 0
}
if ! ufw allow <SERVICE_PORT>/udp comment <SERVICE_NAME> \
  || ! ufw status verbose; then
  restore_ufw_udp || echo "CRITICAL: UFW UDP change failed and rollback was incomplete" >&2
  exit 1
fi
printf 'ufw_udp_backup=%s\n' "$udp_backup"
```

Keep the current SSH session open and retain the printed root-only backup until a new SSH connection succeeds. If the external check fails, restore `/etc/ufw` from that exact archive and return UFW to the printed prior active state before closing the original session.

## nftables

For a host using nftables directly, stage a candidate outside `/etc`, validate it, then use the rollback procedure below. Do not install `/etc/nftables.conf`, enable the service, reload, or start it before a runtime rollback timer is active and a fresh SSH connection has verified the candidate. Keep the existing forward policy when the host is a router, VPN gateway, or container host.

```bash
candidate=/run/nft-candidate.conf
nft -c -f "$candidate" || exit 1
```

Input ruleset shape:

```nft
flush ruleset

table inet filter {
    chain input {
        type filter hook input priority filter; policy drop;
        iif lo accept
        ct state established,related accept
        ct state invalid drop
        ip protocol icmp accept
        ip6 nexthdr ipv6-icmp accept
        tcp dport <SSH_PORT> accept
        tcp dport <SERVICE_PORT> accept
    }
    chain forward {
        type filter hook forward priority filter; policy drop;
    }
    chain output {
        type filter hook output priority filter; policy accept;
    }
}
```

## Rollback For Risky Rule Changes

Schedule rollback before replacing nftables rules over SSH. `nft -f` applies incrementally: both the backup and the candidate rules file must start with `flush ruleset` (Debian's `/etc/nftables.conf` does), or the load merges into the current ruleset instead of replacing it.

Runtime impact: creates a transient `nft-rollback` systemd unit and timer until it fires or is stopped.

```bash
candidate=/path/to/new-rules.conf
backup=$(mktemp /run/nft-backup.XXXXXX)
chmod 600 "$backup" || exit 1
if ! { printf 'flush ruleset\n'; nft list ruleset; } >"$backup"; then
  rm -f "$backup"
  exit 1
fi
if ! nft -c -f "$backup"; then rm -f "$backup"; exit 1; fi
if ! awk 'NF && $1 !~ /^#/ { found=1; good=($1 == "flush" && $2 == "ruleset"); exit !good } END { if (!found) exit 1 }' "$candidate"; then
  echo "candidate must begin with flush ruleset" >&2
  rm -f "$backup"
  exit 1
fi
if ! nft -c -f "$candidate"; then rm -f "$backup"; exit 1; fi
if ! systemd-run --on-active=120 --unit=nft-rollback nft -f "$backup"; then
  rm -f "$backup"
  exit 1
fi
if ! systemctl is-active --quiet nft-rollback.timer; then
  echo "rollback timer is not active" >&2
  rm -f "$backup"
  exit 1
fi
if ! nft -f "$candidate"; then
  systemctl start nft-rollback.service || true
  exit 1
fi
printf 'rollback_backup=%s\n' "$backup"
```

The final `nft -f` is the runtime-impact boundary: it replaces the active ruleset until another ruleset is loaded or the nftables service reloads a different persistent file. It does not yet change boot persistence.

After a fresh SSH connection verifies the candidate, persist it while the rollback timer is still active:

```bash
persistent_target=/etc/nftables.conf
persistent_backup=$(mktemp /run/nftables-conf-original.XXXXXX)
target_was_absent=0
if test -e "$persistent_target"; then
  chmod 600 "$persistent_backup" || exit 1
  cp -a "$persistent_target" "$persistent_backup" || exit 1
else
  target_was_absent=1
fi
if ! install -o root -g root -m 0644 "$candidate" "$persistent_target" \
  || ! systemctl enable nftables; then
  if test "$target_was_absent" -eq 1; then
    rm -f "$persistent_target" || true
  else
    install -o root -g root -m 0644 "$persistent_backup" "$persistent_target" || true
  fi
  nft -f "$backup" || echo "CRITICAL: failed to restore active nftables rules" >&2
  exit 1
fi
```

Cancel after new SSH connectivity is verified:

```bash
systemctl stop nft-rollback.timer nft-rollback.service || exit 1
if systemctl is-active --quiet nft-rollback.timer \
  || systemctl is-active --quiet nft-rollback.service; then
  echo "rollback unit is still active" >&2
  exit 1
fi
nft -c -f "$candidate" || exit 1
nft -f "$candidate" || exit 1
nft list ruleset || exit 1
```

Open one more fresh SSH connection and verify the candidate runtime rules. Only then remove the named rollback files from the original shell:

```bash
rm -f "$backup" "$persistent_backup"
```

## Port And Rule Match

Record one explanation for every allow rule:

- a current listener and owning process
- an explicitly planned service being deployed in the same task
- a provider or overlay requirement the user confirmed

Every public listener must have a matching allow path unless the user confirms it is intentionally blocked at the OS firewall or there is a verified provider firewall rule for it.

Flag open management surfaces (the management-port list lives in [containers.md](containers.md)). Close them only when the current user request explicitly includes removal or the user confirms the closure.

On a public web host, keep 80 and 443 only while a listener or a service planned in the current task needs them; panels and admin UIs count as management ports, not public services.

## UDP

UDP does not give a reliable connect test like TCP. Verify it by:

- service listener in `ss -ulpen`
- firewall allow rule for the UDP port
- application-specific logs or client test when available
