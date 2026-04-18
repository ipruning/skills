---
name: prek
description: "Optimize prek (pre-commit) hook configuration: priority-based parallelism, pass_filenames tuning, startup overhead reduction, and benchmarking. Triggers: prek, pre-commit optimization, hook performance, priority tuning."
metadata:
  version: "1"
---

# Optimizing prek Hooks

## Prerequisites

```bash
command -v prek
```

prek is a pre-commit hook runner. It runs hooks in parallel when they share the same priority, and sequentially across different priorities. Most speed gains come from keeping independent hooks at the same priority and removing unnecessary wrapper overhead.

## Core Concepts

### How priorities work

Hooks with the same priority run concurrently. Different priorities run sequentially, lowest first.

```toml
# These two run at the same time
{ id = "ruff-check", priority = 20 }
{ id = "typos", priority = 20 }
# This waits for both to finish
{ id = "integration-test", priority = 30 }
```

Splitting a parallel group into sequential phases is never faster — the total wall time can only stay the same or increase. Keep all independent checks at the same priority unless correctness requires otherwise.

### Three Hook Categories

| Category | Behavior | Priority Strategy |
|---|---|---|
| Gate checks | Fast, fail-fast guards (branch protection, email check) | Lowest priority (e.g., 0), concurrent |
| Fixers | Modify files in place (trailing-whitespace, end-of-file-fixer) | Each gets a **unique** priority (e.g., 10, 11, 12) to avoid write conflicts |
| Read-only checks | Lint, type-check, scan | All share the **same** priority (e.g., 20), fully concurrent |

Fixers **must** run before checks so that checks validate the fixed state.

## Configuration Patterns

### Prefer official repo hooks

Official pre-commit repo hooks bundle their own toolchain and start faster than local system hooks.

```toml
# ✅ Official repo — manages its own ruff binary
[[repos]]
repo = "https://github.com/astral-sh/ruff-pre-commit"
rev = "v0.15.4"
hooks = [{ id = "ruff-check" }]

# ❌ Local system hook — slower due to mise/uv startup overhead
[[repos]]
repo = "local"
hooks = [{ id = "ruff", entry = "mise exec -- uv run ruff check .", language = "system" }]
```

### Keep format hooks check-only

Format hooks in official repos modify files by default. Add `--check` so they only report problems:

```toml
# ruff-format default: formats in place
# Add --check for pre-commit: only report, don't modify
{ id = "ruff-format", args = ["--check"] }
```

Verify with: commit a badly formatted file, run the hook, then check `git status` and file hash — no changes should appear.

### When to disable pass_filenames

By default prek passes changed file paths to each hook. Disable this (`pass_filenames = false`) when:

- The tool needs full-project context (type checkers like ty, mypy).
- The tool has high startup cost (Node.js tools like markdownlint, eslint) — prek splits long file lists into batches, and each batch spawns a new process. Twelve batches at ~1s startup each means 12s instead of 1.2s.

Keep it enabled for fast, low-startup tools (ruff, typos, shellcheck) so they only check changed files.

### Skip hooks with types

Use `types` so a hook only runs when relevant files changed:

```toml
# Only triggers when Python files are in the changeset
{ id = "ty", types = ["python"], pass_filenames = false }
# Only triggers when shell scripts are in the changeset
{ id = "shellcheck", types = ["shell"] }
```

Don't combine `always_run = true` with `types` — they contradict each other.

### Remove wrapper overhead

Each wrapper layer adds startup latency:

```
mise exec -- uv run ty check .    # ~4.2s (mise + uv overhead)
uv run ty check .                 # ~2.5s (uv overhead only)
.venv/bin/ty check .              # ~1.7s (direct, fastest)
ty check .                        # ~1.7s (if on PATH)
```

Inside prek the environment is already set up, so the wrappers are unnecessary:

```toml
# ❌ Slow
entry = "mise exec -- uv run ty check ."
# ✅ Fast
entry = "uv run ty check ."
# ✅ Fastest (if tool is on PATH)
entry = "ty check ."
```

### Watch out for dotfiles

Some tools skip dotfiles by default (e.g., `autocorrect --fix .` ignores `.agents/`, `.mise/`), but prek passes dotfile paths directly. This means a hook can fail in prek yet pass when run by hand. To fix the manual/CI side, list the dotfile directories explicitly:

```bash
autocorrect --fix . .agents/ .mise/
autocorrect --lint . .agents/ .mise/
```

### What require_serial actually does

`require_serial = true` makes a hook process its file batches one at a time, but it still runs concurrently with other hooks at the same priority. If you need a hook to run alone, give it a unique priority.

## Testing Workflow

### 1. Validate Configuration

```bash
prek validate-config
prek run --all-files --dry-run    # Check ordering without executing
```

### 2. Trigger Test

Create a file that violates the hook, commit with `--no-verify`, then test:

```bash
# Create violation
cat > _test.py << 'EOF'
import os          # unused import (F401)
x = {  "a":1}     # bad formatting
EOF

# Commit without hooks
git add _test.py && git commit --no-verify -m "test"

# Record file hash
md5sum _test.py

# Run specific hooks
prek run ruff-check --all-files
prek run ruff-format --all-files

# Verify no file modification (check-only mode)
md5sum _test.py           # Must match
git status --short        # Must show no unstaged changes
git diff                  # Must be empty

# Clean up
git reset HEAD~1 --hard
```

### 3. Benchmark

```bash
# Baseline
hyperfine 'prek run --all-files'

# After changes
hyperfine 'prek run --all-files'

# Compare two configurations
hyperfine 'prek run --all-files' --warmup 1 --runs 5

# With verbose output to identify bottlenecks
time prek run --all-files --verbose
```

### 4. Analyze Parallelism

From `--verbose` output, check:

- **Wall time vs sum of durations**: high ratio = good parallelism
- **CPU usage** (`time` output): 400%+ means multi-core utilization
- **Bottleneck hook**: the slowest hook in a priority group determines that group's wall time

### 5. Per-Hook Profiling

Measure bare execution time and CPU intensity:

```bash
time <tool> <args>
```

CPU intensity = user time / wall time:

- `> 300%`: CPU-heavy (ty, ripsecrets, ast-grep)
- `50-150%`: IO-bound (typos, markdownlint, ls-lint)
- `< 50%`: lightweight (check-yaml, detect-private-key)

## Common Pitfalls

1. **Stale tool versions**: Official repo hooks pin their version via `rev`. Local system hooks use whatever is on PATH, so CI and local can drift apart.

## Recommended Priority Layout

```toml
# Priority 0:  Gate checks (instant, fail-fast)
# Priority 10: Fixer A (modifies files)
# Priority 11: Fixer B (modifies files)
# Priority 12: Fixer C (modifies files)
# Priority 20: ALL read-only checks (maximum concurrency)
```
