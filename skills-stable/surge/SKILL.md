---
name: surge
description: |
  Read-only diagnosis for Surge/Snell failures on the user's macOS Surge path
  and Snell VPS evidence. Use for Snell v5/v6 listener checks, systemd UDP crash
  evidence, local Surge policy smoke tests, macOS Surge DNS/proxy/Enhanced Mode
  failures, and post-audit manual operator action plans. Not for changing local
  Surge/macOS network state, applying VPS changes, restarting services,
  installing software, or tuning servers.
---

# Surge

Identify the request type before reading references or running commands: Surge
CLI help, local macOS Surge triage, or Snell VPS evidence.

## Surge CLI Help And Output

Surge CLI help and CLI output questions need the CLI manual or installed CLI,
not macOS network triage. When the request does not involve macOS network
triage, Snell VPS evidence, or local Surge policy smoke tests, inspect the
app-bundled Surge documentation if present:

```bash
test -f /Applications/Surge.app/Contents/Resources/Skills/surge/SKILL.md
```

If that file is unavailable, answer from the `surge-cli` executable that is
actually available in `PATH` or at
`/Applications/Surge.app/Contents/Applications/surge-cli`.

## macOS Surge Network Triage

If the failure is on the user's macOS machine and Surge is active, configured,
named by the user, or plausibly the local proxy or DNS boundary, read
[macOS Surge Network Triage](references/macos-network-triage.md) before
diagnosing or reporting local proxy, DNS, or Enhanced Mode failures.

For non-Surge, non-Snell Linux networking, or any task that changes VPS state
such as firewall rules, sysctls, systemd restarts, package installs, or server
tuning, hand off to `$linux-server` or `$exe-dot-dev` when available. Pass audit
evidence and manual action plans, but do not run those server changes here.

## Snell VPS Evidence Audit

1. Read [Snell VPS Evidence Audit](references/snell-vps-triage.md) before judging a
   VPS, Snell systemd service, UDP behavior, firewall exposure, proxy sysctls,
   local Surge policy path, legacy fields, or `Decryption failed` lines for a
   Snell endpoint.
2. Use `audit-snell` for one VPS or `audit-fleet` for a host file:

   ```bash
   uv run --script "$SKILL_DIR/scripts/snell_audit.py" audit-snell --host root@203.0.113.10 --out /tmp/surge-snell-runs
   uv run --script "$SKILL_DIR/scripts/snell_audit.py" audit-fleet --hosts ./snell-hosts.txt --out /tmp/surge-snell-runs
   ```

3. Open `audit.json`. Read `facts`, `findings`, `evidence_paths`, and
   `recommended_manual_actions`.
4. If a repair is needed, run
   `uv run --script "$SKILL_DIR/scripts/snell_audit.py" render-repair-plan --audit <audit.json>`.
   The command prints manual actions. It does not run them.
5. Use
   `uv run --script "$SKILL_DIR/scripts/snell_audit.py" smoke-surge --policy <policy-name>`
   for local Surge policy smoke tests. It does not touch the VPS.

Keep endpoint IPs, PSKs, profile names, and inventories in the user's task or
private config. Audit logs must not contain plaintext Snell PSKs.
