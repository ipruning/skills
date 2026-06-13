---
name: surge-patch
description: |
  Troubleshoot Surge failures caused by Snell VPS endpoints, endpoint routing,
  Snell server versions, systemd units, and UDP/QUIC behavior: enhanced mode
  routing SSH, nc, or curl through the proxy under test; Snell fatal errors;
  PSK-preserving Snell upgrades; systemd unit or drop-in repairs; and failed
  Snell TCP/UDP tests.
---

# Surge Snell Operations

First collect the normal Surge baseline with `surge-cli --raw environment`, `surge-cli --raw dump policy`, and `surge-cli --raw dump profile`. Continue here when the evidence points at a Snell endpoint, its VPS, its systemd service, or its UDP path.

## Workflow

1. Read [Snell VPS Triage](references/snell-vps-triage.md) before changing Snell servers, systemd units, UDP behavior, or Surge `DIRECT` rules.
2. Build the server inventory from the active Surge profile or user-provided input. Keep real IPs, PSKs, hostnames, and profile names in the user's private config or current task notes.
3. Under Surge enhanced mode or rule mode, route the proxy server endpoint itself as `DIRECT` before SSH, `nc`, or curl tests touch that endpoint.
4. When Snell logs contain `UDP socket send error`, `uv_close`, or `signal 6`, and `systemctl cat snell-server` contains `PrivateDevices`, `ProtectSystem`, `RestrictAddressFamilies`, or empty capability sets, replace the incompatible unit/drop-in before changing Surge UDP settings.
5. Disable or downgrade UDP only when SSH access or service changes are unavailable and the user needs immediate mitigation. Mark the change as mitigation in the final report and include the rollback condition.

## Output

Snell audit commands print facts and warning signals to stdout. They do not mutate remote hosts. They do not choose repairs. Persistent repair commands say what they will change and print one JSON object on stdout. Progress, package-manager output, and raw command diagnostics go to stderr or `log_dir`.

Run local scripts as `bash scripts/<name>.sh` on macOS. Run remote installs with `ssh root@<server> 'bash -s -- ...' < scripts/install_snell_server.sh`. Direct shebang execution can be slower under macOS security and provenance checks.

## Commands

- `scripts/audit_snell_servers.sh`: read-only local SSH audit for one or more Snell VPS hosts. It requires `--server name=ip` or `--server-file path`; no private fleet list is embedded. It prints one JSON object per host to stdout, writes raw per-host logs under `--log-dir`, and exits nonzero when any host has failed checks or SSH/audit failure.
- `scripts/install_snell_server.sh`: **persistent** Debian VPS installer/upgrader. It backs up and replaces `/etc/snell/snell-server.conf` and `/etc/systemd/system/snell-server.service`, may remove incompatible systemd hardening drop-ins, installs `/usr/local/bin/snell-server`, then enables and restarts `snell-server`. It reuses the existing `psk` unless `--psk` supplies a replacement or `--replace-psk` asks the script to generate one. `--dry-run` and successful installs print one JSON object to stdout; progress and errors go to stderr.
- `scripts/stress_surge_policy.sh`: local read-only Surge policy stress probe. It repeats TCP/UDP/NAT/external-IP tests for one policy, optionally runs one download bandwidth diagnostic, prints one summary JSON object to stdout, writes the same object to `log_dir/summary.json`, and stores each raw command stdout/stderr/result under `--log-dir`.

Examples:

```bash
bash scripts/audit_snell_servers.sh --server-file /path/to/snell-servers.txt --journal-since '10 min ago' --snell-version <version>

ssh root@<server-ip> 'bash -s -- --snell-version <version> --name <proxy-name> --port <port>' \
  < scripts/install_snell_server.sh

bash scripts/stress_surge_policy.sh --policy <policy-name> --rounds 40 --parallel 8
```

Check the official Snell release notes before upgrades and pass the chosen version with `--snell-version`. Keep private server lists in a private path supplied by the user. If the user asks to persist a local inventory, store it in the requested private config location.
