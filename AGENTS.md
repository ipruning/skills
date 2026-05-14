# Guidelines for AI Agents

## Architecture

This repo is the source of truth for AI-tool skills. A skill is any directory that contains a `SKILL.md`, plus optional supporting files such as scripts, references, or assets. Skills may live at the repo root or inside grouping directories such as `skills-stable/` and `skills-beta/`.

`skillshare` syncs these skills to AI tool config directories, usually by symlink. Run `skillshare sync` after any skill mutation so installed tools see the latest content.

Directories prefixed with `_` are externally synced, gitignored, and overwritten on update. Never edit `_`-prefixed directories directly.

```text
skills/
├── AGENTS.md
├── skills-stable/           # Stable tracked skills and grouped external skills
├── skills-beta/             # Experimental tracked skills and grouped external skills
├── skillshare/              # Skillshare-related skill content
├── _<source>-skills/        # External synced skills, gitignored, overwritten
└── <skill-name>/            # Optional root-level skill directory
```

## Working on skills

- Prefer editing the existing `SKILL.md` and nearby supporting files over creating new structure.
- Keep trigger guidance explicit: a skill should say when to use it and when not to use it.
- Keep `SKILL.md` concise. Put long scripts, templates, examples, or large references in supporting files and link to them.
- Do not edit generated, vendored, or externally synced content. For external skills, prefer updating through `skillshare` or the upstream source.
- After adding, deleting, moving, installing, uninstalling, updating, or collecting skills, run `skillshare sync`.

## Code Style

4-space indent everywhere, 2-space for Markdown. LF line endings. Final newline required.

- **Python** — Ruff (rules E/W/F/UP/B/SIM/I/TID, line-length 120, target py314). Format: `uv run ruff format --check .`. Lint: `uv run ruff check .`. Type-check: `uv run ty check .`.
- **JS / JSON** — Biome (double quotes, 4-space indent). Lint: `biome ci .`.
- **TOML** — `tombi` formatter, 4-space indent.
- **Markdown** — `markdownlint-cli2`.
- **Spelling** — `typos`.
- **Pre-commit** — `prek` (see `prek.toml`).

## Excluding external skills from linting

Some external skills are checked into this repo under non-`_` paths and are tracked in `.metadata.json`. Treat those paths as vendored content: do not lint or reformat them, and keep all lint exclude configs in sync with `.metadata.json`.

Find the checked-in external paths with:

```bash
jq -r '.entries | keys[] | select(startswith("_") | not)' .metadata.json | sort
```

Add each path to these six config files (eight places total — `pyproject.toml` has three sections):

- `.typos.toml` — `[files].extend-exclude`
- `.markdownlint-cli2.yaml` — `ignores`
- `biome.jsonc` — `files.includes` with `!!dir` force-ignore (no trailing `/`)
- `pyproject.toml` — `[tool.ruff].exclude` and `[tool.ty.src].exclude` use trailing-slash directory paths (`dir/`); `[tool.tombi.files].exclude` uses `dir/**` globs
- `prek.toml` — top-level `exclude` regex
- `.autocorrectignore`

`_`-prefixed directories are gitignored and never checked in, so they do not need lint excludes. Only non-`_` directories listed in `.metadata.json` need excludes.

When deleting a checked-in external skill, remove its directory **and** remove its entries from all six config files listed above. Use `skillshare uninstall` when possible; if you `rm -rf` manually, you must clean the configs yourself.

After a skillshare version upgrade or `skillshare update`, directory names may change or entries may disappear. Always verify that all six config files still match `.metadata.json` — the exclude lists must be an exact 1:1 match with the non-`_` entries.

## Running skillshare

AI agents cannot answer prompts. Use supported non-interactive flags such as `--force`, `--all`, `--yes`, `--no-tui`, explicit selectors, and `--json`; do not start prompt-only workflows. Always run `skillshare sync` after any mutation (`install`, `uninstall`, `update`, `collect`, `target`). Use `--json` when you need to parse output.
