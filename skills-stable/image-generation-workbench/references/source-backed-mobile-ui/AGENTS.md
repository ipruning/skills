# Source-Backed Mobile UI Case

Use this case when checking that a source-backed portrait/mobile UI flow keeps an
intentional canvas ratio instead of drifting to a landscape default.

Run:

```bash
uv run --script case.py
```

The script creates a deterministic portrait fixture under `/tmp`, prints the
recommended `annotate-image` command, and explains the expected `1024x1536`
output geometry. It does not call the OpenAI API unless you pass `--run-cli` and
provide credentials in the environment.
