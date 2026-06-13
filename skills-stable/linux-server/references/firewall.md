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
- If Docker is present, inspect Docker rules and published ports before trusting UFW output.

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
apt-get update
apt-get install -y ufw
ufw default deny incoming
ufw default allow outgoing
ufw allow <SSH_PORT>/tcp comment ssh
ufw allow <SERVICE_PORT>/tcp comment <SERVICE_NAME>
ufw --force enable
ufw status verbose
```

Add UDP only when the service configuration or `ss -ulpen` shows a UDP listener:

Persistent impact: adds an inbound UDP allow rule until the rule is deleted.

```bash
ufw allow <SERVICE_PORT>/udp comment <SERVICE_NAME>
ufw status verbose
```

Keep the current SSH session open and verify a new SSH connection after enabling.

## nftables

For a host using nftables directly, persist rules in `/etc/nftables.conf` and validate before loading. Keep the existing forward policy when the host is a router, VPN gateway, or container host.

Persistent impact: enables the nftables service and replaces the active firewall ruleset with the validated file.

```bash
nft -c -f /etc/nftables.conf
systemctl enable nftables
systemctl restart nftables
nft list ruleset
```

Input ruleset shape:

```nft
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

Schedule rollback before replacing nftables rules over SSH.

Runtime impact: creates a transient `nft-rollback` systemd unit and timer until it fires or is stopped.

```bash
nft list ruleset > /tmp/nft-backup.conf
nft -c -f /path/to/new-rules.conf
systemd-run --on-active=120 --unit=nft-rollback nft -f /tmp/nft-backup.conf
systemctl list-timers --no-pager 'nft-rollback*'
```

Apply the candidate rules only after validation and rollback scheduling:

Persistent impact: replaces the active nftables ruleset until another ruleset is loaded or the nftables service reloads a different persistent file.

```bash
nft -f /path/to/new-rules.conf
```

Cancel after new SSH connectivity is verified:

```bash
systemctl stop nft-rollback.timer 2>/dev/null || true
```

## Port And Rule Match

Record one explanation for every allow rule:

- a current listener and owning process
- an explicitly planned service being deployed in the same task
- a provider or overlay requirement the user confirmed

Every public listener must have a matching allow path unless the user confirms it is intentionally blocked at the OS firewall or there is a verified provider firewall rule for it.

Flag open management surfaces such as dashboards, `x-ui`, nginx-proxy-manager admin ports, database admin ports, or Docker-published admin ports. Close them only when the current user request explicitly includes removal or the user confirms the closure.

## UDP

UDP does not give a reliable connect test like TCP. Verify it by:

- service listener in `ss -ulpen`
- firewall allow rule for the UDP port
- application-specific logs or client test when available
