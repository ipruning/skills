# Guidelines for AI Agents

## Architecture

This repo is the source of truth for AI-tool skills and Skillshare extras. A skill is any directory that contains a `SKILL.md`, plus optional supporting files such as scripts, references, or assets. Skills may live at the repo root or inside grouping directories such as `skills-stable/` and `skills-beta/`.

`skillshare` syncs non-ignored skills to configured AI tool targets. Target configuration decides whether sync uses symlinks or copies. `skillshare` also syncs non-skill resources from `extras/` to configured target directories. Run `skillshare sync --all` after mutating synced skills or extras so configured tools see the latest content. `.skillignore` controls which source skills are skipped.

The current source checkout owns its first-party skills. A nested source checkout owns its own first-party skills. The leading underscore does not decide edit ownership. The source checkout's `.metadata.json` decides the boundary: entries in `.metadata.json` are upstream Track-managed; skill directories outside those entries are first-party.

`CLAUDE.md` at the repo root is a symlink to `AGENTS.md` so Claude Code loads the same guidelines. Edit `AGENTS.md` only; never replace the symlink with a copy. Nested source checkouts use the same arrangement.

```text
skills/
├── AGENTS.md
├── CLAUDE.md -> AGENTS.md
├── extras/                  # Skillshare extras, grouped by target tool
│   ├── amp/AGENTS.md
│   ├── codex/AGENTS.md
│   └── claude/CLAUDE.md
├── skills-stable/           # Stable tracked skills and grouped external skills
├── skills-beta/             # Experimental tracked skills and grouped external skills
├── skillshare/              # Skillshare-related skill content
├── _<source>-skills/        # Nested source checkouts
└── <skill-name>/            # Optional root-level skill directory
```

## Working on skills

- Edit the existing `SKILL.md` and nearby supporting files before creating new structure.
- Edit first-party skills in the source checkout that owns them.
- When the user names a nested source checkout, enter that checkout, read its `AGENTS.md`, and apply its `.metadata.json` boundary.
- For global harness instructions, edit the full target-specific file under `extras/{amp,codex,claude}/`; do not generate these files from a shared template.
- Keep trigger guidance explicit: a skill should say when to use it and when not to use it.
- Keep `SKILL.md` concise. Put long scripts, templates, examples, or large references in supporting files and link to them.
- Before adding or heavily revising a first-party skill, review it against the five-layer checklist in `_jihuanshe-skills/skills-stable/skill-roast/SKILL.md`. The checklist also covers drafting a new skill from scratch: run its layers in reverse to outline the first draft.
- Write first-party `SKILL.md` bodies in Chinese classic prose with complete sentences. Keep the frontmatter description, key terms, code, code comments, and tables in English. Supporting references may stay in English.
- Do not edit generated, vendored, or upstream Track-managed content.
- After adding, deleting, moving, installing, uninstalling, updating, or collecting synced skills or extras, run `skillshare sync --all`. Changes under paths listed in `.skillignore` are not exposed to targets unless the ignore or target configuration changes; check the file rather than assuming a whole collection is ignored.

## Branch and sync policy

Source checkouts can have different merge rules. Do not infer one checkout's policy from another checkout.

- This source checkout is the user's personal skill source. Direct `main` updates are allowed unless the user asks for a branch, PR, or separate commit shape.
- `_jihuanshe-skills/` is a separate nested source repo. Follow its own `AGENTS.md`: do not commit or push directly to `main`; use a branch and PR for mergeable work.
- Before starting new work in a source checkout, if the worktree is clean or can be safely paused, switch to `main` and pull the upstream state first. If the worktree has uncommitted work, do not force a branch switch; inspect the state and preserve the work.
- After a PR is squash-merged upstream, treat the local feature branch as stale. Switch to `main`, pull, and branch again before continuing related work. Do not stack new edits on an old branch whose commits no longer match upstream history.

## Working on Skillshare extras

- Use `extras/<name>/...` for non-skill resources. For global harness prompts, keep the simple target-grouped layout: `extras/amp/AGENTS.md`, `extras/codex/AGENTS.md`, and `extras/claude/CLAUDE.md`.
- Do not use Skillshare `agents_source` for `AGENTS.md` / `CLAUDE.md`; Skillshare agents are single-file sub-agent definitions, while these files are always-loaded harness instructions.
- Keep global harness prompt files as complete, directly editable documents. Avoid shared-template generators unless the user explicitly asks for a generated model again.
- When adding a new extra or target, update the active Skillshare config (`extras_source` and `extras:` entries) in the environment that syncs it. If that config is maintained by another repo, make that repo change as a separate logical commit.
- Use `mode: copy` for extras whose target is a tool root containing unrelated files, such as `~/.codex`, `~/.claude`, or `~/.config/amp`. Use `merge` only for dedicated target directories where pruning Skillshare-managed symlinks is safe.
- Before a real sync after config changes, run `skillshare extras list --json` and `skillshare sync extras --dry-run --force --json`; confirm the expected targets, modes, and `pruned` counts. After syncing copy-mode prompt files, `cmp` the source and live target when practical.

## Code Style

Use 4-space indentation by default and 2-space indentation in Markdown files. Use LF line endings and final newlines. Follow the formatter/config for file-type exceptions.

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

After a skillshare version upgrade or `skillshare update`, directory names may change or entries may disappear. Always verify that the external-skill exclude entries in all six config files match the non-`_` `.metadata.json` entries exactly. Keep unrelated tool-specific excludes unchanged.

## Running skillshare

Use supported non-interactive flags such as `--force`, `--yes`, `--no-tui`, explicit selectors, and `--json`; do not start prompt-only workflows. Always run `skillshare sync --all` after any mutation (`install`, `uninstall`, `update`, `collect`, `target`, or extras edits). Use `--json` when you need to parse output.
