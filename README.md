# Skills

Coding agent skills mono-repo, managed by [skillshare](https://github.com/runkids/skillshare). Write once, sync everywhere.

## Why This Workflow

- **Write once, sync to all coding agents** — One `skillshare sync` distributes skills to Amp, Codex, Claude Code, Cursor, etc. via symlinks.
- **Three-layer stacking** — Personal + org + community skills coexist in one repo. External repos are auto-gitignored with `_` prefix.
- **One command on a new machine** — `skillshare init --remote <repo>` pulls everything down.
- **Security audit on install** — Auto-scans for dangerous patterns. CRITICAL findings block installation.

## Setup (macOS)

```bash
# Install skillshare
brew install skillshare # or: mise use -g github:runkids/skillshare@latest

# Init with your repo
skillshare init \
  --source ~/.config/skillshare/skills \
  --remote https://github.com/<you>/skills \
  --all-targets --mode merge --subdir . --no-skill

# Install shared skills
skillshare install https://github.com/<org>/skills --track

# Sync to all coding agents
skillshare sync
```

> Drop `--no-skill` and `--all-targets` to get the interactive TUI instead.

## Setup (Linux / Cloud VM)

```bash
curl -fsSL https://raw.githubusercontent.com/runkids/skillshare/main/install.sh | sh

skillshare init \
  --source ~/.config/skillshare/skills \
  --remote https://github.com/<you>/skills \
  --targets codex --mode merge --subdir . --no-skill

skillshare install https://github.com/<org>/skills --track
skillshare sync
```

## Daily Use

```bash
skillshare sync                             # After writing/editing a skill
skillshare push                             # Push to Git (machine A)
skillshare pull && skillshare sync          # Pull on machine B
skillshare update --all && skillshare sync  # Update external skills
```

## Gotchas

1. **`sync` is manual** — Run it after every `install` / `uninstall` / `update`.
2. **Don't `rm -rf` skills** — Use `skillshare uninstall`. It trashes (7-day retention), recoverable via `trash restore`.
3. **Don't edit `_`-prefixed dirs** — Managed by skillshare, gitignored, overwritten on `update`.
4. **HIGH audit ≠ blocked** — Only CRITICAL blocks. HIGH is a warning. `--force` to override.
5. **Use `merge` mode** — `replace` wipes the target dir. `merge` symlinks alongside your local skills.
6. **`skillshare doctor`** — First thing to run when skills aren't showing up.
