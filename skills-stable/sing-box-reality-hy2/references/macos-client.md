# macOS Client Reference

Use this for macOS Surge and optional macOS sing-box sidecar.

Resolve values and their authorized source through
[client-inputs.md](client-inputs.md) before rendering a policy.

## Surge Boundary

Surge cannot directly use VLESS REALITY.

Evidence to check when in doubt:

```text
surge-cli --check with a vless line returns:
Error: Unknown proxy type: vless
```

Surge supports HY2 and Snell for this stack. Use:

```text
HY2: native Surge Hysteria2 policy
Snell: existing fallback policy
REALITY: only via local sing-box sidecar exposing SOCKS/Mixed
```

This reference only wires an existing Snell policy into the REALITY + HY2 stack. For
Snell service health, Snell v6 migration, UDP relay/NAT interpretation, or
other Snell-specific work, use `$operate-snell`.

## Native Surge HY2 Policy

Policy shape:

```ini
vps-1-hy2 = hysteria2, vps-1.example.com, 443, password=<HY2_PASSWORD>, sni=vps-1.example.com
```

Do not print the password. Redact it in chat and logs.

`download-bandwidth` is optional in Surge and measured in Mbps. Omit it when
there is no measurement. When setting it, use a sustainable value measured on
the current client network with at least three same-endpoint runs; never copy a
value from another hotspot or VPS.

## surge.conf Integration

Expected shape:

```ini
[General]
skip-proxy = <preserve-existing-entries>, 100.64.0.0/10, <SERVER_IP>
tun-excluded-routes = 192.168.0.0/16, 10.0.0.0/8, 172.16.0.0/12

[Proxy]
vps-1-hy2 = hysteria2, <HY2_DOMAIN>, 443, password=<HY2_PASSWORD>, sni=<HY2_DOMAIN>

[Proxy Group]
PROXY = select, vps-1-hy2

[Rule]
IP-CIDR,<SERVER_IP>/32,DIRECT,no-resolve
DOMAIN-SUFFIX,tailscale.com,DIRECT
DOMAIN-SUFFIX,tailscale.io,DIRECT
IP-CIDR,100.64.0.0/10,DIRECT,no-resolve
IP-CIDR6,fd7a:115c:a1e0::/48,DIRECT,no-resolve
PROCESS-NAME,io.tailscale.ipn.macsys.network-extension,DIRECT
PROCESS-NAME,Tailscale,DIRECT

[Host]
*.ts.net = server:100.100.100.100
```

Only when a working Snell policy already exists and the user asks to retain it,
append that existing policy to `[Proxy]` and the group. Preserve its actual
port, version, and options instead of generating new Snell defaults. Snell
health and repair remain owned by `$operate-snell`.

Do not copy Linux sing-box Tailscale exclusions into Surge
`tun-excluded-routes`. On macOS Surge, keep ordinary LAN ranges excluded from
VIF, route Tailscale by DIRECT rules, and preserve MagicDNS through
`100.100.100.100`. Verify with `route -n get <tailscale-peer-ipv4>`: a healthy
live route resolves to the Tailscale utun interface, not the Surge VIF.

For a disposable smoke test, copy the active profile to a dedicated temporary
profile under the `ConfigDirectoryPath` recorded in
`~/Library/Application Support/com.nssurge.surge-mac/KDDefaults.plist`. Keep
the copy mode `0600` and add only the test policy plus the `SERVER_IP` DIRECT
rule. Do not overwrite the active profile. Record `SelectedConfigName` before
switching and pass the temporary basename without `.conf` to `switch-profile`;
the filename with its extension does not select the profile. Restore the
original basename in an exit trap, then delete the temporary profile and
protected credential file. A new file in `ConfigDirectoryPath` needs no
`reload`, import, registry edit, or Surge restart.

The `SERVER_IP` DIRECT rule also applies to a local sing-box sidecar's own TCP
and UDP sockets. Without it, Surge Enhanced Mode can capture the sidecar before
the protocol reaches the VPS. A sidecar error shaped like
`read udp 198.18.0.1:<port>-><SERVER_IP>:443: connection refused` is local VIF
path evidence; verify the temporary DIRECT rule before changing the server.

`surge-cli switch-profile` returning exit code zero is not activation proof: a
missing profile can return `(null)` with exit code zero. Require a JSON
`result=success`, then poll `dump policy` for the concrete test policy and
`dump rule` for the `SERVER_IP` DIRECT rule with a deadline. Runtime profile
activation is asynchronous. After restoration, poll until both temporary
entries are absent; one immediate dump can still show the old profile. A
deadline expiry fails the switch or restoration.

For a durable profile edit:

```bash
defaults_plist="$HOME/Library/Application Support/com.nssurge.surge-mac/KDDefaults.plist"
config_dir="$(plutil -extract ConfigDirectoryPath raw "$defaults_plist")"
config_name="$(plutil -extract SelectedConfigName raw "$defaults_plist")"
profile_path="$config_dir/$config_name.conf"

/Applications/Surge.app/Contents/Applications/surge-cli --check "$profile_path"
/Applications/Surge.app/Contents/Applications/surge-cli reload
/Applications/Surge.app/Contents/Applications/surge-cli --raw set ProxyGroupSelection.PROXY=vps-1-hy2
```

Validate:

```bash
surge-cli --raw test-policy vps-1-hy2
surge-cli --raw test-policy-external-ip vps-1-hy2
surge-cli --raw test-policy-udp vps-1-hy2
surge-cli --raw environment | jq -r '.environment.ProxyGroupSelection.PROXY'
```

Group-level tests on select groups may return `{}`. Test the concrete policy instead.

## REALITY via Sidecar

Only for macOS, not iOS.

Use an installed binary only when its version passes
[version-compatibility.md](version-compatibility.md). For a one-shot sidecar on
a Mac without sing-box, stage the matching official release for `uname -m` in
a mode `0700` temporary directory instead of installing it globally. Verify the
asset digest from the release's checksum artifact when present; when the
release has no checksum file, use the digest published in the official GitHub
release asset metadata. Then require the staged binary to report the expected
version.

Run sing-box locally with a mixed inbound:

```json
{
  "type": "mixed",
  "tag": "mixed-in",
  "listen": "127.0.0.1",
  "listen_port": 2080
}
```

Surge policy:

```ini
REALITY-via-singbox = socks5, 127.0.0.1, 2080
```

This keeps Surge rules but adds a local dependency. Prefer native HY2/Snell unless the user explicitly wants REALITY through Surge on macOS.
