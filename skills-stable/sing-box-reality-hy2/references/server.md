# Server Reference

Use this for a Debian 12/13 or Ubuntu 24.04 systemd VPS running `sing-box stable + VLESS REALITY Vision + Hysteria2 HTTP/3 masquerade`.

Read [version-compatibility.md](version-compatibility.md) before installation. Do not apply this reference to non-APT, non-systemd, container-only, or already complex firewall hosts without adapting it first.

## Inputs

Collect:

```text
SERVER_IP
HY2_DOMAIN
REALITY_SNI
REALITY_HANDSHAKE_HOST usually same as REALITY_SNI
MASQUERADE_URL, a user-owned or deliberately chosen stable HTTPS origin
DNS_RESOLVER_IP, a user-owned or explicitly authorized external resolver
```

`HY2_DOMAIN` 必须是用户为本次部署指定或明确授权使用的域名。`REALITY_SNI`、`REALITY_HANDSHAKE_HOST`、`MASQUERADE_URL` 和 `DNS_RESOLVER_IP` 必须逐项由用户指定，或由用户明确授权 Agent 为这个 VPS 选择；一般性的部署授权不等于允许自行引入第三方目标。缺少来源授权时停止并询问，不继承其他服务器的值，也不使用永久全局默认值。

Cloudflare DNS:

```text
Type: A
Name: chosen host, for example vps-1
Content: SERVER_IP
Proxy status: DNS only
TTL: Auto
AAAA: omit unless server and client IPv6 are verified
```

## Preflight

Read the host before changing it:

```bash
set -eu
. /etc/os-release
printf 'os=%s %s\n' "$ID" "$VERSION_ID"
systemctl --version | sed -n '1p'
timedatectl show -p NTPSynchronized -p Timezone
sshd -T | awk '$1 ~ /^(port|listenaddress|permitrootlogin|passwordauthentication|pubkeyauthentication)$/ { print }'
ss -lntup
ufw status verbose 2>/dev/null || true
nft list ruleset 2>/dev/null || true
```

Stop instead of killing an unknown process when:

- TCP/443 or UDP/443 already has an owner.
- TCP/80 is occupied and Certbot standalone mode is planned.
- the current SSH port or management source is not known.
- the host already has firewall rules whose ownership is unclear.
- there is no second SSH session or provider console before a firewall change.

Verify public DNS through an external resolver before requesting a certificate:

```bash
dig +short A "$HY2_DOMAIN" @"$DNS_RESOLVER_IP"
dig +short AAAA "$HY2_DOMAIN" @"$DNS_RESOLVER_IP"
```

The A result must contain `SERVER_IP`. The AAAA result must be empty unless IPv6 is intentionally supported. Provider security groups must allow the same ports as the host firewall; UFW alone does not prove public reachability.

Verify the REALITY target from the VPS:

```bash
openssl s_client \
  -connect "$REALITY_HANDSHAKE_HOST:443" \
  -servername "$REALITY_SNI" \
  -tls1_3 \
  -alpn h2 </dev/null 2>/dev/null \
  | grep -E 'Protocol|ALPN protocol|Verify return code'

curl -fsSI "https://$REALITY_SNI/" | grep -Ei '^(HTTP/|location:)'
```

Require TLS 1.3, ALPN `h2`, certificate verification success, and no redirect to a different hostname. Prefer a target whose network location and latency are close to the VPS. Do not use a permanent global default target.

Verify the chosen masquerade origin independently:

```bash
curl -fsS -o /dev/null --connect-timeout 8 --max-time 20 "$MASQUERADE_URL"
```

## Install

Do not run a full distribution upgrade as part of this deployment. System upgrades need their own maintenance decision.

```bash
apt-get update
apt-get install -y curl ca-certificates dnsutils jq openssl ufw nftables certbot

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
test -n "$package_version" || {
  echo 'sing-box 1.13.14 is unavailable from the configured repository.' >&2
  exit 1
}
apt-get install -y "sing-box=$package_version"
apt-mark hold sing-box

version_text="$(sing-box version | sed -n '1p')"
printf '%s\n' "$version_text"
case "$version_text" in
  'sing-box version 1.13.'*) ;;
  *) echo 'This template is validated only for stable 1.13.x; inspect migration docs before continuing.' >&2; exit 1 ;;
esac
```

The hold prevents an unattended major-version migration. A planned upgrade must
first read the target version's migration notes, render a candidate config, run
that version's `sing-box check`, and only then remove the hold.

## Firewall

If this is a fresh single-purpose VPS and UFW is the chosen firewall, preserve every effective SSH port before enabling it:

```bash
sshd -T | awk '$1 == "port" { print $2 }' | sort -u \
  | while read -r ssh_port; do ufw allow "$ssh_port/tcp" comment ssh-management; done
ufw allow 80/tcp comment certbot-http
ufw allow 443/tcp comment sing-box-reality
ufw allow 443/udp comment sing-box-hy2
ufw --force enable
ufw status verbose
```

Open a fresh SSH connection after enabling UFW. If the host already uses nftables, iptables, a provider firewall agent, or source-restricted SSH rules, adapt the existing firewall instead of enabling UFW over it. Keep an existing Snell listener only when the user asks to retain that fallback.

## Certificate

Certbot standalone mode requires TCP/80 to be free and publicly reachable. Let's Encrypt stopped expiration notification emails and deleted ACME account email addresses on 2025-06-04. Do not ask for an email or create a reminder to add one:

```bash
certbot certonly \
  --standalone \
  --preferred-challenges http \
  -d "$HY2_DOMAIN" \
  --register-unsafely-without-email \
  --agree-tos \
  --non-interactive
```

The deploy hook must not restart an invalid configuration:

```bash
install -d -m 755 /etc/letsencrypt/renewal-hooks/deploy
cat >/etc/letsencrypt/renewal-hooks/deploy/restart-sing-box.sh <<'EOF'
#!/bin/sh
set -eu
sing-box check -c /etc/sing-box/config.json
systemctl try-restart sing-box.service
EOF
chmod 755 /etc/letsencrypt/renewal-hooks/deploy/restart-sing-box.sh
```

The timer performs renewal; it is not an expiry alert. Enable it and validate the complete renewal path, including the deploy hook:

```bash
systemctl enable --now certbot.timer
systemctl is-enabled certbot.timer
systemctl is-active certbot.timer
systemctl list-timers certbot.timer --no-pager
certbot renew --dry-run --run-deploy-hooks
```

For unattended production operation, an ordinary TCP/443 TLS probe cannot observe the HY2 certificate because TCP/443 belongs to REALITY. If standing monitoring is authorized, use `$end-to-end-monitoring` with the protocol assertions in [monitoring.md](monitoring.md). Otherwise report it as not configured.

## Secrets

```bash
install -d -m 700 /etc/sing-box
UUID="$(sing-box generate uuid)"
KEYS="$(sing-box generate reality-keypair)"
REALITY_PRIVATE_KEY="$(printf '%s\n' "$KEYS" | awk -F': ' '/PrivateKey/ {print $2}')"
REALITY_PUBLIC_KEY="$(printf '%s\n' "$KEYS" | awk -F': ' '/PublicKey/ {print $2}')"
REALITY_SHORT_ID="$(openssl rand -hex 8)"
HY2_PASSWORD="$(openssl rand -hex 32)"
```

The validated implementation stores REALITY short IDs in up to 8 decoded bytes, so `openssl rand -hex 8` produces the full 16-hex-character value. The source anchor is in [version-compatibility.md](version-compatibility.md).

Write `/root/sing-box-secrets.txt` with mode `600` and these keys:

```text
SERVER_IP
HY2_DOMAIN
REALITY_SNI
REALITY_HANDSHAKE_HOST
UUID
REALITY_PRIVATE_KEY
REALITY_PUBLIC_KEY
REALITY_SHORT_ID
HY2_PASSWORD
```

Do not generate or persist an obfuscation password unless both server and client will actually enable Salamander.

## Server Config Shape

TCP/443 VLESS REALITY:

```json
{
  "type": "vless",
  "tag": "vless-reality-in",
  "listen": "0.0.0.0",
  "listen_port": 443,
  "users": [
    {
      "name": "<user>",
      "uuid": "__UUID__",
      "flow": "xtls-rprx-vision"
    }
  ],
  "tls": {
    "enabled": true,
    "server_name": "__REALITY_SNI__",
    "reality": {
      "enabled": true,
      "handshake": {
        "server": "__REALITY_HANDSHAKE_HOST__",
        "server_port": 443
      },
      "private_key": "__REALITY_PRIVATE_KEY__",
      "short_id": ["__REALITY_SHORT_ID__"],
      "max_time_difference": "1m"
    }
  }
}
```

UDP/443 Hysteria2:

```json
{
  "type": "hysteria2",
  "tag": "hy2-h3-in",
  "listen": "0.0.0.0",
  "listen_port": 443,
  "users": [
    {
      "name": "<user>",
      "password": "__HY2_PASSWORD__"
    }
  ],
  "tls": {
    "enabled": true,
    "server_name": "__HY2_DOMAIN__",
    "certificate_path": "/etc/letsencrypt/live/__HY2_DOMAIN__/fullchain.pem",
    "key_path": "/etc/letsencrypt/live/__HY2_DOMAIN__/privkey.pem"
  },
  "masquerade": {
    "type": "proxy",
    "url": "__MASQUERADE_URL__",
    "rewrite_host": true
  }
}
```

The full config uses a direct outbound and `route.final = direct`. With one IP, ordinary TCP HTTPS to `HY2_DOMAIN` reaches REALITY, not the Hysteria2 masquerade; only HTTP/3 over UDP/443 exercises the masquerade.

The proxy masquerade origin is an availability dependency only for
unauthenticated HTTP/3 cover traffic. Prefer an origin the user controls; if a
public origin is chosen, verify it from the VPS and do not treat its `2xx`
response as proof of HY2 authentication.

Use `log.level = warn` in the production candidate. Temporarily switch to
`info` only when validation or diagnosis needs connection-level evidence, then
restore `warn`; public scanners and per-connection info logs otherwise create
avoidable journal volume.

In a whole-host journal audit, classify `[UFW BLOCK]` records as firewall drop
events before counting them as kernel faults. Keep bounded low-level firewall
logging when its audit value is wanted; disabling it is a conscious loss of
edge evidence, not a generic log-health fix.

Leave server and client HY2 `up_mbps` / `down_mbps` empty by default. In the
validated baseline, empty values select the congestion-controlled BBR path
instead of a guessed Brutal rate. A fixed client may opt into measured Brutal
values without turning that client-specific rate into a server-template
default.

## Stage and Activate

Write the rendered configuration to `/etc/sing-box/config.json.new`, not directly over the live file. Then validate, format, validate again, and keep a rollback copy:

```bash
set -eu
candidate=/etc/sing-box/config.json.new
target=/etc/sing-box/config.json
backup="${target}.bak.$(date +%Y%m%d-%H%M%S)"

sing-box check -c "$candidate"
sing-box format -w -c "$candidate"
sing-box check -c "$candidate"

if test -f "$target"; then
  install -m 600 -o root -g root "$target" "$backup"
fi
install -m 600 -o root -g root "$candidate" "$target"

systemctl enable sing-box
if ! systemctl restart sing-box; then
  test -f "$backup" && install -m 600 -o root -g root "$backup" "$target"
  systemctl restart sing-box || true
  exit 1
fi
rm -f "$candidate"
```

## Validate

```bash
sing-box check -c /etc/sing-box/config.json
systemctl is-active sing-box
systemctl is-enabled sing-box
ss -lntup | grep -E ':443\b'
openssl x509 \
  -in "/etc/letsencrypt/live/$HY2_DOMAIN/fullchain.pem" \
  -noout -subject -enddate
systemctl is-enabled certbot.timer
systemctl is-active certbot.timer
test -x /etc/letsencrypt/renewal-hooks/deploy/restart-sing-box.sh
certbot renew --dry-run --run-deploy-hooks
```

Expected listeners:

```text
tcp 0.0.0.0:443 sing-box
udp 0.0.0.0:443 sing-box
```

An external client is required before calling the deployment complete:

- a REALITY mixed test returns `SERVER_IP` and the server log names the expected VLESS user;
- an HY2 mixed test returns `SERVER_IP` and the server log names the expected Hysteria2 user;
- an HTTP/3 request to `HY2_DOMAIN` returns the configured masquerade response;
- provider firewall and host firewall counters show UDP/443 reaching the host when HY2 fails.

Random invalid REALITY handshakes from public scanners are expected. A clean `systemd` stop with exit status 0 is an external stop, not a sing-box crash.

## Performance Baseline

Do not install a generic network-tuning bundle. Read the active TCP sender,
qdisc, actual HY2 socket buffers, and UDP drop counters first:

```bash
sysctl net.ipv4.tcp_congestion_control net.ipv4.tcp_available_congestion_control
sysctl net.core.default_qdisc net.core.rmem_max net.core.wmem_max
ss -u -a -m -p | grep -A2 -B1 sing-box
nstat -az | grep -E 'Udp(InErrors|RcvbufErrors|SndbufErrors)|TcpRetransSegs'
```

For a long-RTT VLESS server, BBR with `fq` is a reasonable measured target, not
an unconditional deployment step. Keep an existing working BBR/fq setup. Do
not change kernels or congestion control without a same-path before/after test.

Hysteria recommends `16 MiB` UDP send and receive maxima on Linux. The process
may already obtain those buffers even when the global sysctl displays a smaller
value, so the `skmem` values from `ss` are the deciding evidence. Write a
dedicated `/etc/sysctl.d/` override only when the live sing-box socket remains
smaller and UDP errors or a repeatable HY2 bottleneck are present. Recheck the
socket and counters after applying it.
