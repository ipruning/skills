# Go SDK Snapshot Examples

```go
import (
    "github.com/tigrisdata/storage-go/storage"
)

client, _ := storage.New(ctx)

// Create snapshot-enabled bucket
client.CreateSnapshotBucket(ctx, "my-bucket")

// Take named snapshot
version, _ := client.CreateBucketSnapshot(ctx, "my-bucket")

// Read object at snapshot version
obj, _ := client.GetObjectAtVersion(ctx, "my-bucket", "config.json", version)

// List snapshots
snapshots, _ := client.ListBucketSnapshots(ctx, "my-bucket")
```
