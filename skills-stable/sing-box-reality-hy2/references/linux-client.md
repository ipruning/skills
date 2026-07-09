# Linux / VPS Client Reference

Use this for Linux clients, Linux workstations, and VPS-to-VPS testing.
The durable target for a workstation or dedicated client is system-level TUN.
Mixed mode is the default for a business VPS or multi-service host because TUN
changes every service's DNS, egress, and return path. Use TUN on those hosts only
after the user approves that blast radius.

## Install

On Debian/Ubuntu, use the same official APT repo as the server:

```bash
mkdir -p /etc/apt/keyrings
curl -fsSL https://sing-box.app/gpg.key -o /etc/apt/keyrings/sagernet.asc
chmod a+r /etc/apt/keyrings/sagernet.asc
cat >/etc/apt/sources.list.d/sagernet.sources <<'EOF'
Types: deb
URIs: https://deb.sagernet.org/
Suites: *
Components: *
Enabled: yes
Signed-By: /etc/apt/keyrings/sagernet.asc
EOF
apt-get update
package_version="$(apt-cache madison sing-box | awk '$3 == "1.13.14" { print $3; exit }')"
test -n "$package_version"
apt-get install -y "sing-box=$package_version" curl jq
apt-mark hold sing-box
sing-box version
```

On Arch Linux, prefer the distro package if it provides `sing-box` with
`with_utls` and a systemd `sing-box@.service`:

```bash
pacman -Qi sing-box
sing-box version
systemctl cat sing-box@.service
```

The Arch package must report `v1.13.14` before this template is applied. If the
distribution package has crossed a stable major version, stop and refresh the
template against that version instead of forcing old JSON into the new core.

For `v1.13.14`, REALITY client code explicitly requires `with_utls` and
`utls.enabled=true`; a build without it fails initialization. This is a
REALITY implementation requirement for this version even though current
sing-box documentation discourages generic uTLS fingerprinting. Recheck this
constraint when crossing stable versions.

## Mixed Smoke Test Config

Use mixed first only as a short smoke test. It avoids route takeover while
proving credentials and protocol reachability.

Do not make shell exports the default Linux setup. Avoid persistent
`HTTP_PROXY`, `HTTPS_PROXY`, or `ALL_PROXY` blocks in `.bashrc`, `.zshrc`, or
profile files once TUN works.

Important client rules:

- VLESS outbound dials `SERVER_IP`.
- VLESS TLS uses `server_name = REALITY_SNI`.
- VLESS REALITY uses `public_key` and `short_id`.
- Include `tls.utls` with Chrome fingerprint.
- Omit VLESS `network`; `v1.13.14` enables TCP and UDP by default. `"network":
  "tcp"` disables UDP.
- HY2 outbound dials `SERVER_IP`.
- HY2 TLS uses `server_name = HY2_DOMAIN`.
- Omit HY2 `up_mbps` and `down_mbps` by default. This selects automatic BBR
  instead of a guessed Brutal rate.
- Keep `direct` as a routing outbound, but do not include it in the user-facing
  selector.
- Include `route.default_domain_resolver`.

Skeleton:

```json
{
  "log": {
    "level": "warn",
    "timestamp": true
  },
  "dns": {
    "servers": [
      {
        "type": "local",
        "tag": "dns-local"
      }
    ],
    "final": "dns-local",
    "strategy": "ipv4_only"
  },
  "inbounds": [
    {
      "type": "mixed",
      "tag": "mixed-in",
      "listen": "127.0.0.1",
      "listen_port": 2080
    }
  ],
  "outbounds": [
    {
      "type": "selector",
      "tag": "proxy",
      "outbounds": ["vless-reality-out", "hy2-h3-out"],
      "default": "vless-reality-out",
      "interrupt_exist_connections": true
    },
    {
      "type": "vless",
      "tag": "vless-reality-out",
      "server": "__SERVER_IP__",
      "server_port": 443,
      "uuid": "__UUID__",
      "flow": "xtls-rprx-vision",
      "tls": {
        "enabled": true,
        "server_name": "__REALITY_SNI__",
        "utls": {
          "enabled": true,
          "fingerprint": "chrome"
        },
        "reality": {
          "enabled": true,
          "public_key": "__REALITY_PUBLIC_KEY__",
          "short_id": "__REALITY_SHORT_ID__"
        }
      }
    },
    {
      "type": "hysteria2",
      "tag": "hy2-h3-out",
      "server": "__SERVER_IP__",
      "server_port": 443,
      "password": "__HY2_PASSWORD__",
      "tls": {
        "enabled": true,
        "server_name": "__HY2_DOMAIN__"
      }
    },
    {
      "type": "direct",
      "tag": "direct"
    }
  ],
  "route": {
    "default_domain_resolver": "dns-local",
    "final": "proxy"
  }
}
```

Validate:

```bash
sing-box check -c client-mixed.json
sing-box run -c client-mixed.json
curl -fsS4 --proxy socks5h://127.0.0.1:2080 https://api.ipify.org
```

Switch selector default to `hy2-h3-out` and repeat. Both should return `SERVER_IP`.

## TUN Config

Use TUN after mixed passes. For self-use Linux hosts, TUN is the final mode.
Do not start TUN over SSH unless route exclusions protect the current SSH path,
a rollback exists, or the machine is disposable.

Mandatory 1.13.x fixes:

Use IPv4-only DNS by default for Linux workstation TUN:

```json
"dns": {
  "servers": [
    {
      "type": "local",
      "tag": "dns-local"
    }
  ],
  "final": "dns-local",
  "strategy": "ipv4_only"
}
```

Do not use `prefer_ipv4` as the durable default unless IPv6 is verified across
DNS, routing, package mirrors, and curl. `prefer_ipv4` still returns AAAA
answers, so tools such as pacman/libcurl can choose IPv6 and fail even when IPv4
works. Known symptom on Arch-family hosts: mirrors that publish AAAA records fail with
TLS EOF by default while `curl -4` to the same URL succeeds (a concrete
reproducer is `stable-mirror.omarchy.org` on an Omarchy box). Treat this like
Surge `ipv6 = false`: disable IPv6 answers at DNS until the host has proven IPv6
routing.

```json
"route": {
  "auto_detect_interface": true,
  "default_domain_resolver": "dns-local",
  "rules": [
    {
      "network": "icmp",
      "action": "route",
      "outbound": "direct"
    },
    {
      "process_name": "tailscaled",
      "action": "route",
      "outbound": "direct"
    },
    {
      "action": "sniff"
    },
    {
      "protocol": "dns",
      "action": "hijack-dns"
    },
    {
      "ip_is_private": true,
      "action": "route",
      "outbound": "direct"
    }
  ],
  "final": "proxy"
}
```

Omit the `tailscaled` rule when Tailscale is absent. ICMP cannot use VLESS or
HY2 in this stack. Route it direct for normal `ping` behavior, or replace that
rule with an explicit reject policy when revealing the workstation's direct
ICMP path is unacceptable.

TUN inbound:

```json
{
  "type": "tun",
  "tag": "tun-in",
  "interface_name": "singtun0",
  "address": [
    "172.19.0.1/30",
    "fdfe:dcba:9876::1/126"
  ],
  "mtu": 1500,
  "auto_route": true,
  "auto_redirect": true,
  "strict_route": true,
  "route_exclude_address": [
    "__SERVER_IP__/32"
  ]
}
```

The skeleton above already carries the `tailscaled` direct rule (omit it when
Tailscale is absent). Also exclude the tailnet routes before starting TUN:

```json
"route_exclude_address": [
  "__SERVER_IP__/32",
  "100.64.0.0/10",
  "fd7a:115c:a1e0::/48"
]
```

The fixed tailnet ranges are not a complete management-path inventory. Before
starting TUN over Tailscale, inspect accepted subnet routes, exit-node state,
MagicDNS, current SSH source, and the physical underlay:

```bash
tailscale status --json | jq '{Self, Peer}'
ip rule
ip route show table 52
ss -tnp | grep -E '(:22\b|sshd)'
```

Protect every route used by the current management path. When testing TUN over
SSH, add the SSH client address if it is not already protected and use a timeout:

```bash
timeout 60s sing-box run -c tun-test.json
```

For the durable service, install the config under `/etc/sing-box` and use the
packaged systemd template so `CAP_NET_ADMIN` is handled by systemd:

```bash
sudo install -d -m 755 /etc/sing-box
sudo install -m 600 -o sing-box -g sing-box client-tun.json /etc/sing-box/<name>.json
sudo sing-box check -c /etc/sing-box/<name>.json
sudo systemctl enable sing-box@<name>.service
sudo systemctl restart sing-box@<name>.service

for _ in {1..20}; do
  ip link show singtun0 >/dev/null 2>&1 && break
  sleep 0.25
done
ip -brief addr show singtun0
```

TUN validation:

```bash
env -u http_proxy -u https_proxy -u all_proxy -u no_proxy \
  -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u NO_PROXY \
  curl -fsS4 --noproxy "*" https://api.ipify.org
env -u http_proxy -u https_proxy -u all_proxy -u no_proxy \
  -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u NO_PROXY \
  curl -fsSIL4 --noproxy "*" https://www.google.com | sed -n '1,5p'
getent ahostsv4 openai.com | head
resolvectl query --type=AAAA openai.com || true
curl -6 -m 10 --noproxy "*" https://openai.com || true
# On Arch-family hosts, repeat the getent/curl check against the actual package
# mirrors in use to confirm they resolve and fetch IPv4-only, e.g.:
#   getent ahosts <mirror-host> | awk '{print $1}' | sort -u
#   curl -fsSIL --noproxy "*" https://<mirror-host>/<db-path> | sed -n '1p'
ip addr show singtun0
systemctl is-active sing-box@<name>.service
systemctl is-enabled sing-box@<name>.service
ping -n -c 3 1.1.1.1

curl --http3-only -m 25 -fsS -o /dev/null \
  -w 'http3=%{http_code} remote=%{remote_ip}\n' \
  --noproxy "*" https://cloudflare-quic.com/
```

With `ipv4_only`, `resolvectl query --type=AAAA` should report no RR and
`curl -6` should fail to resolve. `getent ahostsv6` is not a valid assertion
because glibc may print IPv4-mapped `::ffff:` addresses even when DNS returned no
AAAA record.

With selector default `vless-reality-out`, the HTTP/3 request must succeed and
the journal must show VLESS packet traffic. If curl lacks HTTP/3 support, use
another UDP-aware client and retain the same log assertion.

If the current SSH path or peer access uses Tailscale, also verify the tailnet
route after enabling TUN:

```bash
ip route get <tailscale-peer-ipv4>
ip -6 route get <tailscale-peer-ipv6>
tailscale ping <tailscale-peer-ipv4>
getent hosts <tailnet-host>.ts.net
tailscale netcheck
```

The healthy Linux shape keeps peer routes on `tailscale0`, preserves MagicDNS,
and leaves every accepted subnet route usable. A successful peer ping alone is
not enough when subnet routes or an exit node are configured.

Run initial validation with `log.level = info` so the selected outbound is
visible. Restore `warn` after the route and protocol assertions pass. A
long-running `info` service logs every connection and can produce tens of
thousands of journal lines during probes or builds.

Good logs include:

```text
inbound/tun[tun-in]: started at singtun0
dns: exchanged A api.ipify.org
outbound/vless[...]: outbound connection
outbound/vless[...]: outbound packet connection
```

`UDP is not supported by outbound: proxy` with VLESS selected means the VLESS
outbound was restricted to `"network": "tcp"`. Remove that restriction, run
`sing-box check`, restart, and repeat the HTTP/3 test. Do not silently route all
UDP to HY2 unless the user explicitly asks for protocol-based splitting.

If `curl -I` shows `HTTP/1.1 200 Connection established`, the test is still
going through an env proxy. Clear proxy env and retest with `--noproxy "*"`.

Repeating `icmp is not supported by default outbound: proxy` means the explicit
ICMP direct or reject rule is missing. Do not route ICMP to VLESS or HY2.

## Performance Decisions

Keep the upstream TUN stack default. In `v1.13.14`, a build with gVisor defaults
to the mixed stack: system TCP plus gVisor UDP. Set `stack` only to diagnose a
reproducible compatibility problem. For a workstation whose physical underlay
MTU is `1500`, use this conservative baseline:

```json
{
  "mtu": 1500,
  "auto_route": true,
  "auto_redirect": true,
  "strict_route": true
}
```

Start with the physical underlay MTU, usually `1500`. `auto_redirect` handles
the main Linux forwarding path, so increasing the virtual TUN MTU is not a
free throughput upgrade. Test HTTP/3, Docker, Tailscale, packet loss, and the
same fixed download before keeping a larger value.

HY2 without `up_mbps` / `down_mbps` uses automatic BBR and is the portable
default. A fixed workstation may use Brutal only after at least three
same-endpoint runs establish sustainable upload and download rates. Set each
direction no higher than the lower sustained result, then repeat the test while
measuring gateway latency. Remove both values when the link changes, becomes
lossy, or latency under load regresses materially.

Do not apply a generic UDP sysctl block solely because `net.core.rmem_max` looks
small. Inspect the live sing-box socket and kernel drop counters while HY2 is
active:

```bash
ss -u -a -m -p | grep -A2 -B1 sing-box
nstat -az | grep -E 'Udp(InErrors|RcvbufErrors|SndbufErrors)'
```

If the sing-box socket already reports receive/send buffers near `16 MiB` and
the UDP error counters do not increase during a transfer, leave sysctl alone.
Only when the actual socket remains smaller and the transfer shows buffer
warnings, drops, or a reproducible throughput ceiling should the host set both
maxima to `16777216` in a dedicated `/etc/sysctl.d/` file and repeat the test.

Kernel TCP BBR affects the outer VLESS TCP sender; it does not tune HY2's
userspace QUIC congestion controller. Do not change every client from Cubic as
a ritual. Verify the active sender, qdisc, and an upload/download comparison
before retaining a host-level congestion-control change.

## Old Proxy Cleanup

When migrating an existing Linux host from Clash/Mihomo or user-level proxy
configs, do not leave both stacks active. After TUN is active and verified:

```bash
systemctl list-unit-files --no-pager | grep -Ei 'clash|mihomo' || true
systemctl list-units --type=service --all --no-pager | grep -Ei 'clash|mihomo' || true
ps -eo pid,ppid,user,comm,args | grep -Ei 'clash|mihomo' | grep -v grep || true
ss -lntup | grep -E ':(7890|7891|7892|7893|9090|9097|2080)\b' || true
```

Quarantine old daemon state only after TUN is proven and each path has been
traced to the old process or unit. Do not assume every `/opt/clash`,
`~/.config/sing-box`, or systemd path belongs to the migration. Record the
source, owner, consumer, backup path, and restore command before moving it.

After that inventory, move only the confirmed old unit and daemon directory:

```bash
sudo systemctl disable --now mihomo.service 2>/dev/null || true
sudo systemctl mask mihomo.service 2>/dev/null || true
sudo install -d -m 700 /root/proxy-cleanup
sudo mv /etc/systemd/system/mihomo.service /root/proxy-cleanup/mihomo.service.etc.$(date +%Y%m%d-%H%M%S) 2>/dev/null || true
sudo mv /usr/lib/systemd/system/mihomo.service /root/proxy-cleanup/mihomo.service.usr.$(date +%Y%m%d-%H%M%S) 2>/dev/null || true
sudo systemctl daemon-reload
sudo mv /opt/clash /root/proxy-cleanup/opt-clash.$(date +%Y%m%d-%H%M%S) 2>/dev/null || true
```

Clean shell hooks and stale user-level configs:

```bash
rg -n -i 'clash|mihomo|watch_proxy|HTTP_PROXY|HTTPS_PROXY|ALL_PROXY|http_proxy|https_proxy|all_proxy' \
  ~/.bashrc ~/.bash_profile ~/.profile ~/.zshrc ~/.zprofile ~/.zshenv /etc/profile /etc/bash.bashrc /etc/zsh/zshrc 2>/dev/null || true
mkdir -p ~/.local/share/proxy-cleanup
```

Show the candidate file list and obtain confirmation before moving user-level
directories. Keep the active sing-box client config. If stale files under the
user's home are root-owned, ask the user to run the specific root-owned
quarantine command.

## Linux Recommendation

Default Linux self-use mode:

```text
systemd sing-box TUN service
no persistent proxy env exports
selector default vless-reality-out
VLESS carries both TCP and UDP
HY2 remains a manually selected high-speed fallback
```

Default selector:

```json
"default": "vless-reality-out"
```

Use HY2 when UDP is clean and a same-path comparison proves it is better. On a
hotspot or lossy path, keep REALITY as the stable default.
