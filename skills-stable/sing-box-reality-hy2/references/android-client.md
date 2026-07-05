# Android Client Reference

Use this for SFA / sing-box for Android configs and Tailscale coexistence.

## Default Shape

Android should import the same sing-box outbounds as Linux:

- Selector default: `vless-reality-out`.
- HY2 available as `hy2-h3-out`.
- DNS strategy: `ipv4_only` unless IPv6 is verified on the device network.
- Remove Linux-only `auto_redirect`.

## Tailscale Boundary

Treat Android differently from Linux and macOS. On stock Android, full-device
SFA and the Tailscale app both rely on Android VPN service semantics, so do not
promise they can both run as active full-device VPNs at the same time.

Best default:

```text
If Tailscale access is required on Android:
  keep Tailscale as the active VPN
  do not enable full-device SFA at the same time

If REALITY/HY2 full-device proxy is required on Android:
  run SFA as the active VPN
  do not assume Tailscale peers or MagicDNS will be available from that device
```

If a user names a specific Android client, device ROM, or work profile that
claims VPN coexistence, verify live behavior before calling it supported:

```text
Tailscale app status
SFA profile active state
access to a 100.64.0.0/10 peer
resolution of *.ts.net
external IP through selected proxy
```

Do not copy Linux `route_exclude_address` guidance here. Android VPN ownership
is controlled by the platform and client app, not by the same systemd TUN route
model used on Linux.
