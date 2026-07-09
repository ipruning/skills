# Swap

Swap commands inspect and resize swap on small VPS hosts.

## Read State

```bash
free -h
swapon --show --bytes || true
grep -n '^[^#].*[[:space:]]swap[[:space:]]' /etc/fstab || true
ls -lh /swap /swapfile 2>/dev/null || true
df -h /
```

Preserve the existing swap path when resizing (`/swap`, `/swapfile`, or provider-created path). Create a second active swap file only when the user explicitly wants multiple swap devices.

## Choose Size

For small proxy/VPS nodes:

- 1 GiB RAM: use 2 GiB swap when `/` has at least 4 GiB free after allocation; use 4 GiB only when fleet convention or prior OOM evidence calls for it and `/` has at least 8 GiB free after allocation.
- 2 GiB RAM: use 2 GiB swap when no fleet convention exists; use 4 GiB only when prior OOM evidence exists and `/` has at least 8 GiB free after allocation.
- Match the user's fleet convention when the user asks for consistency.
- Do not oversize swap on tiny disks or write-heavy workloads without checking disk space.

Swap prevents abrupt OOM kills; it is not a performance substitute for RAM.

## Resize Existing Swap File

Only resize when there is enough free disk and current memory pressure allows `swapoff`. Do not back up the swap file's contents: after `swapoff` they are dead pages, the copy can fill a small root disk, and the rollback path is simply recreating the file. What must survive is the `/etc/fstab` line.

Persistent impact: recreates the swap file at the existing path and keeps existing `/etc/fstab` behavior when the path is already listed there.

```bash
df -h /
free -h
swapon --show
```

Set variables before resizing:

```bash
SWAP_PATH=<SWAP_PATH>
SIZE_MIB=<SIZE_GIB_TIMES_1024>
grep -q "^[^#].*[[:space:]]${SWAP_PATH}[[:space:]]" /etc/fstab
swapoff "$SWAP_PATH"
if ! fallocate -l "${SIZE_MIB}M" "$SWAP_PATH" 2>/dev/null; then
  dd if=/dev/zero of="$SWAP_PATH" bs=1M count="$SIZE_MIB" status=none
fi
chmod 600 "$SWAP_PATH"
mkswap -f "$SWAP_PATH"
swapon "$SWAP_PATH"
swapon --show --bytes
free -h
grep -n '^[^#].*[[:space:]]swap[[:space:]]' /etc/fstab
```

If the swap path is not listed in `/etc/fstab`, add it in a separate step:

Persistent impact: appends a swap mount entry to `/etc/fstab`; the swap file will be activated on future boots until the entry is removed.

```bash
printf '%s none swap sw 0 0\n' "$SWAP_PATH" >>/etc/fstab
findmnt --verify --tab-file /etc/fstab
```

If `swapoff` fails because memory is tight, stop and reassess rather than forcing the change.
