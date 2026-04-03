# Skills

A skill is a SKILL.md file that teaches a coding agent how to do one thing well. This repo holds all your skills and syncs them to every AI tool you use — Amp, Codex, Claude Code, Cursor, and others — with [skillshare](https://github.com/runkids/skillshare).

Each top-level directory is one skill. Directories prefixed with `_` are installed from external repos; skillshare manages them and git ignores them.

## Setup

macOS:

```bash
brew install skillshare
```

Linux:

```bash
curl -fsSL https://raw.githubusercontent.com/runkids/skillshare/main/install.sh | sh
```

Then point skillshare at this repo and sync:

```bash
skillshare init \
  --source ~/.config/skillshare/skills \
  --remote https://github.com/<you>/skills \
  --all-targets --mode merge --subdir . --no-skill

skillshare install https://github.com/<org>/skills --track
skillshare sync
```

Drop `--no-skill` and `--all-targets` for the interactive TUI.

## Daily use

```bash
skillshare sync                             # after writing or editing a skill
skillshare push                             # push to git
skillshare pull && skillshare sync          # pull on another machine
skillshare update --all && skillshare sync  # update external skills
```

## Things that will bite you

`sync` is manual. Run it after every `install`, `uninstall`, or `update`.

Remove skills with `skillshare uninstall`, not `rm -rf`. Uninstall puts them in trash with 7-day retention.

Never edit `_`-prefixed directories. They are overwritten on `update`.

`skillshare doctor` is the first thing to run when skills don't show up.
