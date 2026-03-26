# Guidelines for AI Agents

## Synced Skills Ignore Rules

Any skill directory containing a `.skillshare-meta.json` file is externally synced and MUST be excluded from all linting/CI config files to prevent CI failures.

Config files that must list synced dirs:

- `.autocorrectignore`
- `.markdownlint-cli2.yaml` (ignores list)
- `.typos.toml` (extend-exclude)
- `biome.jsonc` (files.includes negation with `!!`)
- `prek.toml` (exclude regex)
- `pyproject.toml` (`[tool.ruff].exclude` and `[tool.ty.src].exclude`)

When a new skill is synced via skillshare, add it to ALL of the above files.

To find all synced skill directories that need explicit excludes, run:

```sh
fd -H -t f '.skillshare-meta.json' -x dirname {} | sed 's|^\./||' | sort -u
```
