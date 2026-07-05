# macOS Surge Network Triage

These checks apply when the failure is on the user's macOS machine and Surge is
part of the network path. Read state first. Do not change Enhanced Mode, System
Proxy, outbound mode, shell proxy variables, DNS, or policy selection during
diagnosis. If the user explicitly asks for a local toggle or repair command,
read [macOS Surge Operator Actions](macos-surge-operator-actions.md) and output
a manual command plan; do not run it from this skill.

## Prerequisites

```bash
surge_cli=$(command -v surge-cli || true)
if [ -z "$surge_cli" ] && [ -x /Applications/Surge.app/Contents/Applications/surge-cli ]; then
  surge_cli=/Applications/Surge.app/Contents/Applications/surge-cli
fi
test -n "$surge_cli"
```

When the user's task or network evidence shows a mainland-China path,
international traffic such as GitHub, Homebrew, npm, and Docker Hub may fail
without a proxy. In that case, Surge may be the network control plane.

## Local Proxy And Routing Controls

| Control               | Mechanism                              | Scope                                    | State Check                               |
| --------------------- | -------------------------------------- | ---------------------------------------- | ----------------------------------------- |
| Shell proxy variables | `http_proxy`/`https_proxy`/`all_proxy` | Per-shell; tools that honor env vars     | `env \| grep -i proxy`                    |
| System Proxy          | macOS HTTP proxy configured by Surge   | Apps that use the macOS system proxy     | HTTP API `GET /v1/features/system_proxy`  |
| Enhanced Mode         | Surge system-wide TUN / virtual NIC    | System-wide traffic interception         | HTTP API `GET /v1/features/enhanced_mode` |
| Outbound Mode         | Surge rule/direct/proxy selection      | How Surge routes traffic that it handles | HTTP API `GET /v1/outbound`               |

**No control is always correct:**

- On a mainland-China path, international package or source hosts may hang when
  no working local proxy control routes them through Surge.
- Shell proxy variables or System Proxy pointed at an unhealthy Surge path can
  make tool traffic hang.
- Enhanced Mode routes traffic system-wide and can break direct-connection
  debugging.
- Outbound Mode can send traffic direct, by rule, or through a proxy policy;
  confirm it before blaming the VPS.

## Tailscale Coexistence

Surge Enhanced Mode and Tailscale both install virtual interfaces. Treat their
route handling as platform-specific:

- Keep Tailscale out of the macOS system proxy with `skip-proxy = ..., 100.64.0.0/10`.
- Add Surge rules for Tailscale control traffic and tailnet ranges:
  `DOMAIN-SUFFIX,tailscale.com,DIRECT`, `DOMAIN-SUFFIX,tailscale.io,DIRECT`,
  `IP-CIDR,100.64.0.0/10,DIRECT,no-resolve`, and
  `IP-CIDR6,fd7a:115c:a1e0::/48,DIRECT,no-resolve`.
- Add process rules for the Tailscale network extension when present:
  `PROCESS-NAME,io.tailscale.ipn.macsys.network-extension,DIRECT` and
  `PROCESS-NAME,Tailscale,DIRECT`.
- Keep MagicDNS resolvable through Tailscale DNS:
  `*.ts.net = server:100.100.100.100` under `[Host]`.
- Do not put `100.64.0.0/10` or `fd7a:115c:a1e0::/48` in Surge
  `tun-excluded-routes` unless a live route test proves it is necessary. On this
  setup, excluding those ranges can make Surge install competing
  physical-interface routes and steal traffic from Tailscale. Exclude ordinary
  LAN ranges there, then use DIRECT rules for Tailscale.

Read-only checks:

```bash
tailscale status --json
ssh -G <tailscale-host> | awk '$1 ~ /^(hostname|user)$/ {print}'
route -n get <tailscale-ipv4>
netstat -rn -f inet | grep -E '100\.64|100\.100\.100\.100|utun'
scutil --dns | grep -E '100\.100\.100\.100|ts\.net|utun' -C 3
```

The healthy shape is that a Tailscale peer route goes through Tailscale's utun
interface, not Surge's VIF. Surge may still handle non-tailnet traffic in
Enhanced Mode.

## Diagnose First

Check current state:

```bash
# Network health (DNS, proxy RTT, UDP relay); no auth needed
"$surge_cli" diagnostics

# What outbound mode? (0=direct, 1=global, 2=rule)
"$surge_cli" --raw environment

# Shell proxy vars set?
env | grep -i proxy
```

## Symptom → Next Check

| Symptom                                                     | Likely Cause                                 | Next Check                                      |
| ----------------------------------------------------------- | -------------------------------------------- | ----------------------------------------------- |
| `brew install` / `npm install` / `docker pull` hangs        | No proxy for international traffic           | Confirm Surge state and shell proxy variables   |
| `curl` to a remote server hangs despite proxy vars          | Surge upstream is dead                       | Run `"$surge_cli" diagnostics`, check proxy RTT |
| Need direct connection (e.g. debugging latency to a server) | Enhanced Mode is intercepting                | Confirm Enhanced Mode                           |
| Everything suddenly broken                                  | Surge crashed or proxy nodes down            | Run `"$surge_cli" diagnostics` first            |
| Intermittent timeouts                                       | Wrong outbound mode (direct instead of rule) | Confirm outbound mode                           |

## Surge HTTP API Read Checks

Use `GET` for diagnosis.

### Extract API Key

Use the active profile path from `"$surge_cli" --raw dump profile`, the current
Surge UI state, or profile path evidence in the user's request. Do not assume
`default.conf`.

```bash
profile_path="<active Surge profile path>"
x_key=$(perl -ne 'print $1 if /http-api = (.*?)@/' "$profile_path")
```

### Feature State

```bash
# Enhanced mode (system-wide TUN)
xh --verify no GET https://localhost:6171/v1/features/enhanced_mode X-Key:$x_key

# System proxy (macOS system-level HTTP proxy)
xh --verify no GET https://localhost:6171/v1/features/system_proxy X-Key:$x_key

# Outbound mode (rule / direct / proxy)
xh --verify no GET https://localhost:6171/v1/outbound X-Key:$x_key

# Other toggleable features
xh --verify no GET https://localhost:6171/v1/features/mitm X-Key:$x_key
xh --verify no GET https://localhost:6171/v1/features/capture X-Key:$x_key
xh --verify no GET https://localhost:6171/v1/features/rewrite X-Key:$x_key
xh --verify no GET https://localhost:6171/v1/features/scripting X-Key:$x_key
```

### Other Read Operations

```bash
# List modules
xh --verify no GET https://localhost:6171/v1/modules X-Key:$x_key
```

## Quick Status Check

```bash
profile_path="<active Surge profile path>"
x_key=$(perl -ne 'print $1 if /http-api = (.*?)@/' "$profile_path")
echo "Outbound:      $(xh --verify no --body GET https://localhost:6171/v1/outbound X-Key:$x_key | jq -r '.mode')"
echo "System Proxy:  $(xh --verify no --body GET https://localhost:6171/v1/features/system_proxy X-Key:$x_key | jq -r '.enabled')"
echo "Enhanced Mode: $(xh --verify no --body GET https://localhost:6171/v1/features/enhanced_mode X-Key:$x_key | jq -r '.enabled')"
```

## File Locations And Local Hints

- Surge app: `/Applications/Surge.app/`
- Surge CLI: `/Applications/Surge.app/Contents/Applications/surge-cli`
- Config profiles: `~/Library/Application Support/Surge/Profiles/`
- User-specific repos or shell helpers are source evidence only when the user
  names them.

## Gotchas

- Examples use `xh --verify no`; if `xh` is unavailable, use an HTTPS client
  that can ignore the local self-signed API certificate.
- `jq` is required for JSON parsing in the inline scripts.
- The API uses HTTPS with a self-signed cert (`http-api-tls = true`); pass
  `--verify no` or the equivalent option.
- The API key changes per config file — always extract it dynamically, never hardcode.
- Surge proxy ports: HTTP = `6152`, SOCKS5 = `6153`, API = `6171`.
- Enhanced Mode takes about 1 second to fully activate after a user-requested
  toggle; re-check status after that delay.
