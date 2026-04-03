# Snapshot Restore Workflows (TypeScript)

## Restore from a Named Snapshot

### Step 1: List Snapshots and Find the Right One

```typescript
import { listBucketSnapshots } from "@tigrisdata/storage";

const result = await listBucketSnapshots("my-bucket");
console.log(result.data);
// [
//   { name: "before-deploy-v2.3", version: "1751631910169675092", creationDate: 2026-03-17T14:00:00Z },
//   { name: "daily-2026-03-16",   version: "1751545510169675092", creationDate: 2026-03-16T02:00:00Z },
//   { name: "before-migration",   version: "1751459110169675092", creationDate: 2026-03-15T02:00:00Z },
// ]
```

### Step 2: Find the Snapshot by Name

```typescript
const snapshots = result.data ?? [];
const target = snapshots.find((s) => s.name === "before-deploy-v2.3");
if (!target) throw new Error("Snapshot not found");

const snapshotVersion = target.version;
console.log(`Restoring from snapshot: ${target.name} (${target.version})`);
```

### Step 3: Restore a Single File

```typescript
import { get, put } from "@tigrisdata/storage";

const old = await get("config.json", "string", { snapshotVersion });

if (old.error) {
  console.log("File did not exist at this snapshot");
} else {
  await put("config.json", old.data, { contentType: "application/json" });
  console.log("File restored from snapshot");
}
```

### Step 4: Restore the Entire Bucket

```typescript
import { list, get, put } from "@tigrisdata/storage";

async function restoreFromSnapshot(bucketName: string, snapshotVersion: string) {
  const allFiles = [];
  let page = await list({ snapshotVersion, limit: 100, config: { bucket: bucketName } });
  allFiles.push(...(page.data?.items ?? []));

  while (page.data?.hasMore) {
    page = await list({
      snapshotVersion,
      limit: 100,
      paginationToken: page.data.paginationToken,
      config: { bucket: bucketName },
    });
    allFiles.push(...(page.data?.items ?? []));
  }

  console.log(`Restoring ${allFiles.length} files from snapshot ${snapshotVersion}...`);

  for (const file of allFiles) {
    const old = await get(file.path, "file", {
      snapshotVersion,
      config: { bucket: bucketName },
    });
    if (!old.error) {
      await put(file.path, old.data, {
        contentType: file.contentType,
        config: { bucket: bucketName },
      });
    }
  }

  console.log("Restore complete");
}

// Usage
const snapshots = await listBucketSnapshots("my-bucket");
const target = snapshots.data?.find((s) => s.name === "before-deploy-v2.3");
await restoreFromSnapshot("my-bucket", target!.version);
```

---

## Restore a Specific Prefix

Restore just a subdirectory (e.g., only `uploads/`) instead of the entire bucket:

```typescript
async function restorePrefixFromSnapshot(
  bucketName: string,
  prefix: string,
  snapshotVersion: string,
) {
  const allFiles = [];
  let page = await list({ prefix, snapshotVersion, limit: 100, config: { bucket: bucketName } });
  allFiles.push(...(page.data?.items ?? []));

  while (page.data?.hasMore) {
    page = await list({
      prefix,
      snapshotVersion,
      limit: 100,
      paginationToken: page.data.paginationToken,
      config: { bucket: bucketName },
    });
    allFiles.push(...(page.data?.items ?? []));
  }

  for (const file of allFiles) {
    const old = await get(file.path, "file", {
      snapshotVersion,
      config: { bucket: bucketName },
    });
    if (!old.error) {
      await put(file.path, old.data, {
        contentType: file.contentType,
        config: { bucket: bucketName },
      });
    }
  }

  console.log(`Restored ${allFiles.length} files under ${prefix}`);
}

// Restore just the uploads directory
const target = snapshots.data?.find((s) => s.name === "before-migration");
await restorePrefixFromSnapshot("my-bucket", "uploads/", target!.version);
```

---

## Recover Without an Explicit Snapshot (Using Timestamps)

Even if you never took a named snapshot, every change is tracked. Use any timestamp:

```typescript
// Convert a date to a snapshot version (nanoseconds since Unix epoch)
const targetDate = new Date("2026-03-17T14:00:00Z");
const snapshotVersion = String(targetDate.getTime() * 1_000_000);

// Now use this version exactly like a named snapshot version
const old = await get("config.json", "string", { snapshotVersion });
```

This works because snapshot versions are nanosecond timestamps. Named snapshots just record a specific timestamp for convenience.

---

## Recover a Changed File (Undo an Overwrite)

```typescript
import { get, put, listBucketSnapshots } from "@tigrisdata/storage";

// Find the snapshot taken before the bad change
const snapshots = await listBucketSnapshots("my-bucket");
const target = snapshots.data?.find((s) => s.name === "before-deploy-v2.3");

// Read what the file looked like at that snapshot
const old = await get("data/users.json", "string", {
  snapshotVersion: target!.version,
});

if (!old.error) {
  await put("data/users.json", old.data, { contentType: "application/json" });
  console.log("Reverted to previous version");
}
```

---

## Compare Current vs Snapshot

```typescript
import { get, listBucketSnapshots } from "@tigrisdata/storage";

const snapshots = await listBucketSnapshots("my-bucket");
const target = snapshots.data?.find((s) => s.name === "before-deploy-v2.3");

// Current version
const current = await get("config.json", "string");

// Version at snapshot
const atSnapshot = await get("config.json", "string", {
  snapshotVersion: target!.version,
});

if (current.data !== atSnapshot.data) {
  console.log("File has changed since snapshot");
  // Diff, log, or restore as needed
}
```
