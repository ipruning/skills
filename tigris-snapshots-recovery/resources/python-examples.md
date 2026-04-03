# Python Snapshot Examples (tigris-boto3-ext)

```python
from tigris_boto3_ext import TigrisSnapshot, create_snapshot_bucket

# Create snapshot-enabled bucket
create_snapshot_bucket(s3, "my-bucket")

# Read object at a point in time
with TigrisSnapshot(s3, "my-bucket", version="1751631910169675092") as snap:
    obj = snap.get_object(Key="config.json")
    content = obj["Body"].read()

# Take explicit snapshot
from tigris_boto3_ext import create_snapshot
version = create_snapshot(s3, "my-bucket", name="before-deploy")
```
