# Client Inputs

Read this before rendering a Linux, Android, Windows, or macOS client.

## Required Values

```text
SERVER_IP
REALITY_SNI
UUID
REALITY_PUBLIC_KEY
REALITY_SHORT_ID
HY2_DOMAIN
HY2_PASSWORD
```

macOS Surge native HY2 needs only `SERVER_IP`, `HY2_DOMAIN`, and
`HY2_PASSWORD`. A platform that uses only one outbound needs only that
outbound's subset. Tailscale exclusions, interface names, service instance
names, and existing policy names come from the actual client host, not from a
different machine's template.

## Authorized Sources

Use values only from one of these sources:

- the user supplied them for this target;
- this task generated them for this server and retained the redacted mapping;
- the user authorized reading the exact server secrets file or client artifact
  over the already identified SSH path.

Do not search credential caches, copy credentials from another VPS, infer a
password from an existing policy, or change SSH identity to obtain them. If an
authorized source is unavailable, stop at a placeholder config and name the
missing values.

Never print `REALITY_PRIVATE_KEY` or `HY2_PASSWORD`. A client receives the
REALITY public key, never the private key. Validate `HY2_DOMAIN` against the
certificate and `REALITY_SNI` against the deployed server config before the
first protocol test.
