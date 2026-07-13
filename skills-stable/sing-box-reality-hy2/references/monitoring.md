# External HY2 Signals

Use this with `$end-to-end-monitoring` when standing monitoring is authorized. That skill owns cadence, freshness, backend, notification transitions, secret storage, responder, and runbook. This reference only defines the protocol-specific signals and the sing-box process constraint.

Run the producer outside the sing-box VPS. Its notification path must not depend only on the HY2 path it observes. A producer cannot report its own total loss; an independent backend must detect missing runs when that silence matters.

## Inputs

```text
SERVER_IP
HY2_DOMAIN
HY2 outbound from an authorized client config
EXPECTED_EGRESS_IPV4, usually SERVER_IP on a directly addressed VPS
CERT_MIN_SECONDS, chosen from the certificate lifetime and repair window
DNS_RESOLVER_IP, a user-owned or explicitly authorized external resolver
EGRESS_ECHO_URL, a user-owned or explicitly authorized HTTPS IP echo endpoint
```

Use `300s` cadence and `1209600` seconds of certificate margin only as starting values. The monitoring contract decides the actual values.
The target-service authorization does not implicitly authorize third-party DNS or IP echo services. Record both endpoints in the monitoring contract before the producer uses them.

## Dedicated Profile

Build a separate mixed profile from the authorized HY2 outbound. Do not alter the active TUN profile or print the extracted outbound because it contains the HY2 password:

```bash
umask 077
jq '{
  log: {level: "warn", timestamp: true},
  inbounds: [{
    type: "mixed",
    tag: "monitor-in",
    listen: "127.0.0.1",
    listen_port: 2089
  }],
  outbounds: [.outbounds[] | select(.tag == "hy2-h3-out")],
  route: {final: "hy2-h3-out"}
}' <authorized-client-config.json >hy2-monitor.json
sing-box check -c hy2-monitor.json
```

Install the result as `root:<monitor-group>` mode `0640`. Keep the source config and generated profile on the authorized host.

## Signals

### Public DNS

When any client dials `HY2_DOMAIN` instead of `SERVER_IP`, query an external resolver and require the intended A record. Require no AAAA record unless IPv6 is part of the deployment contract:

```bash
dig +short A "$HY2_DOMAIN" @"$DNS_RESOLVER_IP"
dig +short AAAA "$HY2_DOMAIN" @"$DNS_RESOLVER_IP"
```

The HTTP/3 check below uses `--resolve` and therefore does not cover public DNS.

### HTTP/3 Certificate

First require a curl build with HTTP/3 and `%{certs}` support. Do not silently downgrade to TCP:

```bash
curl -V | grep -w HTTP3
case "$(curl -sS -o /dev/null -w '%{certs}' file:///dev/null 2>&1)" in
  *"unknown --write-out variable"*) exit 1 ;;
esac
```

Connect directly to `SERVER_IP` while validating `HY2_DOMAIN`:

```bash
probe_dir="$(mktemp -d)"
trap 'rm -rf "$probe_dir"' EXIT
curl --http3-only \
  --resolve "$HY2_DOMAIN:443:$SERVER_IP" \
  --connect-timeout 8 --max-time 20 \
  -sS -o /dev/null -w '%{http_code}\n%{certs}' \
  "https://$HY2_DOMAIN/" >"$probe_dir/result"
sed -n '1p' "$probe_dir/result"
awk '
  /-----BEGIN CERTIFICATE-----/ { capture = 1 }
  capture { print }
  /-----END CERTIFICATE-----/ { exit }
' "$probe_dir/result" >"$probe_dir/leaf.pem"
openssl x509 -in "$probe_dir/leaf.pem" -noout \
  -checkend "$CERT_MIN_SECONDS"
rm -rf "$probe_dir"
trap - EXIT
```

Require an HTTP status from the HTTP/3 server, a parseable leaf PEM, successful
hostname and chain validation from curl, and a successful `openssl -checkend`.

Do not require `2xx` unless the configured masquerade has a deterministic response. A proxy masquerade can return an upstream error even while QUIC and the certificate are healthy. This check observes unauthenticated HTTP/3 behavior, not HY2 authentication.

### Authenticated HY2

Choose one sidecar lifecycle. For a one-shot manual or scheduler probe, start
the dedicated profile, wait for its local listener, and always stop it:

```bash
if ss -H -ltn 'sport = :2089' | grep -q .; then
  echo "local monitor port 2089 is already owned; stop or choose another dedicated port" >&2
  exit 1
fi

sidecar_log="$(mktemp)"
sing-box run -c hy2-monitor.json >"$sidecar_log" 2>&1 &
sidecar_pid=$!
cleanup_sidecar() {
  kill "$sidecar_pid" 2>/dev/null || true
  wait "$sidecar_pid" 2>/dev/null || true
  rm -f "$sidecar_log"
}
trap cleanup_sidecar EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

sidecar_listening() {
  ss -H -ltnp 'sport = :2089' | grep -Fq "pid=$sidecar_pid,"
}

for _ in $(seq 1 40); do
  if ! kill -0 "$sidecar_pid" 2>/dev/null; then
    cat "$sidecar_log" >&2
    exit 1
  fi
  sidecar_listening && break
  sleep 0.25
done
sidecar_listening || {
  cat "$sidecar_log" >&2
  exit 1
}
```

Then force an IPv4 request through it:

```bash
curl -4 --proxy socks5h://127.0.0.1:2089 \
  --connect-timeout 5 --max-time 15 \
  -fsS "$EGRESS_ECHO_URL"
```

Require `EXPECTED_EGRESS_IPV4`. On a NATed VPS, define that value from measured egress instead of assuming it equals `SERVER_IP`. Treat failure of the IP echo service as an external dependency failure unless a second endpoint or owned echo service confirms the proxy is also down.

For a standing producer, `$end-to-end-monitoring` may instead install one
persistent dedicated sidecar unit. The probe unit must declare an ordering and
runtime dependency on that sidecar, require port `2089` readiness before curl,
and fail freshness when the sidecar is inactive. Do not also launch the
one-shot process when the persistent unit owns the port.

## systemd Constraint

A sing-box mixed process subscribes to Linux route updates. A hardened unit using `RestrictAddressFamilies=` must include `AF_NETLINK`:

```ini
RestrictAddressFamilies=AF_INET AF_INET6 AF_NETLINK AF_UNIX
```

Without it, sing-box exits with:

```text
start service: subscribe route updates: address family not supported by protocol
```

After `$end-to-end-monitoring` builds the producer, verify a healthy manual run, one scheduler-triggered run, the first failure, repeated-failure suppression, recovery, backend freshness, and notification delivery. API acceptance alone does not prove display on the user's device.
