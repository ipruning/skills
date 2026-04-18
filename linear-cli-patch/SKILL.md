---
name: linear-cli-patch
description: Install and configure Linear CLI on exe.dev VMs (proxy auth, no API key needed). Triggers when using Linear inside an exe.dev VM.
allowed-tools: Bash(linear:*), Bash(curl:*)
---

# Linear CLI on exe.dev

The exe.dev HTTP Proxy exposes the Linear API at `linear.int.exe.xyz` and injects authentication automatically — no API key required.

## Environment Check

```bash
[ -f /exe.dev/shelley.json ] && echo exe.dev || ([ "$(uname)" = Darwin ] && echo macOS || echo Linux)
```

Only proceed with this skill if the output is `exe.dev`.

## Installation and Login

```bash
curl -sL https://github.com/schpet/linear-cli/releases/download/v2.0.0/linear-x86_64-unknown-linux-gnu.tar.xz -o /tmp/linear-cli.tar.xz
tar -xJf /tmp/linear-cli.tar.xz -C /tmp/
sudo install -m 755 /tmp/linear-x86_64-unknown-linux-gnu/linear /usr/local/bin/linear

echo 'export LINEAR_GRAPHQL_ENDPOINT="https://linear.int.exe.xyz/graphql"' >> ~/.bashrc
export LINEAR_GRAPHQL_ENDPOINT="https://linear.int.exe.xyz/graphql"

linear auth login --key placeholder --plaintext
```

- The archive is `.tar.xz` — extract with `tar -xJf`
- `--plaintext` is required because the VM has no system keyring
- Verify with `linear auth whoami`

## Direct curl on exe.dev

The proxy handles authentication — no token needed:

```bash
curl -s -X POST https://linear.int.exe.xyz/graphql \
  -H "Content-Type: application/json" \
  -d '{"query": "{ viewer { id name email } }"}'
```

See the `linear-cli` skill for command usage and flag details.
