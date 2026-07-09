# Image Workbench References

This directory contains runnable regression cases for the CLI, not parameter documentation or task guidance.

Each case directory contains:

- `AGENTS.md` explaining the scenario and the expected observation.
- `case.py` generating its fixture deterministically.

Both cases run locally by default; only `source-backed-mobile-ui/case.py` offers `--run-cli` to hit the real API.

After editing `scripts/image_workbench.py`, run:

```bash
SKILL_DIR=/absolute/path/to/image-workbench
uv run python -m py_compile "$SKILL_DIR/scripts/image_workbench.py"
uv run ruff check "$SKILL_DIR/scripts/image_workbench.py"
uv run ty check "$SKILL_DIR/scripts/image_workbench.py"
uv run --script "$SKILL_DIR/scripts/image_workbench.py" --help
uv run --script "$SKILL_DIR/references/long-screenshot-guardrail/case.py"
uv run --script "$SKILL_DIR/references/source-backed-mobile-ui/case.py"
```

Keep API parameter truth in `../scripts/image_workbench.py` help and
`profiles --json`. Do not recreate flat reference docs here.
