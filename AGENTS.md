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
- For first-party skills owned directly by this checkout, write `SKILL.md` bodies, frontmatter `description` values, and user-visible fields in `agents/openai.yaml` in Chinese by default, using clear, complete sentences. Keep product names, protocols, tool names, API identifiers, code symbols, and terms that lose precision in translation in their original language. Supporting references may stay in English.
- Do not apply this language policy to generated, vendored, or upstream Track-managed content, and do not edit that content directly. Nested source checkouts follow their own `AGENTS.md`; do not normalize or rewrite their language policy from the parent checkout.

## Structural search maintenance

Use the smallest tool that fits: `rg` for exact text; `ast-grep run` for a one-off source-structure investigation; and a YAML rule with `valid` and `invalid` tests for a complex or recurring constraint. Put a repository-wide merge gate in CI or a canonical `mise` task, not in a Git hook. Do not add project configuration or a standing gate for an investigation.

This read-only example targets a Python skill script in this repository:

```sh
mise exec -- ast-grep run -p 'getattr($OBJ, $ATTR)' -l python skills-beta/things/scripts
```

## Skillshare source and publication boundaries

`skillshare status --json` reports the configured `source.path`. Global Skillshare mutations and syncs operate on that primary checkout regardless of cwd; running them in a task worktree does not mutate or publish that worktree. Treat a real sync as an authorized external write, not as repository validation.

- Keep worktrees outside every configured Skillshare source. An in-source worktree is scanned as skill content. Gitignored nested checkouts such as `_<source>-skills/` may exist only in the primary checkout; follow their own `AGENTS.md` when editing them.
- Source checkouts, not synchronized copies or target directories, are the maintenance sources. Never install or edit skills directly in projection targets such as `~/.claude/skills`; those writes become untracked shadow state.
- A merged change is not live until the primary checkout contains it, an authorized real sync has completed, and the affected projection or behavior has been verified.
- `_jihuanshe-skills/` is a separate source; its own `AGENTS.md` governs work there.

## Working on Skillshare extras

- Use `extras/<name>/...` for non-skill resources. For global harness prompts, keep the simple target-grouped layout: `extras/amp/AGENTS.md`, `extras/codex/AGENTS.md`, and `extras/claude/CLAUDE.md`.
- Treat `extras/amp/AGENTS.md` as the source document for manual publication to Amp's **Personal Settings → Advanced → Global AGENTS.md**. Do not add an Amp extras target or write it to `~/.config/amp`; after an authorized update, verify the saved cloud setting instead of a local file.
- Do not use Skillshare `agents_source` for `AGENTS.md` / `CLAUDE.md`; Skillshare agents are single-file sub-agent definitions, while these files are always-loaded harness instructions.
- Keep global harness prompt files as complete, directly editable documents. Avoid shared-template generators unless the user explicitly asks for a generated model again.
- When adding a new extra or target, update the active Skillshare config (`extras_source` and `extras:` entries) in the environment that syncs it. If another repository owns that config, change it there.
- Use `mode: copy` for extras whose target is a tool root containing unrelated files, such as `~/.codex` or `~/.claude`. Use `merge` only for dedicated target directories where pruning Skillshare-managed symlinks is safe.
- Inspect extras with `skillshare extras list --json` and preview configuration changes with `skillshare sync extras --dry-run --force --json`. After an authorized real sync, verify copy-mode prompt files with `cmp`.

## Code Style

Use 4-space indentation by default and 2-space indentation in Markdown files. Use LF line endings and final newlines. Follow the formatter/config for file-type exceptions.

- **Python** — Ruff follows `pyproject.toml` (line-length 120, target py314). Format: `uv run ruff format --check .`. Lint: `uv run ruff check .`. Type-check: `uv run ty check .`.
- **JS / JSON / JSONC** — Biome-managed files use double quotes and 4-space indent. Generated or excluded files such as `.metadata.json` may differ; do not reformat them unless the owning tool expects it. Lint: `biome ci .`.
- **TOML** — `uvx tombi lint .`; format config uses 4-space indent.
- **Markdown** — `markdownlint-cli2`.
- **Spelling** — `typos`.
- **Repository checks** — use the explicit `mise run lint` task; `prek.toml` also lists the supported checks.

## Excluding external skills from linting

Some external skills are checked into this repo under non-`_` paths and are tracked in `.metadata.json`. Treat those paths as vendored content: do not lint or reformat them. Every non-`_` `.metadata.json` entry must be excluded in six config files (eight places total — `pyproject.toml` has three sections):

- `.typos.toml` — `[files].extend-exclude`, `"dir/"`
- `.markdownlint-cli2.yaml` — `ignores`, `"dir/"`
- `biome.jsonc` — `files.includes`, `"!!dir"` (no trailing `/`)
- `pyproject.toml` — `[tool.ruff].exclude` and `[tool.ty.src].exclude` use `"dir/"`; `[tool.tombi.files].exclude` uses `"dir/**"`
- `prek.toml` — top-level `exclude` regex, `^dir/`
- `.autocorrectignore` — `dir/`

`mise run check-lint-excludes` verifies both directions — metadata entries missing from a config, and stale excludes whose entry is gone — and reports the exact literal to add or remove. Run it after `skillshare install`, `uninstall`, or `update`, since updates can rename directories. Keep unrelated tool-specific excludes unchanged; `_`-prefixed directories are gitignored and need no excludes.

When deleting a checked-in external skill, use `skillshare uninstall` when possible; if you `rm -rf` manually, remove the directory's entries from all six config files — the checker lists the leftovers.

## Running skillshare

Use supported non-interactive flags such as `--force`, `--yes`, `--no-tui`, explicit selectors, and `--json`; do not start prompt-only workflows. Use `--json` when parsing output. Changes under paths listed in `.skillignore` are not exposed to targets unless the ignore or target configuration changes; inspect the file instead of assuming a collection is ignored.

The complete real-sync entry point is `skillshare sync --all --global`; run it only when publication is authorized and the intended content is present in `source.path`. Keep real sync on the normal non-JSON path so skills, native agents, and extras complete together. When a vendor CLI embeds its own skills, prefer a thin first-party router skill that reads them at runtime over installing copies into this source.
