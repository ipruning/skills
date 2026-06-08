# Long Screenshot Guardrail Case

Use this case when checking that the CLI rejects extreme screenshot ratios before
the image API can silently recompose them.

Run:

```bash
uv run --script case.py
```

The script creates a `322x2595` long screenshot fixture under `/tmp` and invokes
`annotate-image` with `--aspect-policy match-input`. The expected result is a
non-zero exit with a clear message telling the caller to crop, slice, or compose
the long page outside the raster image.
