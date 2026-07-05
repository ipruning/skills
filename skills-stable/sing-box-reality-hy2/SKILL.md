---
name: sing-box-reality-hy2
description: >-
  Deploy, repair, and validate a narrow sing-box stable proxy stack: VLESS
  REALITY Vision on TCP/443 plus Hysteria2 on UDP/443. Use when the user gives
  a VPS IP, SSH host, domain, or existing server and wants server setup, client
  config, certbot/Cloudflare DNS, VPS-to-VPS or local tests, or REALITY/HY2
  performance diagnosis. Linux/VPS clients should converge to system-level
  sing-box TUN; mixed is only a smoke test. Also use when migrating Linux away
  from Clash/Mihomo or shell proxy exports. macOS uses Surge HY2/Snell or a
  sing-box sidecar; Windows uses sing-box-compatible configs. For standalone
  Surge/Snell audits, use the surge skill.
---

# Sing Box REALITY HY2

Deploy the narrow REALITY + HY2 stack. Do not turn this into a proxy panel, all-protocol bundle, or long-lived environment-variable proxy setup.

## Route

Identify the requested surface and read only the matching reference:

- Server setup or repair: read `references/server.md`.
- Linux/VPS client setup, testing, or migration from Clash/Mihomo/shell exports:
  read `references/linux-client.md`.
- macOS/Surge setup or testing: read `references/macos-client.md`.
- Android/SFA setup or Tailscale coexistence: read `references/android-client.md`.
- Windows client config or testing: read `references/windows-client.md`.
- Performance interpretation or speed testing: read `references/testing.md`.
- SOP drift checks or "does the doc match the server": read `references/testing.md`
  and run the live redacted cross-check.
- Standalone Surge triage, Snell audits, Snell v6 canary planning, and Snell
  repair plans belong to `$surge`.

When inputs are missing, ask only for the blocker:

- Server setup needs SSH access, `SERVER_IP`, a DNS-only `HY2_DOMAIN`, and a
  reachable `REALITY_SNI` or permission to use the default.
- Client setup needs server secrets or SSH access to read them from the server.
- Certbot can run without email only if the user accepts that tradeoff; create a
  reminder to add email later.

If the request touches more than one surface, execute in this order:

1. Server.
2. Linux/mixed smoke test.
3. Linux systemd TUN.
4. Remove old Linux proxy daemons, shell export hooks, and temporary mixed
   fallback unless the user explicitly wants to keep them.
5. macOS Surge or Windows client config.
6. Speed tests and policy selection.

## Hard Rules

- Use `sing-box` stable from the official Sagernet APT repo. Do not install `sing-box-beta`.
- Baseline is `sing-box 1.13.x`. Do not use fields documented as `1.14.0 alpha`
  or `1.14.0 changes` unless the user explicitly asks to migrate after stable
  support exists.
- Avoid panels and all-in-one scripts for production. Use auditable config files and systemd.
- Never print secrets in chat. Redact password fields, PSK fields, UUIDs only when they are not needed, REALITY private keys, and HY2 passwords.
- Use `sing-box check` before every restart.
- Use `sing-box format -w` only after `check` passes.
- Keep SSH reachable before firewall, TUN, or route changes.
- Do not start Linux TUN over SSH unless there is a rollback or temporary test host.
- Do not leave `HTTP_PROXY`, `HTTPS_PROXY`, or `ALL_PROXY` exports as the
  default Linux experience after TUN works. Env proxy is a temporary smoke-test
  tool, not the final setup.
- When validating docs against a live server, inspect runtime state and redacted config fields. Do not rely on prior memory alone.

## Defaults

- REALITY SNI/handshake host: stable TLS 1.3 site reachable from VPS, such as `www.apple.com`.
- HY2 domain: Cloudflare DNS-only `A` record to the VPS IPv4. No orange cloud. No AAAA unless IPv6 is verified.
- HY2 outbound should dial `SERVER_IP`; TLS `server_name` should be `HY2_DOMAIN`.
- Linux selector default: `vless-reality-out`.
- Linux full-device default: systemd `sing-box@<name>.service` running a TUN config from `/etc/sing-box/<name>.json`.
- Linux workstation TUN DNS default: `ipv4_only`, unless IPv6 has been
  verified across DNS, routing, and package mirrors. `prefer_ipv4` still exposes
  AAAA answers to applications and is not enough for Arch/Omarchy package
  updates.
- If SSH reaches the host through Tailscale, add the Tailscale IPv4/IPv6 ranges
  listed in `references/linux-client.md` to TUN route exclusions before enabling
  TUN.
- Tailscale handling is platform-specific. Linux sing-box TUN should exclude
  Tailscale ranges in `route_exclude_address`; macOS Surge should keep
  Tailscale DIRECT and MagicDNS working, but should not copy those ranges into
  Surge `tun-excluded-routes` without a live route test.
- Windows starts from mixed mode to avoid route conflicts; full-device Windows
  TUN must be adapted to the named client and verified against Tailscale routes.
- Android/SFA and Tailscale both use Android VPN service semantics; do not
  promise simultaneous full-device VPN operation unless the specific client and
  device prove it.
- Surge should use HY2 first for this stack and keep Snell as fallback. Surge
  protocol limits do not change the Linux/Android design.

## Done Criteria

Do not call the deployment done until these pass:

```text
Server:
  sing-box check
  systemctl is-active sing-box
  ss shows TCP/443 and UDP/443 owned by sing-box
  certbot certificate exists for HY2_DOMAIN

Linux client:
  mixed REALITY returns VPS IP from api.ipify.org when doing a protocol smoke test
  mixed HY2 returns VPS IP from api.ipify.org when doing a protocol smoke test
  systemd TUN service is active and enabled
  fresh bash/zsh shells have no HTTP_PROXY / HTTPS_PROXY / ALL_PROXY defaults
  curl --noproxy "*" returns the VPS IP without proxy env
  Arch/Omarchy mirrors return HTTP 200 without proxy env and resolve to IPv4-only unless IPv6 is intentionally enabled
  logs show inbound/tun, dns exchanged, and outbound/vless by default
  old Clash/Mihomo services, ports, /opt/clash, and shell watch_proxy hooks are absent after migration

macOS Surge:
  surge-cli --check profile
  test-policy-external-ip returns VPS IP
  test-policy-udp returns a response for HY2
```

## Field Notes

- Linux TUN config must include `route.default_domain_resolver`.
- Linux TUN route rules must put `{ "action": "sniff" }` before DNS hijack, or DNS to the TUN peer can fail.
- If Linux TUN package updates fail with TLS EOF while `curl -4` succeeds,
  treat leaked AAAA/IPv6 as the first suspect. Set DNS `strategy` to
  `ipv4_only`, restart sing-box, and verify mirror hosts resolve to IPv4-only.
  This is the Linux equivalent of Surge `ipv6 = false`.
- For Linux workstations, the durable endpoint is TUN, not `export
  ALL_PROXY=...`. Mixed mode is only a smoke test and should be removed or left
  manual once TUN is active.
- For Tailscale SSH paths, verify the tailnet peer route after TUN starts. On
  Linux, `ip route get <tailscale-ip>` should resolve to `tailscale0`; on macOS
  Surge, `route -n get <tailscale-ip>` should resolve to the Tailscale utun, not
  the Surge VIF.
- When cleaning an old Clash/Mihomo host, remove the daemon, `/opt/clash`,
  `7890/7891/9090` listeners, shell `watch_proxy` hooks, and stale user-level
  sing-box subscription/dashboard configs before calling the migration done.
- A valid server config may render `"max_time_difference": "1m0s"` after `sing-box format`; treat it as equivalent to `1m`.
