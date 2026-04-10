# Guidelines for AI Agents

## Architecture

Each top-level directory is one skill. A skill contains a SKILL.md and optional supporting files. `skillshare` syncs them to AI tool config directories via symlinks.

Directories prefixed with `_` are externally synced, gitignored, and overwritten on update. Never edit them.

```text
~/.config/skillshare/
├── config.yaml              # Targets, sync mode, ignore rules
└── skills/                  # This Git repo
    ├── <skill-name>/        # Your own skills
    ├── _<org>-skills/       # Org skills (gitignored)
    └── _<community>/        # Community skills (gitignored)
```

## Code Style

4-space indent everywhere, 2-space for Markdown. LF line endings. Final newline required.

- **Python** — Ruff (rules E/W/F/UP/B/SIM/I/TID, line-length 120, target py314). Format: `uv run ruff format --check .`. Lint: `uv run ruff check .`. Type-check: `uv run ty check .`.
- **JS / JSON** — Biome (double quotes, 4-space indent). Lint: `biome ci .`.
- **TOML** — `tombi` formatter, 4-space indent.
- **Markdown** — `markdownlint-cli2`.
- **Spelling** — `typos`.
- **Pre-commit** — `prek` (see `prek.toml`).

## Excluding external skills from linting

Directories containing `.skillshare-meta.json` are externally synced and must be excluded from all lint configs. Find them with:

```bash
fd -H -t f '.skillshare-meta.json' -x dirname {} | sed 's|^\./||' | sort -u
```

Add each directory to these six config files (seven places total — `pyproject.toml` has two sections):

- `.typos.toml` — `[files].extend-exclude`
- `.markdownlint-cli2.yaml` — `ignores`
- `biome.jsonc` — `files.includes` with `!!dir` force-ignore (no trailing `/`)
- `pyproject.toml` — `[tool.ruff].exclude` and `[tool.ty.src].exclude`
- `prek.toml` — top-level `exclude` regex
- `.autocorrectignore`

`_`-prefixed directories are gitignored and never checked in, so they don't need lint excludes. Only non-`_` directories with `.skillshare-meta.json` need them.

When deleting a skill, remove its directory **and** remove its entries from all six config files listed above. Use `skillshare uninstall` when possible; if you `rm -rf` manually, you must clean the configs yourself.

## Running skillshare

Always use non-interactive flags (`--force`, `--all`, `--yes`). AI agents cannot answer prompts. Always run `skillshare sync` after any mutation (`install`, `uninstall`, `update`, `collect`, `target`). Use `--json` when you need to parse output.
