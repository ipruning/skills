# Guidelines for AI Agents

## Architecture

This repo is the source of truth for AI-tool skills. A skill is any directory that contains a `SKILL.md`, plus optional supporting files such as scripts, references, or assets. Skills may live at the repo root or inside grouping directories such as `skills-stable/` and `skills-beta/`.

`skillshare` syncs non-ignored skills to configured AI tool targets, usually by symlink. Run `skillshare sync` after mutating synced skills so configured tools see the latest content. `.skillignore` controls which source skills are skipped.

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
- After adding, deleting, moving, installing, uninstalling, updating, or collecting synced skills, run `skillshare sync`. Changes under ignored paths, such as the current `skills-beta/` ignore, are not exposed to targets unless the ignore or target configuration changes.

## Code Style

4-space indent by default, 2-space for Markdown. LF line endings. Final newline required. Follow the formatter/config for file-type exceptions.

- **Python** — Ruff selects E/W/F/UP/B/SIM/I/TID plus BLE001, ignores E501/TID252, line-length 120, target py314. Format: `uv run ruff format --check .`. Lint: `uv run ruff check .`. Type-check: `uv run ty check .`.
- **JS / JSON / JSONC** — Biome-managed files use double quotes and 4-space indent. Generated or excluded files such as `.metadata.json` may differ; do not reformat them unless the owning tool expects it. Lint: `biome ci .`.
- **TOML** — `uvx tombi lint .`; format config uses 4-space indent.
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

After a skillshare version upgrade or `skillshare update`, directory names may change or entries may disappear. Always verify that the external-skill exclude entries in all six config files match the non-`_` `.metadata.json` entries exactly. Other tool-specific excludes, such as `.metadata.json`, may also exist.

## Running skillshare

AI agents cannot answer prompts. Use supported non-interactive flags such as `--force`, `--all`, `--yes`, `--no-tui`, explicit selectors, and `--json`; do not start prompt-only workflows. Always run `skillshare sync` after any mutation (`install`, `uninstall`, `update`, `collect`, `target`). Use `--json` when you need to parse output.
