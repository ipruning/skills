# Windows Client Reference

Use this for Windows client config generation and smoke tests. Linux remains
the primary client path; Windows support should reuse the same sing-box
outbounds and avoid inventing a separate protocol plan.

## Recommended Shape

Resolve values and their authorized source through
[client-inputs.md](client-inputs.md) before rendering the profile.

Start with mixed mode:

```text
127.0.0.1:2080 mixed inbound
selector default vless-reality-out
hy2-h3-out available as fallback
```

Use the complete Linux mixed profile in [linux-client.md](linux-client.md) as
the outbound source of truth. Windows adds no protocol-specific fields.

Mixed mode is also the safest Tailscale-compatible default on Windows because
it does not install system routes or compete with the Tailscale adapter.

## Validation

If the Windows host has sing-box CLI:

```powershell
sing-box.exe check -c .\client-mixed.json
sing-box.exe run -c .\client-mixed.json
curl.exe -fsS4 --proxy socks5h://127.0.0.1:2080 https://api.ipify.org
```

Require `SERVER_IP`, stop the process, change the selector default to
`hy2-h3-out`, and repeat. Both outbounds must pass before the profile is called
valid.

## Full-Device Routing

Do not assume Windows TUN service semantics from the Linux TUN reference.
Generate the mixed config first. If the user names a Windows client that
supports importing sing-box JSON and managing TUN, adapt the outbound section
and let that client own the Windows network state.

Ask for the specific Windows client name when the user wants full-device
routing and has not provided one.

For Tailscale coexistence, verify instead of assuming:

```powershell
tailscale status
route print
Get-NetRoute -DestinationPrefix 100.64.0.0/10 -ErrorAction SilentlyContinue
Resolve-DnsName <tailnet-host>.ts.net -ErrorAction SilentlyContinue
Test-NetConnection <tailscale-peer-ipv4>
```

The healthy Windows shape is that tailnet routes remain owned by Tailscale, and
MagicDNS still resolves through Tailscale. If the named Windows proxy client
supports route exclusions, exclude `100.64.0.0/10` and
`fd7a:115c:a1e0::/48`; otherwise keep Windows on mixed mode.
