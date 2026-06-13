---
name: surge-patch
description: |
  Operate Surge/Snell VPS audits, repairs, and smoke checks with a uv-based
  Python CLI. Use for Snell install or repair, read-only VPS audits, systemd
  UDP/QUIC checks, and local Surge TCP/UDP/external-IP/NAT probes.
---

# Surge Snell Operations

`scripts/surge_patch.py` prepares a run directory, uploads it when the work is
remote, runs the operation, and collects the result. Run it with
`uv run --script`.

## Workflow

1. Read [Snell VPS Triage](references/snell-vps-triage.md) when changing a VPS,
   systemd service, UDP behavior, or Surge routing.
2. Prepare one run directory for `install-snell`, `audit-snell`, or
   `surge-smoke`.
3. For remote Snell work, upload the run directory, run it over SSH, then
   collect it. The remote directory remains on the VPS for later audit.
4. For local Surge smoke checks, prepare the run locally, run it, then collect
   with
   `--local-only`.
5. Keep endpoint IPs, PSKs, profile names, and inventories in the user's current
   task input or private config.

## Output

Every structured command prints one JSON object to stdout. Progress,
diagnostics, package-manager output, SSH output, and probe details go to stderr
or files inside the run directory.

Remote run directories include:

- `manifest.json`: run id, operation, target, persistent effects, and paths
- `input.json`: structured input
- `input.env`: private shell input for the remote payload
- `stdout`, `stderr`, `exit_code`: captured payload result
- `result.json`: parsed operation result
- `logs/`: raw audit, runner, and probe logs

## Operations

`install-snell` is persistent. It may install or replace
`/usr/local/bin/snell-server`, back up and replace the Snell config and systemd
service files, remove incompatible Snell hardening drop-ins, and restart
`snell-server`. Prepare it with `--confirm-persistent`.

`audit-snell` is read-only on the VPS. It records systemd state, listeners,
recent Snell logs, hardening signals, and derived checks.

`surge-smoke` is local and read-only for Surge configuration. It runs supported
`surge-cli --raw` TCP, UDP, external IP, and NAT policy probes and stores raw
probe files in the local run directory.

## Examples

```bash
uv run --script scripts/surge_patch.py prepare \
  --operation audit-snell \
  --host root@203.0.113.10 \
  --port 14180

uv run --script scripts/surge_patch.py upload --run-dir /tmp/surge-patch-runs/<run_id>
uv run --script scripts/surge_patch.py run --run-dir /tmp/surge-patch-runs/<run_id>
uv run --script scripts/surge_patch.py collect --run-dir /tmp/surge-patch-runs/<run_id>
```

```bash
uv run --script scripts/surge_patch.py prepare \
  --operation install-snell \
  --host root@203.0.113.10 \
  --snell-version 5.0.1 \
  --port 14180 \
  --confirm-persistent
```
