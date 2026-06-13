# Snell VPS Triage

Surge + Snell incidents start with classification. The failure may sit in Surge routing, the Snell listener, systemd, firewall rules, or the remote outbound path.

## Initial Classification

- `Connection refused` means the target `IP:port` actively rejected the connection: no listener, service crash, wrong port, local firewall `REJECT`, or a mapped/container port issue.
- Timeout is more consistent with routing loss, firewall `DROP`, provider network trouble, or filtering.
- Surge fatal errors can be local-to-proxy failures or remote errors reported back by the Snell server. Do not infer IP blocking from Surge UI text alone.
- `Decryption failed` is not automatically a server failure. It may come from naked TCP probes, wrong PSK clients, stale device configs, scanners, or the operator's own tests.

## Surge Snell-Specific Checks

Collect the Surge baseline first:

```bash
surge-cli --raw environment
surge-cli --raw dump policy
surge-cli --raw dump profile
```

Then test the Snell policy:

```bash
surge-cli --raw test-policy <policy-name>
surge-cli --raw test-policy-udp <policy-name>
surge-cli --raw test-policy-external-ip <policy-name>
surge-cli --raw test-policy-nat-type <policy-name>
```

If a policy returns `{}` or `Policy doesn't exist`, confirm the policy exists in the active profile before treating the remote server as broken.

## Enhanced Mode Pitfall

When Surge enhanced mode or rule mode is active, local CLI tools can be routed through the proxy under test. Before testing or SSHing into a Snell server, route that server endpoint as `DIRECT`.

Add a temporary rule during investigation:

```bash
surge-cli --raw add-temp-rule 'IP-CIDR,<server-ip>/32,DIRECT,no-resolve'
```

Permanent `DIRECT` rules are profile changes. Add one only to the user's own profile after confirming the endpoint belongs to the user's fleet. Keep that fleet inventory in a private path supplied by the user.

## VPS Checks

Run these on the Snell VPS:

```bash
systemctl status snell-server --no-pager
systemctl show snell-server -p ActiveState -p SubState -p NRestarts -p ExecMainStartTimestamp -p LimitNOFILE
systemctl cat snell-server
journalctl -u snell-server -n 200 --no-pager
ss -lntup | awk '/:<port>/ { print }'
ufw status verbose
iptables -S
nft list ruleset
```

Always inspect `systemctl cat`, not just `/etc/systemd/system/snell-server.service`. Drop-ins can keep incompatible hardening active after the main service file is replaced.

## Known Bad Pattern

Snell v5 UDP/QUIC paths can fail under over-aggressive systemd hardening. These log lines identify the failure:

```text
UDP socket send error: invalid argument
uv_close: Assertion `0' failed
signal 6
```

Treat service drop-ins containing directives such as `PrivateDevices`, `ProtectSystem`, `RestrictAddressFamilies`, or empty capability sets as suspect. Verify by comparing the effective unit with `systemctl cat`.

## Stable Service Baseline

Stable baseline for Snell v5 on Debian/systemd:

```ini
[Service]
Type=simple
User=snell
Group=snell
ExecStart=/usr/local/bin/snell-server -c /etc/snell/snell-server.conf
Restart=always
RestartSec=2
LimitNOFILE=1048576
UMask=0077
```

This service keeps privilege separation and restart behavior. It does not add sandboxing that can break Snell v5 UDP/QUIC.

After applying the baseline, run the audit script and inspect each JSONL row. A healthy host has `status` set to `ok` or `warn`, an empty `failed_checks` array, and `values` containing `active=active`, `sub=running`, `tcp_listen=yes`, `udp_listen=yes`, `hardening_mentions=0`, and `udp_crash_markers=0`.

## Commands

For upgrade work, check the official [Snell release notes](https://kb.nssurge.com/surge-knowledge-base/release-notes/snell), choose the target version, and pass it through `--snell-version`.

Audit stdout carries JSON facts, `failed_checks`, and warning signals. Raw logs stay behind `log_path`. Repairs stay in separate persistent commands.

Install or upgrade a server while preserving the existing PSK. **Persistent**: the script backs up and replaces the Snell config and systemd service, may remove incompatible hardening drop-ins, enables `snell-server`, and restarts the service. Stdout is one JSON object; progress and errors go to stderr.

```bash
ssh root@<server-ip> 'bash -s -- --snell-version <version> --name <proxy-name> --port <port>' \
  < scripts/install_snell_server.sh
```

Audit a private fleet supplied by the user. The audit is read-only on remote hosts. Stdout is JSON Lines, one host per line. The command exits nonzero when any host has `status=issue` or `status=fail`.

```bash
bash scripts/audit_snell_servers.sh --server-file /path/to/snell-servers.txt --journal-since '10 min ago' --snell-version <version>
```

Stress a configured Surge policy from the local Mac. This is read-only for Surge and the VPS, but it generates proxy traffic. Stdout is one summary JSON object; the same object is written to `log_dir/summary.json`; each raw command stdout/stderr/result is stored under `log_dir`.

```bash
bash scripts/stress_surge_policy.sh --policy <policy-name> --rounds 40 --parallel 8
```

Use `--bandwidth-download` only when extra traffic is acceptable. Surge may return only a completion marker for bandwidth diagnostics. Treat the per-command raw logs as evidence of the test path, not as a reliable throughput measurement.

Server file formats:

```text
proxy-a 203.0.113.10
proxy-b=203.0.113.11
```

The audit records raw host output in `log_path`. The JSON row contains derived `failed_checks` plus raw `values`; use `values.apt_duplicate_sources=1` as a signal for manual apt source cleanup instead of letting the audit command mutate remote files.

## Decryption Failed Handling

Before banning IPs for `Decryption failed`, compare the source list against the operator's current direct egress and SSH source:

```bash
surge-cli --raw test-policy-external-ip DIRECT
ssh root@<server-ip> 'printf "%s\n" "$SSH_CONNECTION"'
journalctl -u snell-server --since '10 min ago' --no-pager |
  awk '/Decryption failed/ { count[$NF]++ } END { for (ip in count) print count[ip], ip }' |
  sort -nr
```

Do not add fail2ban or firewall bans if the source could be the operator, a roaming device, or a naked port test. Report it as a warning unless it causes load, resource exhaustion, or confirmed abuse.

## Common Tooling Pitfalls

- macOS `/bin/bash` is 3.2. Keep bash scripts compatible with bash 3.2 and avoid `xargs -r`, `grep -P`, `readlink -f`, `date -d`, `timeout`, and bare `sed -i`.
- On macOS, run local scripts as `bash scripts/<name>.sh` for dry-runs and audits. Direct shebang execution can be slower under local security/provenance checks.
- In zsh, `set -- $row` does not behave like bash word splitting. Use `while read -r name ip`.
- When auditing systemd hardening, ignore comments in `systemctl cat` output.
- Some Surge CLI tests can hang for a policy. Run targeted tests and clean up stuck processes before continuing.
