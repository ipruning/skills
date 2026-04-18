---
name: shelley-backup
description: >-
  Backup Shelley chat history from exe.dev VMs.
  Triggers: backup shelley, save shelley, 备份 shelley.
---

# shelley-backup

## Prerequisites

```bash
command -v ssh && command -v rsync && command -v jq
```

Each exe.dev VM keeps Shelley chat history in a SQLite database. This skill copies them all to `~/Backups/shelley/`, one dated folder per run, with a `latest` symlink pointing to the most recent.

## Instructions

### Step 1: List VMs

```bash
ssh exe.dev ls --json 2>&1 | jq -r '.vms[].ssh_dest'
```

### Step 2: Backup

The script flushes each database's write-ahead log so the file is self-contained, then copies all VMs in parallel:

```bash
BACKUP_ROOT=~/Backups/shelley
TS=$(date +%Y-%m-%d)
DEST="$BACKUP_ROOT/$TS"
mkdir -p "$DEST"

ssh exe.dev ls --json 2>&1 | jq -r '.vms[].ssh_dest' | while read host; do
  vm="${host%%.*}"
  (
    has_db=$(ssh -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new "$host" \
      'test -f ~/.config/shelley/shelley.db && sqlite3 ~/.config/shelley/shelley.db "PRAGMA wal_checkpoint(TRUNCATE);" >/dev/null 2>&1 && echo OK || echo NO' 2>/dev/null)
    if [ "$has_db" = "OK" ]; then
      rsync -az -e "ssh -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new" \
        "${host}:/home/exedev/.config/shelley/shelley.db" \
        "${DEST}/${vm}.shelley.db" && \
      echo "✅ $vm" || echo "❌ $vm"
    else
      echo "⬜ $vm (no db)"
    fi
  ) &
done
wait

ln -sfn "$TS" "$BACKUP_ROOT/latest"
ls -lhS "$DEST/"
```

### Step 3: Validate

```bash
ls -lhS ~/Backups/shelley/latest/
# Each .shelley.db should be a valid SQLite file
for f in ~/Backups/shelley/latest/*.shelley.db; do
  vm=$(basename "$f" .shelley.db)
  msgs=$(sqlite3 "$f" "SELECT COUNT(*) FROM messages;" 2>/dev/null)
  echo "$vm: $msgs messages"
done
```

## Output Structure

```
~/Backups/shelley/
├── 2026-04-03/
│   ├── retouch.shelley.db
│   ├── ipruning-lab.shelley.db
│   └── ...
├── 2026-04-04/
│   └── ...
└── latest -> 2026-04-04/
```

## Notes

- Repeat runs are fast — rsync only transfers changed blocks.
- VMs without Shelley are skipped (marked `⬜`).
- SSH accepts new host keys automatically so the script runs without prompts.
