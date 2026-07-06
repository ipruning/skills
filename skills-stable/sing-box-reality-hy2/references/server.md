# Server Reference

Use this for VPS server setup: `sing-box stable + VLESS REALITY Vision + Hysteria2 HTTP/3 masquerade`.

## Inputs

Collect:

```text
SERVER_IP
HY2_DOMAIN
ACME_EMAIL optional
REALITY_SNI
REALITY_HANDSHAKE_HOST usually same as REALITY_SNI
```

Cloudflare DNS:

```text
Type: A
Name: chosen host, for example vps-1
Content: SERVER_IP
Proxy status: DNS only
TTL: Auto
AAAA: omit unless IPv6 is verified
```

## Install

```bash
apt-get update
apt-get -y upgrade
timedatectl set-timezone UTC
timedatectl set-ntp true
apt-get install -y curl ca-certificates jq openssl ufw nftables certbot

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
apt-get install -y sing-box
sing-box version
```

Reject the deployment if the installed core is not stable `1.13.x` unless the user explicitly requested a newer migration.

## Firewall

```bash
ufw allow OpenSSH
ufw allow 80/tcp comment certbot-http
ufw allow 443/tcp comment sing-box-reality
ufw allow 443/udp comment sing-box-hy2
ufw --force enable
ufw status verbose
```

Keep existing Snell listeners if the host already uses them. Do not remove an existing fallback service unless the user asks.

## Certificate

Prefer a real email. If the user has no email ready, `--register-unsafely-without-email` works but create a reminder to add email later.

```bash
certbot certonly --standalone \
  --preferred-challenges http \
  -d "$HY2_DOMAIN" \
  -m "$ACME_EMAIL" \
  --agree-tos \
  --no-eff-email
```

No-email variant:

```bash
certbot certonly --standalone \
  --preferred-challenges http \
  -d "$HY2_DOMAIN" \
  --register-unsafely-without-email \
  --agree-tos \
  --non-interactive
```

Renew hook:

```bash
install -d -m 755 /etc/letsencrypt/renewal-hooks/deploy
cat >/etc/letsencrypt/renewal-hooks/deploy/restart-sing-box.sh <<'EOF'
#!/bin/sh
systemctl restart sing-box
EOF
chmod +x /etc/letsencrypt/renewal-hooks/deploy/restart-sing-box.sh
```

## Secrets

```bash
install -d -m 700 /etc/sing-box
UUID="$(sing-box generate uuid)"
KEYS="$(sing-box generate reality-keypair)"
REALITY_PRIVATE_KEY="$(printf '%s\n' "$KEYS" | awk -F': ' '/PrivateKey/ {print $2}')"
REALITY_PUBLIC_KEY="$(printf '%s\n' "$KEYS" | awk -F': ' '/PublicKey/ {print $2}')"
REALITY_SHORT_ID="$(openssl rand -hex 4)"
HY2_PASSWORD="$(openssl rand -hex 32)"
HY2_OBFS_PASSWORD="$(openssl rand -hex 32)"
```

Write `/root/sing-box-secrets.txt` mode `600`. Include:

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
HY2_OBFS_PASSWORD
```

## Server Config Shape

Use TCP/443 VLESS REALITY:

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

Use UDP/443 HY2:

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
    "url": "https://www.apple.com",
    "rewrite_host": true
  }
}
```

Full config should use direct outbound and `route.final = direct`.

## Validate

```bash
sing-box check -c /etc/sing-box/config.json
sing-box format -w -c /etc/sing-box/config.json
systemctl enable --now sing-box
systemctl restart sing-box
systemctl is-active sing-box
ss -lntup | grep -E ':443\b'
curl --http3-only -I "https://$HY2_DOMAIN/" || true
```

Expected listeners:

```text
tcp 0.0.0.0:443 sing-box
udp 0.0.0.0:443 sing-box
```

After `sing-box format -w`, a valid config may render `"max_time_difference": "1m"` as `"1m0s"`; the two are equivalent.

Ignore random invalid REALITY handshake logs from scanners. Valid tests show `[<user>] inbound connection to api.ipify.org:443`.
