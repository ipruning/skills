---
name: surge-patch
description: |
  Read Snell VPS state over SSH and test local Surge policies without changing
  servers. Use for Surge/Snell outages, Snell v5/v6 listener checks, systemd
  UDP crash evidence, SSH/firewall/sysctl/swap inventory, and manual repair
  planning. Do not use to install, repair, restart, or tune a VPS.
---

# Surge Snell Checks

Use `scripts/surge_patch.py` with `uv run --script`.

The script reads what is on the machine. It does not fix the machine. If a
change is needed, write the change down and leave execution to the operator.

## Work

1. Read [Snell VPS Triage](references/snell-vps-triage.md) before judging a
   VPS, systemd service, UDP behavior, firewall exposure, proxy sysctls, or
   Surge route.
2. For one VPS, run `audit-snell`. For several VPSes, put one SSH target per
   line in a hosts file and run `audit-fleet`.
3. Open `audit.json`. Read `facts`, `findings`, `evidence_paths`, and
   `recommended_manual_actions`.
4. If a repair is needed, run `render-repair-plan --audit <audit.json>`. The
   command prints manual actions. It does not run them.
5. Use `smoke-surge` for local Surge policy checks. It does not touch the VPS.

Keep endpoint IPs, PSKs, profile names, and inventories in the user's task or
private config. Audit logs must not contain plaintext Snell PSKs.

## Commands

Audit one VPS:

```bash
uv run --script scripts/surge_patch.py audit-snell \
  --host root@203.0.113.10 \
  --journal-since "6 hours ago" \
  --out /tmp/surge-patch-runs
```

Audit a fleet:

```bash
uv run --script scripts/surge_patch.py audit-fleet \
  --hosts ./snell-hosts.txt \
  --journal-since "6 hours ago" \
  --out /tmp/surge-patch-runs
```

Print manual repair actions:

```bash
uv run --script scripts/surge_patch.py render-repair-plan \
  --audit /tmp/surge-patch-runs/<run_id>/audit.json
```

Check a local Surge policy:

```bash
uv run --script scripts/surge_patch.py smoke-surge \
  --policy "My Snell Policy" \
  --test tcp \
  --test udp
```

## Files

`audit-snell` and `audit-fleet` write a local directory under `--out`.

Read these files first:

- `audit.json`: the result to quote in the answer
- `logs/audit_raw.log`: redacted raw evidence
- `logs/audit_summary.kv`: compact facts from the VPS
- `logs/journal_recent.log`: recent Snell log markers
- `logs/service_cat.log`: effective systemd unit and drop-ins
- `logs/listeners.log`: TCP and UDP listeners
- `logs/sshd_effective.log`: effective SSH settings
- `logs/ufw_status.log`, `logs/nft_ruleset.log`, `logs/iptables_rules.log`
- `logs/docker_ports.log`: Docker-published ports when Docker is present

Exit codes:

- SSH, upload, remote execution, or collection failed: non-zero
- Audit completed and found server problems: zero
- Audit completed and found server problems with `--fail-on-issue`: non-zero

## Snell Rules

Judge Snell v5 and v6 separately.

- v5 can use TCP and UDP on existing UDP/QUIC nodes.
- v6 is normally TCP-only unless the user gives a concrete UDP need.
- v6 configs should not carry old `ipv6`, `obfs`, `reuse`, or `version`
  fields.
- `Decryption failed` by itself usually means scanner traffic, a stale client,
  or a wrong PSK. Do not call it a server crash unless logs or load say so.

Do not treat `udp_listen=yes` as always good. Do not treat `udp_listen=no` as
always bad.
