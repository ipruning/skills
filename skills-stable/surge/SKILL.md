---
name: surge
description: |
  Read-only diagnosis for Surge/Snell failures on the user's macOS Surge path
  and Snell VPS evidence. Use for Snell v5/v6 listener checks, systemd UDP crash
  evidence, local Surge policy smoke tests, macOS Surge DNS/proxy/Enhanced Mode
  failures, and post-audit manual operator action plans. Do not use this Skill
  to change local Surge/macOS network state, apply VPS changes, restart
  services, install software, or tune servers.
---

# Surge

Choose the path before reading references or running commands.

## Surge App-Bundled Skill

Use this route only for ordinary Surge CLI operations that do not involve macOS
network triage, Snell VPS evidence, or local Surge policy smoke tests. Do not
carry a repo-local copy of the Surge app-bundled Skill.

Check the Surge app-bundled Skill:

```bash
test -f /Applications/Surge.app/Contents/Resources/Skills/surge/SKILL.md
```

If the file exists, read
`/Applications/Surge.app/Contents/Resources/Skills/surge/SKILL.md` and follow
the Surge app-bundled Skill. If it does not exist, proceed from the local
`surge-cli` executable that is actually available:

1. `surge-cli` in `PATH`
2. `/Applications/Surge.app/Contents/Applications/surge-cli`

## macOS Surge Network Triage

If the failure is on the user's macOS machine and Surge is active, configured,
named by the user, or plausibly the local proxy or DNS boundary, read
[macOS Surge Network Triage](references/macos-network-triage.md) before
diagnosing or reporting local proxy, DNS, or Enhanced Mode failures.

For ordinary Linux server networking, do not use this Skill for generic OS
triage. Use the server's normal tools and facts.

## Snell VPS Evidence Audit

1. Read [Snell VPS Evidence Audit](references/snell-vps-triage.md) before judging a
   VPS, Snell systemd service, UDP behavior, firewall exposure, proxy sysctls,
   or local Surge policy path to a Snell endpoint.
2. Use `scripts/snell_audit.py` with `uv run --script` to collect evidence.
3. Open `audit.json`. Read `facts`, `findings`, `evidence_paths`, and
   `recommended_manual_actions`.
4. If a repair is needed, run `render-repair-plan --audit <audit.json>`. The
   command prints manual actions. It does not run them.
5. Use `smoke-surge` for local Surge policy smoke tests. It does not touch the
   VPS.

Keep endpoint IPs, PSKs, profile names, and inventories in the user's task or
private config. Audit logs must not contain plaintext Snell PSKs.

## Snell Rules

Use [Snell VPS Evidence Audit](references/snell-vps-triage.md) for Snell v5/v6
listener, UDP, legacy-field, and `Decryption failed` judgment.
