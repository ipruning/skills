<!-- markdownlint-disable MD013 -->

# Tailscale v1.102.2 DNS-01 传播竞态恢复

这是一次历史事故的应急恢复路径，不是日常签发方式。它会临时停止 stock `tailscaled`、运行一份与设备精确版本匹配的自编译 daemon，获取证书后立即恢复 stock daemon。不要把 fork 写进 init，也不要长期运行。

## 六个硬门槛

只有以下条件全部有现场证据时才继续：

1. 设备精确运行 Tailscale v1.102.2，CLI 与 daemon 版本一致。
2. 系统时间、CA trust store 和到 Tailscale control plane 的网络均正常。
3. 日志显示 `SetDNS` 成功，随后 ACME authorization／order 很快变为 `invalid`，没有其他明确根因。
4. Let’s Encrypt 返回的 `Retry-After` 或 rate-limit 窗口已经结束。
5. 当前 stable 版本和对应源码尚未修复该路径；若可安全升级到已修复版本，优先升级。
6. 用户明确允许维护窗口内短暂停止 Tailscale；全程可通过 LAN SSH 恢复。

任一项为 Unknown 就停止。不要用「HTTPS Certificates 已打开」代替 CA、网络或 DNS 传播证据。

先保留最小证据，不复制私钥或完整 tailnet 状态。节点 JSON 在操作机侧裁剪；日志只筛选 ACME 和证书相关行，原始日志留在设备：

```sh
ssh "root@$JETKVM_LAN_IP" 'tailscale version --daemon --json' |
  jq '{short, long, daemonLong}'
ssh "root@$JETKVM_LAN_IP" 'date -u'
ssh "root@$JETKVM_LAN_IP" 'tailscale status --json' |
  jq '{Version, BackendState, Online: .Self.Online, Health, CertDomains}'
ssh "root@$JETKVM_LAN_IP" '
  tail -n 250 /userdata/tailscale/var/tailscaled.log*.txt 2>/dev/null |
    grep -Ei "acme|certificate|SetDNS|authorization|order|Retry-After|x509" || true
'
```

## 构建精确版本的临时 daemon

构建机需要 Git、Go、Python 3 和 Tailscale 构建依赖。使用临时 checkout，并锁定设备对应 tag：

```sh
for cmd in git go gofmt python3 sha256sum; do
  command -v "$cmd" || exit 1
done

RECOVERY_SRC="$(mktemp -d)"
trap 'rm -rf "$RECOVERY_SRC"' EXIT
git clone --branch v1.102.2 --depth 1 \
  https://github.com/tailscale/tailscale.git "$RECOVERY_SRC"
cd "$RECOVERY_SRC"
test "$(git describe --tags --exact-match)" = 'v1.102.2'
```

以下补丁只接受 v1.102.2 的精确源码片段。匹配数量不是 1 时停止，不要猜新版本的插入位置：

```sh
python3 <<'PY'
from pathlib import Path

path = Path("feature/acme/cert.go")
before = '''\t\t\tlogf("did SetDNS for %s", key)
\t\t}

\t\tchal, err := ac.Accept(ctx, ch)
'''
after = '''\t\t\tlogf("did SetDNS for %s", key)
\t\t\tlogf("waiting 330 seconds for DNS propagation for %s", key)
\t\t\tselect {
\t\t\tcase <-ctx.Done():
\t\t\t\treturn ctx.Err()
\t\t\tcase <-time.After(330 * time.Second):
\t\t\t}
\t\t}

\t\tchal, err := ac.Accept(ctx, ch)
'''
source = path.read_text()
if source.count(before) != 1:
    raise SystemExit("unexpected ACME source; stop and inspect this Tailscale version")
path.write_text(source.replace(before, after))
PY

gofmt -w feature/acme/cert.go
git diff --check
git diff -- feature/acme/cert.go
```

该版本文件已导入 `time`。构建独立 ARMv7 daemon，不覆盖任何 stock 文件：

```sh
CGO_ENABLED=0 GOOS=linux GOARCH=arm GOARM=7 \
  ./build_dist.sh \
  -o tailscaled-cert-recovery-armv7 \
  ./cmd/tailscaled

file tailscaled-cert-recovery-armv7
sha256sum tailscaled-cert-recovery-armv7
```

## 经 LAN SSH 传输

写入独立名称并原子落位：

```sh
ssh "root@$JETKVM_LAN_IP" '
  set -eu
  cat > /userdata/tailscale/tailscaled-cert-recovery.new
  chmod 0755 /userdata/tailscale/tailscaled-cert-recovery.new
  mv /userdata/tailscale/tailscaled-cert-recovery.new \
    /userdata/tailscale/tailscaled-cert-recovery
' < tailscaled-cert-recovery-armv7
```

不要覆盖 `/userdata/tailscale/tailscaled`。记录 LAN 恢复命令；若远端恢复脚本意外中断且 daemon 未自动回来，从 LAN SSH 执行：

```sh
ssh "root@$JETKVM_LAN_IP" '
  /userdata/init.d/S21persistent-data start 2>/dev/null || true
  /userdata/init.d/S22tailscale start
'
```

## 单次签发窗口

脚本通过 trap 尝试恢复 stock daemon。它只把证书和私钥写到 `/tmp`，签发完成后删除；daemon 自己的持久证书缓存仍在 `/userdata/tailscale/var/certs`。

```sh
ssh -tt "root@$JETKVM_LAN_IP" "JETKVM_FQDN='$JETKVM_FQDN' ash -s" <<'EOF'
set -eu

RECOVERY=/userdata/tailscale/tailscaled-cert-recovery
STOCK_INIT=/userdata/init.d/S22tailscale
RECOVERY_LOG=/tmp/tailscaled-cert-recovery.log
OUT_CERT=/tmp/tailscale-cert-recovery.crt
OUT_KEY=/tmp/tailscale-cert-recovery.key
RECOVERY_PID=
STOCK_STOPPED=false

test -x "$RECOVERY"
test -n "$JETKVM_FQDN"
pidof tailscaled >/dev/null

restore_stock() {
  trap - EXIT HUP INT TERM
  set +e
  if [ -n "$RECOVERY_PID" ]; then
    kill "$RECOVERY_PID" 2>/dev/null
    wait "$RECOVERY_PID" 2>/dev/null
  fi
  rm -f "$OUT_CERT" "$OUT_KEY"
  if [ "$STOCK_STOPPED" = true ]; then
    "$STOCK_INIT" start
  fi
}
trap restore_stock EXIT
trap 'exit 1' HUP INT TERM

STOCK_STOPPED=true
"$STOCK_INIT" stop
sleep 2

if [ -f /userdata/tailscale/cacert.pem ]; then
  export SSL_CERT_FILE=/userdata/tailscale/cacert.pem
fi
"$RECOVERY" >"$RECOVERY_LOG" 2>&1 &
RECOVERY_PID=$!

i=0
until STATUS_JSON="$(tailscale status --json 2>/dev/null)" &&
  printf '%s\n' "$STATUS_JSON" | grep -q '"BackendState": "Running"' &&
  printf '%s\n' "$STATUS_JSON" | grep -q '"Online": true' &&
  printf '%s\n' "$STATUS_JSON" | grep -Fq "\"$JETKVM_FQDN\""; do
  i=$((i + 1))
  if [ "$i" -ge 30 ] || ! kill -0 "$RECOVERY_PID" 2>/dev/null; then
    echo "recovery daemon did not reach Running; inspect $RECOVERY_LOG through LAN SSH" >&2
    exit 1
  fi
  sleep 1
done

tailscale cert \
  --min-validity=720h \
  --cert-file="$OUT_CERT" \
  --key-file="$OUT_KEY" \
  "$JETKVM_FQDN"
EOF
```

330 秒等待期间不要中止或重复启动另一个签发请求。若 SSH 断开，先走 LAN 恢复命令，再判断结果；不要假定 trap 已执行。

## 证明 stock daemon 已恢复

```sh
ssh "root@$JETKVM_LAN_IP" 'pidof tailscaled'
ssh "root@$JETKVM_LAN_IP" 'tailscale status --json' |
  jq -e '
    .BackendState == "Running" and
    .Self.Online == true and
    ((.Health // []) | length == 0)
  '
ssh "root@$JETKVM_LAN_IP" 'tailscale version --daemon --json' |
  jq -e '.long == .daemonLong'
ssh "root@$JETKVM_LAN_IP" 'tailscale serve status'

curl --noproxy '*' -fsS -o /dev/null -w 'HTTP %{http_code}\n' \
  "https://$JETKVM_FQDN/"

openssl s_client \
  -connect "$JETKVM_FQDN:443" \
  -servername "$JETKVM_FQDN" </dev/null 2>/dev/null |
  openssl x509 -noout -dates -fingerprint -sha256
```

## 清理临时 fork

只有 stock daemon、Serve 和线上证书全部通过后，删除本流程明确创建的临时文件：

```sh
ssh "root@$JETKVM_LAN_IP" '
  rm -f /userdata/tailscale/tailscaled-cert-recovery
  rm -f /tmp/tailscaled-cert-recovery.log
'
```

本地 source checkout 由前面的 shell trap 清理。不要删除 stock `tailscaled`、`tailscaled.state` 或 `var/certs`。

## 证据锚点

- [Tailscale v1.102.2 `feature/acme/cert.go`](https://github.com/tailscale/tailscale/blob/v1.102.2/feature/acme/cert.go)
- [Tailscale HTTPS Certificates](https://tailscale.com/docs/how-to/set-up-https-certificates)
