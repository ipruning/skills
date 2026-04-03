---
name: exe-backup
description: >-
  Backup Shelley chat history from all exe.dev VMs. Use when the user asks to
  "backup shelley", "backup exe VMs", "save chat history from exe.dev",
  "备份 shelley", or wants to preserve AI conversation data from exe.dev servers.
---

# exe-backup

Backup Shelley SQLite databases from all exe.dev VMs to local `~/Databases/backup/shelley/<date>/` with a `latest` symlink.

## Instructions

### Step 1: List VMs

```bash
ssh exe.dev ls --json 2>&1 | jq -r '.vms[].ssh_dest'
```

### Step 2: Backup

Run this script — it checkpoints WAL, rsyncs in parallel, and updates the `latest` symlink:

```bash
BACKUP_ROOT=~/Databases/backup/shelley
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
ls -lhS ~/Databases/backup/shelley/latest/
# Each .shelley.db should be a valid SQLite file
for f in ~/Databases/backup/shelley/latest/*.shelley.db; do
  vm=$(basename "$f" .shelley.db)
  msgs=$(sqlite3 "$f" "SELECT COUNT(*) FROM messages;" 2>/dev/null)
  echo "$vm: $msgs messages"
done
```

## Output Structure

```
~/Databases/backup/shelley/
├── 2026-04-03/
│   ├── retouch.shelley.db
│   ├── ipruning-lab.shelley.db
│   └── ...
├── 2026-04-04/
│   └── ...
└── latest -> 2026-04-04/
```

## Notes

- `rsync -az` enables incremental + compression — repeat runs only transfer changed blocks.
- `PRAGMA wal_checkpoint(TRUNCATE)` flushes WAL before copy for data integrity.
- VMs without Shelley installed are skipped with `⬜`.
- All SSH connections use `StrictHostKeyChecking=accept-new` to avoid interactive prompts.
