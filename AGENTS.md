# Guidelines for AI Agents

## Architecture

- Mono-repo of coding agent skills (SKILL.md files) managed by `skillshare`.
- Each top-level directory is one skill (e.g. `demand-audit-v2/`, `prek/`).
- `_`-prefixed dirs are externally synced (gitignored) — never edit them.

## Repo Layout

```text
~/.config/skillshare/
├── config.yaml              # Targets, sync mode, ignore rules
├── registry.yaml            # Installed external skill registry
└── skills/                  # Source dir (= this Git repo)
    ├── <skill-name>/        # Your own skills
    ├── _<org>-skills/       # Org skills (gitignored, --track installed)
    └── _<community>/        # Community skills (gitignored)
```

## Code Style

- 4-space indent everywhere (2-space for `.md`). LF line endings. Final newline required.
- Python: Ruff rules E/W/F/UP/B/SIM/I/TID, line-length 120, target py314.
- JS/JSON: Biome with double quotes, 4-space indent.
- TOML: `tombi` formatter, 4-space indent.

## Lint

- Python: `uv run ruff check .` / `uv run ruff format --check .`
- Type-check: `uv run ty check .`
- Markdown: `markdownlint-cli2` | JSON/JS: `biome ci .` | Spell: `typos`
- Pre-commit: `prek` (see `prek.toml`)

## Synced Skills Ignore Rules

Any dir with `.skillshare-meta.json` is externally synced — exclude it from ALL lint configs.
Find them: `fd -H -t f '.skillshare-meta.json' -x dirname {} | sed 's|^\./||' | sort -u`
