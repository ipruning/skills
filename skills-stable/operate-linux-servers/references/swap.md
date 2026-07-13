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
if ! awk -v swap_path="$SWAP_PATH" '$1 !~ /^#/ && $1 == swap_path && $3 == "swap" { found=1 } END { exit !found }' /etc/fstab; then
  echo "swap path is not declared in /etc/fstab: $SWAP_PATH" >&2
  exit 1
fi
if ! swapoff "$SWAP_PATH"; then
  echo "swapoff failed; no file changes were made" >&2
  exit 1
fi
rollback_path="${SWAP_PATH}.linux-server-rollback"
test ! -e "$rollback_path" || { echo "rollback path already exists: $rollback_path" >&2; swapon "$SWAP_PATH"; exit 1; }
if ! mv "$SWAP_PATH" "$rollback_path"; then
  swapon "$SWAP_PATH" || echo "CRITICAL: original swap could not be reactivated" >&2
  exit 1
fi
restore_swap() {
  swap_restore_failed=0
  rm -f "$SWAP_PATH" || swap_restore_failed=1
  mv "$rollback_path" "$SWAP_PATH" || swap_restore_failed=1
  chmod 600 "$SWAP_PATH" || swap_restore_failed=1
  swapon "$SWAP_PATH" || swap_restore_failed=1
  test "$swap_restore_failed" -eq 0
}
if ! fallocate -l "${SIZE_MIB}M" "$SWAP_PATH" 2>/dev/null; then
  if ! dd if=/dev/zero of="$SWAP_PATH" bs=1M count="$SIZE_MIB" status=none; then
    restore_swap || echo "CRITICAL: swap allocation failed and rollback was incomplete" >&2
    exit 1
  fi
fi
if ! chmod 600 "$SWAP_PATH" || ! mkswap -f "$SWAP_PATH" || ! swapon "$SWAP_PATH"; then
  restore_swap || echo "CRITICAL: new swap activation failed and rollback was incomplete" >&2
  exit 1
fi
rm -f "$rollback_path" || { echo "new swap is active but rollback file could not be removed" >&2; exit 1; }
swapon --show --bytes
free -h
grep -n '^[^#].*[[:space:]]swap[[:space:]]' /etc/fstab
```

If the swap path is not listed in `/etc/fstab`, add it in a separate step:

Persistent impact: appends a swap mount entry to `/etc/fstab`; the swap file will be activated on future boots until the entry is removed.

```bash
fstab_candidate=$(mktemp)
trap 'rm -f "$fstab_candidate"' EXIT
fstab_backup=$(mktemp /run/fstab-original.XXXXXX)
chmod 600 "$fstab_backup" || exit 1
cp -a /etc/fstab "$fstab_candidate" || exit 1
cp -a /etc/fstab "$fstab_backup" || exit 1
printf '%s none swap sw 0 0\n' "$SWAP_PATH" >>"$fstab_candidate" || exit 1
findmnt --verify --tab-file "$fstab_candidate" || exit 1
restore_fstab() {
  cp -a "$fstab_backup" /etc/fstab \
    && findmnt --verify --tab-file /etc/fstab
}
if ! install -o root -g root -m 0644 "$fstab_candidate" /etc/fstab; then
  restore_fstab || echo "CRITICAL: fstab install failed and rollback was incomplete" >&2
  exit 1
fi
if ! findmnt --verify --tab-file /etc/fstab; then
  if ! restore_fstab; then
    echo "CRITICAL: fstab validation failed and rollback was incomplete" >&2
  fi
  exit 1
fi
printf 'fstab_backup=%s\n' "$fstab_backup"
```

If `swapoff` fails because memory is tight, stop and reassess rather than forcing the change.
