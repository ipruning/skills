# macOS Client Reference

Use this for macOS Surge and optional macOS sing-box sidecar.

## Surge Boundary

Surge cannot directly use VLESS REALITY.

Evidence to check when in doubt:

```text
surge-cli --check with a vless line returns:
Error: Unknown proxy type: vless
```

Surge supports HY2 and Snell for this stack. Use:

```text
HY2: native Surge Hysteria2 policy
Snell: existing fallback policy
REALITY: only via local sing-box sidecar exposing SOCKS/Mixed
```

This reference only wires an existing Snell policy into the REALITY + HY2 stack. For
Snell service health, Snell v6 migration, UDP relay/NAT interpretation, or
server repair planning, use the `surge` skill.

## Native Surge HY2 Policy

Policy shape:

```ini
vps-1-hy2 = hysteria2, vps-1.example.com, 443, password=<HY2_PASSWORD>, sni=vps-1.example.com
```

Do not print the password. Redact it in chat and logs.

`download-bandwidth` is optional in Surge and measured in Mbps. Omit it when
there is no measurement. When setting it, use a sustainable value measured on
the current client network with at least three same-endpoint runs; never copy a
value from another hotspot or VPS.

## surge.conf Integration

Expected shape:

```ini
[General]
skip-proxy = ..., 100.64.0.0/10, 203.0.113.10
tun-excluded-routes = 192.168.0.0/16, 10.0.0.0/8, 172.16.0.0/12

[Proxy]
vps-1-hy2 = hysteria2, vps-1.example.com, 443, password=<redacted>, sni=vps-1.example.com

[Proxy Group]
PROXY = select, vps-1-hy2

[Rule]
IP-CIDR,203.0.113.10/32,DIRECT,no-resolve
DOMAIN-SUFFIX,tailscale.com,DIRECT
DOMAIN-SUFFIX,tailscale.io,DIRECT
IP-CIDR,100.64.0.0/10,DIRECT,no-resolve
IP-CIDR6,fd7a:115c:a1e0::/48,DIRECT,no-resolve
PROCESS-NAME,io.tailscale.ipn.macsys.network-extension,DIRECT
PROCESS-NAME,Tailscale,DIRECT

[Host]
*.ts.net = server:100.100.100.100
```

Only when a working Snell policy already exists and the user asks to retain it,
append that existing policy to `[Proxy]` and the group. Preserve its actual
port, version, and options instead of generating new Snell defaults. Snell
health and repair remain owned by the `surge` skill.

Do not copy Linux sing-box Tailscale exclusions into Surge
`tun-excluded-routes`. On macOS Surge, keep ordinary LAN ranges excluded from
VIF, route Tailscale by DIRECT rules, and preserve MagicDNS through
`100.100.100.100`. Verify with `route -n get <tailscale-peer-ipv4>`: a healthy
live route resolves to the Tailscale utun interface, not the Surge VIF.

After editing:

```bash
/Applications/Surge.app/Contents/Applications/surge-cli --check "$HOME/Library/Application Support/Surge/Profiles/surge.conf"
/Applications/Surge.app/Contents/Applications/surge-cli reload
/Applications/Surge.app/Contents/Applications/surge-cli --raw set ProxyGroupSelection.PROXY=vps-1-hy2
```

Validate:

```bash
surge-cli --raw test-policy vps-1-hy2
surge-cli --raw test-policy-external-ip vps-1-hy2
surge-cli --raw test-policy-udp vps-1-hy2
surge-cli --raw environment | jq -r '.environment.ProxyGroupSelection.PROXY'
```

Group-level tests on select groups may return `{}`. Test the concrete policy instead.

## REALITY via Sidecar

Only for macOS, not iOS.

Run sing-box locally with a mixed inbound:

```json
{
  "type": "mixed",
  "tag": "mixed-in",
  "listen": "127.0.0.1",
  "listen_port": 2080
}
```

Surge policy:

```ini
REALITY-via-singbox = socks5, 127.0.0.1, 2080
```

This keeps Surge rules but adds a local dependency. Prefer native HY2/Snell unless the user explicitly wants REALITY through Surge on macOS.
