# Version Compatibility

This skill is validated against sing-box `v1.13.14`. Discover the installed version before rendering configuration:

```bash
sing-box version | sed -n '1p'
```

On Debian or Ubuntu, also read the versions actually offered by the configured repository:

```bash
apt-cache madison sing-box
```

Apply the templates directly only to `v1.13.14`. For another `1.13.x` patch, render a candidate and run that binary's `sing-box check` before replacing live configuration. For `1.14` or another minor line, read the target release's migration notes and configuration reference first; do not infer compatibility from the field names.

The version-sensitive defaults in this package have immutable source anchors:

- An omitted `network` uses TCP and UDP: [option/types.go at v1.13.14](https://github.com/SagerNet/sing-box/blob/v1.13.14/option/types.go#L39-L43).
- REALITY requires enabled uTLS and accepts at most eight decoded short-ID bytes: [reality_client.go at v1.13.14](https://github.com/SagerNet/sing-box/blob/v1.13.14/common/tls/reality_client.go#L54-L80).
- Empty HY2 bandwidth values use BBR: [Hysteria2 outbound at v1.13.14](https://github.com/SagerNet/sing-box/blob/v1.13.14/docs/configuration/outbound/hysteria2.md#up_mbps-down_mbps).
- TUN defaults to `mixed` with the gVisor build tag and `system` without it: [TUN inbound at v1.13.14](https://github.com/SagerNet/sing-box/blob/v1.13.14/docs/configuration/inbound/tun.md#stack).

The Debian/Ubuntu recipes install and hold the validated patch. Treat that hold as an explicit upgrade gate, not a forgotten package state:

```bash
apt-mark showhold | grep -x sing-box
```

At a planned upgrade, install the target binary in a test environment, migrate and check a candidate config, run both external protocol tests, then remove the hold and upgrade. Do not remove the hold merely because a newer package exists.
