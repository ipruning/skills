# Linux / VPS Client Reference

Use this for Linux clients, Linux workstations, and VPS-to-VPS testing.
The durable Linux target is system-level TUN. Mixed mode is only for protocol
smoke tests or temporary access without elevated privileges.

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
apt-get install -y sing-box curl jq
sing-box version
```

On Arch Linux, prefer the distro package if it provides `sing-box` with
`with_utls` and a systemd `sing-box@.service`:

```bash
pacman -Qi sing-box
sing-box version
systemctl cat sing-box@.service
```

If `sing-box version` lacks `with_utls`, REALITY client checks will fail. Install
or build a package with uTLS support before continuing.

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
- HY2 outbound dials `SERVER_IP`.
- HY2 TLS uses `server_name = HY2_DOMAIN`.
- Include `route.default_domain_resolver`.

Skeleton:

```json
{
  "log": {
    "level": "info",
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
      "outbounds": ["vless-reality-out", "hy2-h3-out", "direct"],
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
      "network": "tcp",
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
works. Known symptom: Arch/Omarchy mirrors such as
`stable-mirror.omarchy.org`, `pkgs.omarchy.org`, or
`geo.mirror.pkgbuild.com` fail with TLS EOF by default, while `curl -4` to the
same URL succeeds. Treat this like Surge `ipv6 = false`: disable IPv6 answers at
DNS until the host has proven IPv6 routing.

```json
"route": {
  "auto_detect_interface": true,
  "default_domain_resolver": "dns-local",
  "rules": [
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

If SSH reaches the host through Tailscale, add both Tailscale ranges before
starting TUN:

```json
"route_exclude_address": [
  "__SERVER_IP__/32",
  "100.64.0.0/10",
  "fd7a:115c:a1e0::/48"
]
```

When testing TUN over SSH, add the SSH client IP to `route_exclude_address` and run with a timeout:

```bash
timeout 60s sing-box run -c tun-test.json
```

For the durable service, install the config under `/etc/sing-box` and use the
packaged systemd template so `CAP_NET_ADMIN` is handled by systemd:

```bash
sudo install -d -m 755 /etc/sing-box
sudo install -m 600 -o sing-box -g sing-box client-tun.json /etc/sing-box/<name>.json
sudo sing-box check -c /etc/sing-box/<name>.json
sudo systemctl enable --now sing-box@<name>.service
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
getent ahosts stable-mirror.omarchy.org | awk '{print $1}' | sort -u
getent ahosts pkgs.omarchy.org | awk '{print $1}' | sort -u
curl -fsSIL --noproxy "*" https://stable-mirror.omarchy.org/core/os/x86_64/core.db | sed -n '1p'
curl -fsSIL --noproxy "*" https://pkgs.omarchy.org/stable/x86_64/omarchy.db | sed -n '1p'
ip addr show singtun0
systemctl is-active sing-box@<name>.service
systemctl is-enabled sing-box@<name>.service
```

If the current SSH path or peer access uses Tailscale, also verify the tailnet
route after enabling TUN:

```bash
ip route get <tailscale-peer-ipv4>
ip -6 route get <tailscale-peer-ipv6>
```

The healthy Linux shape is `dev tailscale0`. If the route points to the
sing-box TUN interface, add `100.64.0.0/10` and `fd7a:115c:a1e0::/48` to
`route_exclude_address`, run `sing-box check`, and restart the service.

Good logs include:

```text
inbound/tun[tun-in]: started at singtun0
dns: exchanged A api.ipify.org
outbound/vless[...] or outbound/hysteria2[...]
```

If `curl -I` shows `HTTP/1.1 200 Connection established`, the test is still
going through an env proxy. Clear proxy env and retest with `--noproxy "*"`.

## Old Proxy Cleanup

When migrating an existing Linux host from Clash/Mihomo or user-level proxy
configs, do not leave both stacks active. After TUN is active and verified:

```bash
systemctl list-unit-files --no-pager | grep -Ei 'clash|mihomo' || true
systemctl list-units --type=service --all --no-pager | grep -Ei 'clash|mihomo' || true
ps -eo pid,ppid,user,comm,args | grep -Ei 'clash|mihomo' | grep -v grep || true
ss -lntup | grep -E ':(7890|7891|7892|7893|9090|9097|2080)\b' || true
```

Quarantine old daemon state only after TUN is proven. Prefer moving old files
to a dated root-owned backup first; delete later only when the user explicitly
asks for irreversible cleanup:

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
for old_proxy_path in ~/.config/sing-box ~/.config/clash ~/.config/mihomo ~/.local/share/clash ~/.local/share/mihomo; do
  [ -e "$old_proxy_path" ] && mv "$old_proxy_path" ~/.local/share/proxy-cleanup/"$(basename "$old_proxy_path").$(date +%Y%m%d-%H%M%S)"
done
```

If stale files under the user's home are root-owned, ask the user to run the
specific root-owned quarantine command. Do not silently leave old dashboard,
cache, or subscription configs that can confuse future audits.

## Linux Recommendation

Default Linux self-use mode:

```text
systemd sing-box TUN service
no persistent proxy env exports
selector default vless-reality-out
```

Default selector:

```json
"default": "vless-reality-out"
```

Use HY2 only when UDP is clean and local tests prove it is faster. On hotspot or lossy paths, REALITY is usually more stable.
