---
name: surge
description: |
  Use for read-only Surge CLI help/output lookups, macOS Surge network triage,
  local Surge policy smoke tests, Snell VPS evidence audits, Snell v5
  UDP/systemd crash evidence, and Snell v6 canary planning. Not for executing
  local Surge/macOS network changes, applying VPS repairs, restarting services,
  installing software, or tuning servers.
---

# Surge

Identify the request type before reading references or running commands: Surge
CLI help/output, local macOS Surge triage, local Surge policy smoke tests, Snell
VPS evidence audit, or Snell v6 canary planning.

## Surge CLI Help And Output

For Surge CLI help or Surge CLI output questions, use the CLI manual or
installed CLI, not macOS network triage. If the request is about Surge CLI
syntax, subcommands, flags, or output interpretation, inspect the app-bundled
Surge documentation if present:

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

If the user asks for a local Surge/macOS toggle or repair, read
[macOS Surge Operator Actions](references/macos-surge-operator-actions.md) and
output a manual command plan. This skill does not execute local network-state
changes.

For non-Surge, non-Snell Linux networking, hand off to `$linux-server` or
`$exe-dot-dev` when available. For Surge/Snell tasks that require VPS state
changes such as firewall rules, sysctls, systemd restarts, package installs, or
server tuning, keep only the evidence audit and manual action plan here; hand
off execution and do not run those server changes from this skill.

## Snell VPS Evidence Audit

1. Read [Snell VPS Evidence Audit](references/snell-vps-triage.md) before judging a
   VPS, Snell systemd service, UDP behavior, firewall exposure, proxy sysctls,
   local Surge policy path, legacy fields, Snell v6 canary planning, or
   `Decryption failed` lines for a Snell endpoint.
2. Use `audit-snell` for one VPS or `audit-fleet` for a host file. Pass
   `--port <snell-port>` unless the endpoint uses the default `14180`:

   ```bash
   uv run --script "$SKILL_DIR/scripts/snell_audit.py" audit-snell \
     --host root@203.0.113.10 \
     --port <snell-port> \
     --out /tmp/surge-snell-runs
   uv run --script "$SKILL_DIR/scripts/snell_audit.py" audit-fleet \
     --hosts ./snell-hosts.txt \
     --port <snell-port> \
     --out /tmp/surge-snell-runs
   ```

3. For `audit-snell`, open the printed `evidence_paths.audit_json` file. For
   `audit-fleet`, read stdout `results[]`, then open each host's
   `results[].evidence_paths.audit_json`. In each audit JSON, read `facts`,
   `findings`, `evidence_paths`, and `recommended_manual_actions`.
4. If findings need a manual action plan, run
   `uv run --script "$SKILL_DIR/scripts/snell_audit.py" render-repair-plan --audit <audit.json>`.
   The command prints JSON with `manual_actions`. It does not run them; a human
   operator or a separate server skill performs any approved change.
5. Use
   `uv run --script "$SKILL_DIR/scripts/snell_audit.py" smoke-surge --policy <policy-name>`
   for local Surge policy smoke tests. It does not touch the VPS.
   In `smoke-surge` output, top-level `status=ok` means all requested probes
   passed; `status=warn` means at least one probe was unsupported. Inspect each
   `results[].status` and `results[].parsed` before calling a policy healthy.

Keep endpoint IPs, PSKs, profile names, and inventories in the user's task or
private config. Do not rely on audit output as a complete secret scrubber unless
a redaction guard has checked the run directory.

For Snell v6 deployment or migration requests, audit the VPS and write a canary
plan first. Hand off VPS changes to `$linux-server` or `$exe-dot-dev`. After the
operator change, run `audit-snell` and `smoke-surge`.
