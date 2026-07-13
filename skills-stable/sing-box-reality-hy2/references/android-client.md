# Android Client Reference

Use this for SFA / sing-box for Android configs and Tailscale coexistence.

## Default Shape

Resolve values and their authorized source through
[client-inputs.md](client-inputs.md) before importing a profile.

Import the outbounds and selector from the Linux mixed profile in
[linux-client.md](linux-client.md). Keep its REALITY default, HY2 fallback,
`ipv4_only` DNS baseline, and omission of guessed HY2 bandwidth values.

For ordinary on-device SFA, omit Linux's `auto_redirect`. The field is not
strictly Linux-only: the validated baseline supports limited IPv4 TCP
forwarding with it on Android, but Android has no nftables or ip6tables. Use it
only for a tested hotspot or repeater forwarding setup, not as the phone
default. The source version is pinned in
[version-compatibility.md](version-compatibility.md).

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

## Validation

1. Import the profile and require SFA to start without schema, REALITY, or TLS
   errors.
2. Select `vless-reality-out`; require an external-IP page to return the VPS
   egress and inspect the SFA log for both TCP and UDP traffic.
3. Select `hy2-h3-out`; repeat the external-IP check and require no certificate
   or authentication error.
4. Verify expected DNS behavior, local-LAN access, and app exclusions on the
   actual device network.
5. When Tailscale matters, test the two VPN modes separately. Do not report
   coexistence unless both the named tailnet peer and MagicDNS work while SFA is
   active.
