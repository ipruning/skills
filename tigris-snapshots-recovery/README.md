# tigris-snapshots-recovery

Point-in-time recovery for Tigris object storage. Recover deleted or changed files from any timestamp.

## What It Covers

- **Snapshot-enabled buckets** — must be enabled at creation (cannot add later), migration path for existing buckets
- **Automatic change tracking** — every put/delete is preserved, no explicit snapshot needed
- **Recover deleted files** — read any file at any past timestamp and restore it
- **Revert overwrites** — undo unwanted changes to files
- **Bulk restore** — restore entire prefixes or full buckets to a point in time
- **Named snapshots** — optional bookmarks for easy reference before deploys/migrations
- **Multi-language** — TypeScript SDK, Go SDK, Python (tigris-boto3-ext)

## Installation

**Claude Code:**

```bash
cp -r skills/tigris-snapshots-recovery ~/.claude/skills/
```

**claude.ai:**

Add `skills/tigris-snapshots-recovery` to project knowledge or paste `SKILL.md` contents into the conversation.

## Usage

This skill activates when you mention:

- "Recover deleted file", "point-in-time recovery"
- "Restore from snapshot", "undo delete"
- "File was deleted", "revert to previous version"
- "Enable snapshots", "snapshot bucket"

## Example Prompts

```text
A file was accidentally deleted from my Tigris bucket, how do I recover it?
```

```text
Set up a new bucket with snapshots enabled for point-in-time recovery
```

```text
Restore all files in the uploads/ prefix to how they were yesterday
```

## License

MIT
