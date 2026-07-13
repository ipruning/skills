# Guidelines for AI Agents

## Architecture

This repo is the source of truth for AI-tool skills and Skillshare extras. A skill is any directory that contains a `SKILL.md`, plus optional supporting files such as scripts, references, or assets. Skills may live at the repo root or inside grouping directories such as `skills-stable/` and `skills-beta/`.

`skillshare` syncs non-ignored skills to configured AI tool targets. Target configuration decides whether sync uses symlinks or copies. `skillshare` also syncs non-skill resources from `extras/` to configured target directories. `.skillignore` controls which source skills are skipped.

Each source checkout owns its first-party skills; the leading underscore does not decide edit ownership. The source checkout's `.metadata.json` decides the boundary: entries in `.metadata.json` are upstream Track-managed; skill directories outside those entries are first-party.

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

## Structural search maintenance

Use the smallest tool that fits: `rg` for exact text; `ast-grep run` for a one-off source-structure investigation; a YAML rule with `valid` and `invalid` tests for a complex or recurring constraint; and `ast-grep scan` wired through `prek` only when the constraint must block merges. Do not add project configuration or a standing gate for an investigation. See `skills-stable/ast-grep/SKILL.md` before authoring or gating rules.

These read-only examples target Python skill scripts in this repository:

```sh
mise exec -- ast-grep run -p 'subprocess.run($$$ARGS)' -l python skills-stable/summarize-lark-meetings/scripts
mise exec -- ast-grep run -p 'getattr($OBJ, $ATTR)' -l python skills-stable/things/scripts
```

## Branch and sync policy

Source checkouts can have different merge rules. Do not infer one checkout's policy from another checkout.

- This source checkout is the user's personal skill source. Direct `main` updates are allowed unless the user asks for a branch, PR, or separate commit shape.
- `_jihuanshe-skills/` is a separate nested source repo. Follow its own `AGENTS.md`: do not commit or push directly to `main`; use a branch and PR for mergeable work.
- Before starting new work in a source checkout, if the worktree is clean or can be safely paused, switch to `main` and pull the upstream state first. If the worktree has uncommitted work, do not force a branch switch; inspect the state and preserve the work, or leave it untouched and start from a fresh git worktree.
- Multiple agent sessions may work in a checkout concurrently. When the worktree is dirty with changes you did not make, or your work needs a branch switch that would move files under another session, create a git worktree instead of switching branches in place: `git worktree add ../skills-worktrees/<topic> -b <branch>`. Remove it after the branch lands (`git worktree remove <path>`).
- Place worktrees outside every skillshare source checkout; a worktree created inside one would be scanned as skill directories. `skillshare` syncs the configured `source.path` checkout, not your cwd, so worktree edits reach synced targets only after they land in the primary checkout. A worktree of this repo also lacks the gitignored nested checkouts (`_<source>-skills/`); read those through the primary checkout.
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

- **Python** — Ruff follows `pyproject.toml` (line-length 120, target py314). Format: `uv run ruff format --check .`. Lint: `uv run ruff check .`. Type-check: `uv run ty check .`.
- **JS / JSON / JSONC** — Biome-managed files use double quotes and 4-space indent. Generated or excluded files such as `.metadata.json` may differ; do not reformat them unless the owning tool expects it. Lint: `biome ci .`.
- **TOML** — `uvx tombi lint .`; format config uses 4-space indent.
- **Markdown** — `markdownlint-cli2`.
- **Spelling** — `typos`.
- **Pre-commit** — `prek` (see `prek.toml`).

## Excluding external skills from linting

Some external skills are checked into this repo under non-`_` paths and are tracked in `.metadata.json`. Treat those paths as vendored content: do not lint or reformat them. Every non-`_` `.metadata.json` entry must be excluded in six config files (eight places total — `pyproject.toml` has three sections):

- `.typos.toml` — `[files].extend-exclude`, `"dir/"`
- `.markdownlint-cli2.yaml` — `ignores`, `"dir/"`
- `biome.jsonc` — `files.includes`, `"!!dir"` (no trailing `/`)
- `pyproject.toml` — `[tool.ruff].exclude` and `[tool.ty.src].exclude` use `"dir/"`; `[tool.tombi.files].exclude` uses `"dir/**"`
- `prek.toml` — top-level `exclude` regex, `^dir/`
- `.autocorrectignore` — `dir/`

`mise run check-lint-excludes` verifies both directions — metadata entries missing from a config, and stale excludes whose entry is gone — and reports the exact literal to add or remove. The pre-commit hook runs it on every commit; run it manually after `skillshare install`, `uninstall`, or `update`, since updates can rename directories. Keep unrelated tool-specific excludes unchanged; `_`-prefixed directories are gitignored and need no excludes.

When deleting a checked-in external skill, use `skillshare uninstall` when possible; if you `rm -rf` manually, remove the directory's entries from all six config files — the checker lists the leftovers.

## Running skillshare

Use supported non-interactive flags such as `--force`, `--yes`, `--no-tui`, explicit selectors, and `--json`; do not start prompt-only workflows. Always run `skillshare sync --all` after any mutation (adding, deleting, or moving synced skills, `install`, `uninstall`, `update`, `collect`, `target`, or extras edits). Use `--json` when you need to parse output. Changes under paths listed in `.skillignore` are not exposed to targets unless the ignore or target configuration changes; check the file rather than assuming a whole collection is ignored.

Sync targets such as `~/.claude/skills` are skillshare projections. Never point a third-party skill installer (for example `npx skills add ... -g`) at a target directory; anything written there directly is untracked shadow state that no audit or prune sees. When a vendor CLI embeds its own skills, prefer a thin first-party router skill that reads them at runtime over installing copies into a source repository.
