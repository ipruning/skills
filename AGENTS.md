# Guidelines for AI Agents

## Architecture

- Mono-repo of AI agent skills (SKILL.md files) for Amp, Codex, and other tools, managed by `skillshare`.
- Each top-level directory is one skill (e.g. `demand-audit-v2/`, `prek/`). Synced external skills live in `_`-prefixed dirs (`_jihuanshe-skills/`, `_planetscale-database-skills/`) and are gitignored — never edit them.
- Python deps managed by `uv` (Python ≥3.14); JS/JSON linted by Biome.

## Build / Lint / Test

- Lint Python: `uv run ruff check .` | Format check: `uv run ruff format --check .`
- Type-check Python: `uv run ty check .`
- Lint Markdown: `markdownlint-cli2` | Lint JSON/JS: `biome ci .` | Spell: `typos`
- Pre-commit hooks via `prek` (see `prek.toml`). No test suite exists.

## Code Style

- 4-space indent everywhere (2-space for `.md`). LF line endings. Final newline required.
- Python: Ruff rules E/W/F/UP/B/SIM/I/TID, line-length 120, target py314. Imports sorted by isort (I).
- JS/JSON: Biome with double quotes, 4-space indent. Organize imports enabled.
- TOML: `tombi` formatter, 4-space indent.

## Synced Skills Ignore Rules

Any dir with `.skillshare-meta.json` is externally synced — exclude it from ALL lint configs:
`.autocorrectignore`, `.markdownlint-cli2.yaml`, `.typos.toml`, `biome.jsonc` (`!!dir/`), `prek.toml` (exclude regex), `pyproject.toml` (`[tool.ruff].exclude` + `[tool.ty.src].exclude`).
Find synced dirs: `fd -H -t f '.skillshare-meta.json' -x dirname {} | sed 's|^\./||' | sort -u`
