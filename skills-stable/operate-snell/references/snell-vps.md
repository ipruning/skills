# Snell VPS

A pure Snell VPS has a clean OS, one Snell service, key-only SSH, the ports it
needs, a small proxy sysctl set, bounded logs, and swap as an OOM cushion. Do
not turn a pure Snell VPS into a panel host.

## First Decide The Host Type

Pure Snell VPS:

- Keep the host plain.
- Do not add Docker, Nginx, panels, dashboards, heavy monitoring, or broad
  firewall lists unless the user asks.
- Open SSH and Snell, nothing else.

Container or app host:

- Preserve Docker, x-ui, nginx-proxy-manager, web ports, and admin ports that
  are already serving real workloads.
- Map public ports before closing anything.
- Bring Snell itself toward the baseline; do not force the whole host into a
  pure-node firewall shape.

## Read State Before Repair

Identify the actual unit, binary, configuration path, listener, firewall owner, and client profile before replacing anything. Config files and unit values can contain a PSK; print metadata and key names, not values.

```bash
mapfile -t snell_units < <(systemctl list-unit-files '*snell*.service' --no-legend | awk '{ print $1 }')
if test "${#snell_units[@]}" -ne 1; then
  printf 'expected exactly one Snell unit, found %d:\n' "${#snell_units[@]}" >&2
  printf '  %s\n' "${snell_units[@]}" >&2
  exit 1
fi
snell_unit=${snell_units[0]}
systemctl show "$snell_unit" \
  -p User -p Group -p FragmentPath -p ActiveState -p SubState -p MainPID -p NRestarts || exit 1
unit_capture=$(mktemp)
chmod 600 "$unit_capture"
if systemctl cat "$snell_unit" >"$unit_capture"; then
  awk -F= '/^[A-Za-z][A-Za-z0-9]+=/ { print "unit-directive=" $1 }' "$unit_capture"
  grep -Eic 'psk|token|password|secret|credential' "$unit_capture" | \
    awk '{ print "unit-secret-marker-count=" $1 }'
else
  echo "unit contents unavailable; repair mapping not verified" >&2
  rm -f "$unit_capture"
  exit 1
fi
rm -f "$unit_capture"
main_pid=$(systemctl show "$snell_unit" -p MainPID --value)
test "$main_pid" -gt 0 || { echo "Snell has no running MainPID; binary/config mapping not verified" >&2; exit 1; }
binary_path=$(readlink -f "/proc/$main_pid/exe") || exit 1
config_path=$(python3 - "$main_pid" <<'PY'
import pathlib
import sys

args = pathlib.Path(f"/proc/{sys.argv[1]}/cmdline").read_bytes().split(b"\0")
for index, arg in enumerate(args[:-1]):
    if arg in {b"-c", b"--config"}:
        config = pathlib.Path(args[index + 1].decode())
        if not config.is_absolute():
            config = pathlib.Path(f"/proc/{sys.argv[1]}/cwd").resolve() / config
        print(config.resolve())
        break
PY
)
test -n "$config_path" || { echo "running Snell config path could not be derived" >&2; exit 1; }
file "$binary_path" || exit 1
sha256sum "$binary_path" || exit 1
stat -c '%a %U:%G %s %y %n' "$config_path" || exit 1
config_keys=$(awk -F= '/^[[:space:]]*[A-Za-z0-9_-]+[[:space:]]*=/{ key=$1; gsub(/[[:space:]]/, "", key); print "config-key=" key }' "$config_path") || exit 1
test -n "$config_keys" || { echo "no Snell config keys could be inventoried" >&2; exit 1; }
printf '%s\n' "$config_keys"
listener_rows=$(ss -H -tulpen | awk -v pid="$main_pid" 'index($0, "pid=" pid ",") { print }') || exit 1
test -n "$listener_rows" || { echo "running Snell process has no mapped listener" >&2; exit 1; }
printf '%s\n' "$listener_rows"
if command -v ufw >/dev/null 2>&1; then ufw status verbose; fi
if command -v nft >/dev/null 2>&1; then nft list ruleset; fi
```

Capture recent journal output into a root-only file and redact credential-shaped values before putting excerpts in a transcript. Treat missing unit, binary, config, listener, or client ownership as a repair blocker, not permission to install a new baseline over unknown state.

Repair in this order:

1. Record the installed binary hash/architecture, unit fragment and drop-ins, config metadata, listeners, firewall path, service user, and a working client profile. Preserve binary, unit, and config rollback copies outside their target paths.
2. Stage the official artifact in a root-only temporary directory. Match architecture and intended Snell version. Verify an official digest when one is published; a locally recorded SHA-256 without an official comparator proves only which bytes were staged.
3. Stage the config as `root:snell` mode `0640` with the current schema. Never echo the PSK. Confirm the service user can read it but cannot replace the root-owned file, and confirm transport requirements from the same server version and client profile before changing TCP/UDP rules.
4. Stage a unit or drop-in and run `systemd-analyze verify`; target-unit warnings fail validation. Do not overwrite the live unit or binary until rollback files and the current SSH recovery path are proven.
5. Apply binary, config, and unit as one maintenance change, run `daemon-reload`, then restart once. On failed start, missing listener, unexpected user, or repeated restart, restore all three artifacts and re-verify the old service.
6. Verify `ActiveState`, `NRestarts`, the exact TCP/UDP listener, firewall rule, and an end-to-end client request from outside the host. Only that closes the repair; `systemctl active` alone does not.

## Snell Service

Get `snell-server` from the official zip, `https://dl.nssurge.com/snell/snell-server-v<VERSION>-linux-<ARCH>.zip`; current versions and release notes are on the Surge Knowledge Base Snell page. Do not use third-party one-click installers — they add panels and firewall rules this baseline rejects.

Use a dedicated service user and a small unit:

```bash
getent group snell >/dev/null || groupadd --system snell
id snell >/dev/null 2>&1 || \
  useradd --system --gid snell --home-dir /nonexistent \
    --shell /usr/sbin/nologin snell
install -d -o root -g snell -m 0750 /etc/snell
install -o root -g snell -m 0640 snell-server.conf \
  /etc/snell/snell-server.conf
runuser -u snell -- test -r /etc/snell/snell-server.conf
if runuser -u snell -- test -w /etc/snell/snell-server.conf; then
  echo "snell service user must not be able to rewrite its config" >&2
  exit 1
fi
if runuser -u snell -- test -w /etc/snell; then
  echo "snell service user must not be able to replace its config" >&2
  exit 1
fi
```

Keep `/usr/local/bin/snell-server` root-owned and executable. Install the unit
below as `/etc/systemd/system/snell-server.service` mode `0644`.
Run `systemd-analyze verify /etc/systemd/system/snell-server.service` before
`daemon-reload`. After activation, verify
`systemctl show snell-server.service -p User -p Group` reports `snell` and the
running process can still read the same config path.

```ini
[Service]
Type=simple
User=snell
Group=snell
ExecStart=/usr/local/bin/snell-server -c /etc/snell/snell-server.conf
Restart=always
RestartSec=2
LimitNOFILE=1048576
UMask=0077
```

Do not add aggressive systemd sandboxing by default. In particular, do not
copy in `PrivateDevices`, `ProtectSystem`, `RestrictAddressFamilies`, broad
capability restrictions, `NoNewPrivileges`, or `PrivateTmp` unless the user
asked for that hardening and the Snell UDP path has been tested afterward.

Derive transport requirements from the installed version, official release notes,
server config, listeners, firewall, and client profile. Do not infer a future or
unpublished version's UDP/TCP behavior from an older release.

## SSH

Keep the existing verified SSH ownership model and key-only access. Do not
force non-root admin users, `AllowUsers`, or guessed `MaxAuthTries` values onto
a single-owner Snell VPS unless the user asks. Independent SSH redesign or
whole-host access audits belong to `$operate-linux-servers`.

## Firewall

For a pure Snell VPS, start with SSH and the configured Snell TCP port:

```text
22/tcp
<snell-port>/tcp
```

Add `<snell-port>/udp` only when the installed server and client configuration
actually use UDP/QUIC. Verify both the UDP listener and an application-level
client path before and after changing the firewall.

UFW and nftables are both fine. Keep one clear owner for host firewall rules.
Do not mix UFW, hand-written iptables, nftables, Docker rules, and large IP
blacklists without a reason.

## Proxy Sysctl

Use the evidence-gated baseline in
[snell-operator-action-patterns.md](snell-operator-action-patterns.md). Confirm
BBR support and sysctl writability before writing. Reserve the real Snell port,
not a copied example port; reserved ports only matter inside
`ip_local_port_range`.

Do not make `nf_conntrack_max` a required baseline. Raise it only when Docker,
NAT, stateful firewall rules, or observed conntrack pressure justify it.

Do not copy broad TCP buffer, `tcp_tw_reuse`, `tcp_abort_on_overflow`, or
50-line tuning lists.

## Logs And Swap

Bound journald on noisy nodes through a drop-in in `/etc/systemd/journald.conf.d/`:

```ini
[Journal]
SystemMaxUse=256M
RuntimeMaxUse=64M
```

Validate the file with the installed systemd tooling, restart journald only in
an approved maintenance window, and read effective limits afterward:

```bash
systemd-analyze cat-config systemd/journald.conf
journalctl --disk-usage
```

Swap is not a throughput tuning. If swap is already present and idle, leave it
alone. Adding or resizing swap is a separate whole-host change and belongs to
`$operate-linux-servers` when the user requests it or measured memory pressure
requires a plan.

## Do Not Do This By Default

| Do not | Reason |
| --- | --- |
| Add complex systemd sandboxing | It can break Snell v5 UDP/QUIC |
| Close UDP without checking | Existing UDP/QUIC deployments may need it |
| Upgrade a stable fleet to an unverified release | Treat protocol-version changes as deliberate migrations |
| Tighten an app/container host like a pure Snell VPS | Docker and app ports may be real traffic |
| Tune conntrack without evidence | It is not the normal bottleneck on a plain Snell node |
| Copy large sysctl lists | They hide risk and rarely solve the real bottleneck |
