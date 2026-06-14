# macOS Surge Network Triage

These checks apply when the failure is on the user's macOS machine and Surge is
part of the network path. Read state first. Do not change Enhanced Mode, System
Proxy, outbound mode, shell proxy variables, DNS, or policy selection during
diagnosis. If the user explicitly asks for a local toggle or repair command,
read [macOS Surge Operator Actions](macos-surge-operator-actions.md).

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

## Two Proxy Layers

| Layer               | Mechanism                              | Scope                                       | State Check                  |
| ------------------- | -------------------------------------- | ------------------------------------------- | ---------------------------- |
| Shell env vars      | `http_proxy`/`https_proxy`/`all_proxy` | Per-shell, only tools that respect env vars | `env \| grep -i proxy`       |
| Surge Enhanced Mode | System-wide TUN (virtual NIC)          | ALL traffic, every process                  | HTTP API `GET` feature state |

**Neither is always correct:**

- No proxy + no enhanced mode → international requests hang.
- Env vars set + Surge unhealthy → worse than no proxy (everything hangs on dead upstream).
- Enhanced Mode routes traffic system-wide and can break direct-connection debugging.

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

| Symptom                                                     | Likely Cause                                 | Next Check                                    |
| ----------------------------------------------------------- | -------------------------------------------- | --------------------------------------------- |
| `brew install` / `npm install` / `docker pull` hangs        | No proxy for international traffic           | Confirm Surge state and shell proxy variables |
| `curl` to a remote server hangs despite proxy vars          | Surge upstream is dead                       | Run `"$surge_cli" diagnostics`, check proxy RTT |
| Need direct connection (e.g. debugging latency to a server) | Enhanced Mode is intercepting                | Confirm Enhanced Mode                         |
| Everything suddenly broken                                  | Surge crashed or proxy nodes down            | Run `"$surge_cli" diagnostics` first          |
| Intermittent timeouts                                       | Wrong outbound mode (direct instead of rule) | Confirm outbound mode                         |

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
xh GET  https://localhost:6171/v1/features/enhanced_mode X-Key:$x_key

# System proxy (macOS system-level HTTP proxy)
xh GET  https://localhost:6171/v1/features/system_proxy X-Key:$x_key

# Outbound mode (rule / direct / proxy)
xh GET  https://localhost:6171/v1/outbound X-Key:$x_key

# Other toggleable features
xh GET https://localhost:6171/v1/features/mitm X-Key:$x_key
xh GET https://localhost:6171/v1/features/capture X-Key:$x_key
xh GET https://localhost:6171/v1/features/rewrite X-Key:$x_key
xh GET https://localhost:6171/v1/features/scripting X-Key:$x_key
```

### Other Read Operations

```bash
# List modules
xh GET https://localhost:6171/v1/modules X-Key:$x_key
```

## Quick Status Check

```bash
profile_path="<active Surge profile path>"
x_key=$(perl -ne 'print $1 if /http-api = (.*?)@/' "$profile_path")
echo "Outbound:      $(xh --body GET https://localhost:6171/v1/outbound X-Key:$x_key | jq -r '.mode')"
echo "System Proxy:  $(xh --body GET https://localhost:6171/v1/features/system_proxy X-Key:$x_key | jq -r '.enabled')"
echo "Enhanced Mode: $(xh --body GET https://localhost:6171/v1/features/enhanced_mode X-Key:$x_key | jq -r '.enabled')"
```

## File Locations And Local Hints

- Surge app: `/Applications/Surge.app/`
- Surge CLI: `/Applications/Surge.app/Contents/Applications/surge-cli`
- Config profiles: `~/Library/Application Support/Surge/Profiles/`
- User-specific repos or shell helpers are source evidence only when the user
  names them.

## Gotchas

- Examples use `xh`; if it is unavailable, use an HTTPS client that can ignore
  the local self-signed API certificate.
- `jq` is required for JSON parsing in the inline scripts.
- The API uses HTTPS with a self-signed cert (`http-api-tls = true`). `xh` handles this fine.
- The API key changes per config file — always extract it dynamically, never hardcode.
- Surge proxy ports: HTTP = `6152`, SOCKS5 = `6153`, API = `6171`.
- Enhanced Mode takes about 1 second to fully activate after a user-requested
  toggle; re-check status after that delay.
