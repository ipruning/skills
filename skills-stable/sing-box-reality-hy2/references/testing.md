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

Prefer an already installed Ookla CLI. Installing a remote repository shell
script as root is an explicit opt-in: inspect the current official installation
instructions and script before running it. Speedtest is not a deployment
dependency.

Run:

```bash
speedtest --accept-license --accept-gdpr --progress=no --format=json-pretty --server-id=<server-id>
```

Record timestamp, server ID, latency, download, upload, packet loss, VPS region,
and provider. A raw baseline only describes that run.

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

Before each run, set the desired Surge policy:

```bash
surge-cli --raw set ProxyGroupSelection.PROXY=vps-1-hy2
speedtest --accept-license --accept-gdpr --progress=no --format=json-pretty --server-id=<server-id>

surge-cli --raw set ProxyGroupSelection.PROXY=REALITY-via-singbox
speedtest --accept-license --accept-gdpr --progress=no --format=json-pretty --server-id=<server-id>
```

Compare policies on the same client network, Speedtest server, concurrency,
Surge mode, and time window. Keep raw results outside this shared skill; a
single hotspot result is not a reusable default.

## Controlled Protocol Comparison

When third-party speed endpoints change servers, rate-limit, or reject the VPS
egress, use a temporary HTTP service bound to the proxy server's loopback. A
SOCKS request for `127.0.0.1:<port>` can reach it only after authenticating to
REALITY or HY2, while the payload avoids a second Internet path.

On the proxy server, create a temporary fixed-size file and a time-bounded
loopback service:

```bash
install -d -m 700 /tmp/singbox-protocol-bench
truncate -s 134217728 /tmp/singbox-protocol-bench/blob.bin
systemd-run \
  --unit=singbox-protocol-bench \
  --property=RuntimeMaxSec=300 \
  --property=WorkingDirectory=/tmp/singbox-protocol-bench \
  /usr/bin/python3 -m http.server 18080 --bind 127.0.0.1
```

Run separate mixed clients on separate loopback ports, then collect at least
three samples per variant:

```bash
curl --proxy socks5h://127.0.0.1:<mixed-port> \
  --connect-timeout 15 --max-time 90 \
  -fsS -o /dev/null \
  -w 'code=%{http_code} bytes=%{size_download} time=%{time_total} speed_Bps=%{speed_download}\n' \
  http://127.0.0.1:18080/blob.bin
```

Compare medians, not the best sample. For HY2, compare omitted bandwidth values
against one conservative Brutal candidate only on a fixed link. While each
download runs, measure latency to the local gateway; a throughput increase that
materially worsens latency or loss is not a better default. Stop the transient
unit and delete the test file when finished.

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
env -u http_proxy -u https_proxy -u all_proxy -u no_proxy \
  -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u NO_PROXY \
  curl --http3-only -m 25 -fsS -o /dev/null \
  -w 'http3=%{http_code} remote=%{remote_ip}\n' \
  --noproxy "*" https://cloudflare-quic.com/
journalctl -u sing-box@<name>.service --no-pager -n 80 \
  | grep -E 'inbound/tun|dns: exchanged|outbound/vless|outbound/hysteria2|UDP is not supported'
```

With selector default `vless-reality-out`, HTTP/3 must succeed and the journal
must show a VLESS packet connection. This is the regression test for an
accidental `"network": "tcp"` restriction. Then select `hy2-h3-out`, repeat the
same target, and require a Hysteria2 packet connection.

If headers include `HTTP/1.1 200 Connection established`, the sample used an
HTTP proxy and is not TUN evidence.

Use fixed file curl tests only as supporting evidence, not as final Speedtest proof:

```bash
curl --proxy socks5h://127.0.0.1:2080 \
  -o /dev/null \
  -sS \
  -w 'download_mbps=%{speed_download}\n' \
  http://<speedtest-mirror>/speedtest/random4000x4000.jpg
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
- HY2 with omitted `up_mbps` / `down_mbps` uses automatic BBR in `v1.13.14`; a fixed Brutal value is a per-link optimization, not a portable default.
- A low global UDP sysctl value is not proof of a small sing-box socket. Inspect `ss -u -a -m -p` and UDP error counters during an active HY2 transfer before tuning it.
- `UDP is not supported by outbound: proxy` with VLESS selected means the selected VLESS outbound was restricted to TCP; omit `network` to restore the `v1.13.14` TCP+UDP default.
- `icmp is not supported by default outbound: proxy` means TUN ICMP reached the selector. Add an explicit ICMP direct or reject rule; VLESS and HY2 do not carry it.
- `inactive (dead)`, exit status 0, and a journal line saying `Stopped sing-box service` prove a clean external stop, not a crash. Inspect timers, test harnesses, and operator actions before changing the config.

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
printf 'certbot.timer enabled='; systemctl is-enabled certbot.timer 2>/dev/null || true
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
    short_id_count: ((.tls.reality.short_id // []) | length),
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
systemctl is-enabled certbot.timer 2>/dev/null || true
systemctl is-active certbot.timer 2>/dev/null || true
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
    short_id_hexlen: ((.tls.reality.short_id // "") | length)
  }),
  hy2: (.outbounds[] | select(.tag == "hy2-h3-out") | {
    server, server_port,
    has_password: ((.password // "") | length > 0),
    tls_server_name: .tls.server_name
  }),
  route: .route
}' <client-config.json>
```

Expected live shape for a verified deployment:

```text
server: vps-1 / 203.0.113.10
sing-box: 1.13.14, active and enabled for this template version
TCP/443: vless-reality-in, xtls-rprx-vision, REALITY enabled, validated REALITY_SNI
UDP/443: hy2-h3-in, certificate for vps-1.example.com, validated masquerade target
Snell: present only when it already existed and the user asked to retain it
client HY2: server 203.0.113.10, tls.server_name vps-1.example.com
Linux VLESS: network omitted, TCP and UDP enabled, uTLS present for REALITY on v1.13.14
Linux HY2: up_mbps/down_mbps omitted by default; measured Brutal values are client-specific
Linux TUN: warn logs; selector excludes direct; rule order ICMP direct -> optional tailscaled direct -> sniff -> hijack-dns -> private direct
Linux workstation final mode: sing-box@<name>.service active/enabled, singtun0 present, no HTTP_PROXY/ALL_PROXY defaults, old Clash/Mihomo absent
Surge: syntax OK; HY2 policy direct to vps-1.example.com:443; optional existing Snell fallback only when requested
```
