# Testing Reference

Use this for performance interpretation and end-to-end validation.

## Do Not Mix Test Surfaces

Separate:

```text
Server raw baseline:
  VPS -> Speedtest server

Protocol/client test:
  Client -> proxy protocol -> VPS -> target

Surge policy test:
  Surge policy -> target

Linux TUN test:
  system traffic -> sing-box TUN -> proxy protocol -> VPS -> target
```

Do not infer client proxy performance from server raw speed alone.
Do not accept env-proxy tests as final Linux TUN proof. Final Linux evidence
must clear proxy env and use `--noproxy "*"`.

## Server Raw Baseline

Install official Ookla speedtest if needed:

```bash
curl -fsSL https://packagecloud.io/install/repositories/ookla/speedtest-cli/script.deb.sh -o /tmp/ookla-speedtest-install.deb.sh
bash /tmp/ookla-speedtest-install.deb.sh
apt-get remove -y speedtest-cli || true
apt-get install -y speedtest
```

Run:

```bash
speedtest --accept-license --accept-gdpr --progress=no --format=json-pretty --server-id=12191
```

Known 2026-07-05 baseline for `203.0.113.10` to Nitel Los Angeles:

```text
download 8425.88 Mbps
upload   7048.04 Mbps
ping     0.839 ms
```

This proves the VPS was not the bottleneck during that run.

## Surge Speedtest CLI

Use Ookla CLI on macOS:

```bash
brew tap teamookla/speedtest
brew trust teamookla/speedtest
brew install teamookla/speedtest/speedtest
```

List servers:

```bash
speedtest --accept-license --accept-gdpr -L
```

Useful server IDs from the deployment:

```text
12191 Nitel Los Angeles
69322 Race Communications Los Angeles
```

Before each run, set the desired Surge policy:

```bash
surge-cli --raw set ProxyGroupSelection.PROXY=vps-1-hy2
speedtest --accept-license --accept-gdpr --progress=no --format=json-pretty --server-id=12191

surge-cli --raw set ProxyGroupSelection.PROXY=vps-1
speedtest --accept-license --accept-gdpr --progress=no --format=json-pretty --server-id=12191
```

Known 2026-07-05 results on hotspot:

```text
HY2  -> Nitel: 356.53 down / 75.48 up / 195.71 ms
Snell -> Nitel: 464.82 down / 67.15 up / 156.72 ms
Snell -> Race: 465.15 down / 65.49 up / 176.12 ms
```

Interpretation:

```text
On that hotspot path, Snell was faster than Surge HY2.
Linux should still default to REALITY for stability.
HY2 remains a useful UDP fallback but not proven fastest on that path.
```

## Linux Protocol Tests

Use mixed configs only as protocol smoke tests:

```bash
sing-box run -c client-mixed.json
curl -fsS4 --proxy socks5h://127.0.0.1:2080 https://api.ipify.org
```

The durable Linux check is TUN without proxy env:

```bash
env -u http_proxy -u https_proxy -u all_proxy -u no_proxy \
  -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u NO_PROXY \
  curl -fsS4 --noproxy "*" https://api.ipify.org
env -u http_proxy -u https_proxy -u all_proxy -u no_proxy \
  -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u NO_PROXY \
  curl -fsSIL4 --noproxy "*" https://www.google.com | sed -n '1,5p'
journalctl -u sing-box@<name>.service --no-pager -n 80 \
  | grep -E 'inbound/tun|dns: exchanged|outbound/vless|outbound/hysteria2'
```

If headers include `HTTP/1.1 200 Connection established`, the sample used an
HTTP proxy and is not TUN evidence.

Use fixed file curl tests only as supporting evidence, not as final Speedtest proof:

```bash
curl --proxy socks5h://127.0.0.1:2080 \
  -o /dev/null \
  -sS \
  -w 'download_mbps=%{speed_download}\n' \
  http://speedtest.lax1.nitelusa.net/speedtest/random4000x4000.jpg
```

Convert bytes/sec to Mbps:

```text
Mbps = speed_download * 8 / 1000000
```

## Failure Interpretation

- `Cannot read` or `Cannot write` from Ookla CLI is a failed sample, not throughput evidence.
- A changed Speedtest server can explain large differences. Compare same protocol on the same server.
- A server raw multi-gigabit result does not mean the client hotspot can achieve multi-gigabit proxy speed.
- HY2 over UDP may underperform on hotspot or lossy paths even when VPS bandwidth is excellent.

## Live SOP Cross-Validation

Use this when the user asks whether the SOP or generated configs match the live VPS. This is read-only and must not print secrets.

Server audit:

```bash
ssh root@<SERVER_IP> 'bash -s' <<'REMOTE'
set -euo pipefail
hostname
date -Is
sing-box version | head -8
printf 'sing-box active='; systemctl is-active sing-box
printf 'sing-box enabled='; systemctl is-enabled sing-box
printf 'snell active='; systemctl is-active snell-server 2>/dev/null || true
printf 'certbot.timer active='; systemctl is-active certbot.timer 2>/dev/null || true
sing-box check -c /etc/sing-box/config.json >/tmp/singbox-check.out 2>/tmp/singbox-check.err && echo 'sing-box check ok' || (cat /tmp/singbox-check.err; exit 1)
stat -c '%a %U:%G %n' /etc/sing-box/config.json /root/sing-box-secrets.txt
cut -d= -f1 /root/sing-box-secrets.txt | sed '/^$/d'
jq '{
  inbounds: [.inbounds[] | {
    tag: .tag,
    type: .type,
    listen: .listen,
    listen_port: .listen_port,
    users_len: ((.users // []) | length),
    user_name: (.users[0].name // null),
    user_flow: (.users[0].flow // null),
    has_uuid: (((.users[0].uuid // "") | length) > 0),
    has_password: (((.users[0].password // "") | length) > 0),
    tls_server_name: (.tls.server_name // null),
    reality_enabled: (.tls.reality.enabled // false),
    reality_handshake_server: (.tls.reality.handshake.server // null),
    reality_handshake_port: (.tls.reality.handshake.server_port // null),
    has_reality_private_key: (((.tls.reality.private_key // "") | length) > 0),
    short_id_len: ((.tls.reality.short_id // []) | length),
    max_time_difference: (.tls.reality.max_time_difference // null),
    certificate_path: (.tls.certificate_path // null),
    key_path: (.tls.key_path // null),
    masquerade_type: (.masquerade.type // null),
    masquerade_url: (.masquerade.url // null),
    masquerade_rewrite_host: (.masquerade.rewrite_host // null)
  }],
  outbounds: [.outbounds[] | {tag: .tag, type: .type}],
  route: .route
}' /etc/sing-box/config.json
ss -lntup | grep -E ':(443|14180)\b' || true
ss -lnup | grep -E ':443\b' || true
ufw status verbose | grep -E 'Status:|Default:|22/tcp|80/tcp|443/tcp|443/udp|14180/tcp|8443/udp' || true
certbot certificates 2>/dev/null | grep -E 'Certificate Name:|Domains:|Expiry Date:' || true
test -x /etc/letsencrypt/renewal-hooks/deploy/restart-sing-box.sh && echo 'renew hook present' || echo 'renew hook missing'
REMOTE
```

Client config audit, redacted:

```bash
jq '{
  selector: (.outbounds[] | select(.type == "selector") | {tag, default, outbounds}),
  vless: (.outbounds[] | select(.tag == "vless-reality-out") | {
    server, server_port, flow, network,
    tls_server_name: .tls.server_name,
    utls: .tls.utls,
    reality_enabled: .tls.reality.enabled,
    has_public_key: ((.tls.reality.public_key // "") | length > 0),
    short_id_len: ((.tls.reality.short_id // "") | length)
  }),
  hy2: (.outbounds[] | select(.tag == "hy2-h3-out") | {
    server, server_port,
    has_password: ((.password // "") | length > 0),
    tls_server_name: .tls.server_name
  }),
  route: .route
}' <client-config.json>
```

Expected live shape for the 2026-07-05 deployment:

```text
server: vps-1 / 203.0.113.10
sing-box: 1.13.14 active and enabled
TCP/443: vless-reality-in, xtls-rprx-vision, REALITY enabled, SNI www.apple.com
UDP/443: hy2-h3-in, certificate for vps-1.example.com, masquerade proxy to https://www.apple.com
Snell: TCP/14180 active only as Surge fallback
client HY2: server 203.0.113.10, tls.server_name vps-1.example.com
Linux TUN: default_domain_resolver present, rule order sniff -> hijack-dns -> private direct
Linux workstation final mode: sing-box@<name>.service active/enabled, singtun0 present, no HTTP_PROXY/ALL_PROXY defaults, old Clash/Mihomo absent
Surge: syntax OK; HY2 policy direct to vps-1.example.com:443; Snell fallback to 203.0.113.10:14180
```
