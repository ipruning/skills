# macOS Surge Operator Actions

Use this reference only to write a manual command plan after the user asks for a
local Surge/macOS toggle or repair. The actor for these commands is the human
operator or a separately authorized execution path, not the read-only diagnosis
path.

## API Key

Use the active profile path from `"$surge_cli" --raw dump profile`, the current
Surge UI state, or profile path evidence in the user's request. Do not assume
`default.conf`.

```bash
profile_path="<active Surge profile path>"
x_key=$(perl -ne 'print $1 if /http-api = (.*?)@/' "$profile_path")
```

## Feature Toggles

```bash
# Enhanced Mode (system-wide TUN)
xh --verify no POST https://localhost:6171/v1/features/enhanced_mode X-Key:$x_key enabled:=true
xh --verify no POST https://localhost:6171/v1/features/enhanced_mode X-Key:$x_key enabled:=false

# System Proxy
xh --verify no POST https://localhost:6171/v1/features/system_proxy X-Key:$x_key enabled:=true
xh --verify no POST https://localhost:6171/v1/features/system_proxy X-Key:$x_key enabled:=false

# Outbound mode
xh --verify no POST https://localhost:6171/v1/outbound X-Key:$x_key mode=rule
xh --verify no POST https://localhost:6171/v1/outbound X-Key:$x_key mode=direct
```

## Local Shell Proxy

```bash
# Confirm the local Surge ports before exporting these values.
export http_proxy=http://127.0.0.1:6152
export https_proxy=http://127.0.0.1:6152
export all_proxy=socks5://127.0.0.1:6153

# Unset proxy
unset http_proxy https_proxy all_proxy
```

## Maintenance Actions

```bash
# Reload profile
xh --verify no POST https://localhost:6171/v1/profiles/reload X-Key:$x_key

# Flush DNS
xh --verify no POST https://localhost:6171/v1/dns/flush X-Key:$x_key

# Switch policy group selection
xh --verify no POST https://localhost:6171/v1/policy_groups/select X-Key:$x_key group_name='GroupName' policy='ProxyName'
```

After the operator runs a toggle, wait about 1 second and re-read the relevant
GET endpoint before reporting the result.
