<!-- markdownlint-disable MD013 -->

# JetKVM + Tailscale Runbook

本 Runbook 使用官方 Tailscale control plane，并把 JetKVM Web UI 通过 Tailscale Serve 只开放给 tailnet。命令在 macOS 或 Linux 操作机执行，除非代码块明确位于远端 SSH 中。

## 操作机与现场变量

先由用户确认 LAN 地址：

```sh
export JETKVM_LAN_IP='REPLACE_WITH_LAN_IP'
```

JetKVM Web UI 必须已启用 Developer Mode，并写入操作机的 SSH 公钥。先接受或核对 LAN SSH host key，再运行安装器；不要让后续自动化替代首次身份核验。

macOS 上的官方安装器需要无前缀 `sha256sum`：

```sh
brew install coreutils
export PATH="$(brew --prefix coreutils)/libexec/gnubin:$PATH"
```

统一预检：

```sh
for cmd in curl ssh sha256sum jq openssl; do
  command -v "$cmd" || exit 1
done

ssh -o BatchMode=yes "root@$JETKVM_LAN_IP" '
  set -eu
  uname -a
  date -u
  mount | grep " on /userdata "
  test -w /userdata
  printf "LAN SSH OK\n"
'
```

Tailscale 已入网后，从节点状态发现地址和证书域名，不手写猜测：

```sh
SELF_STATUS="$(ssh "root@$JETKVM_LAN_IP" 'tailscale status --json')"

export JETKVM_TS_IP="$(
  printf '%s\n' "$SELF_STATUS" |
    jq -er '.Self.TailscaleIPs[] | select(startswith("100."))'
)"
export JETKVM_FQDN="$(
  printf '%s\n' "$SELF_STATUS" | jq -er '.CertDomains[0]'
)"

printf 'LAN=%s\nTailscale=%s\nFQDN=%s\n' \
  "$JETKVM_LAN_IP" "$JETKVM_TS_IP" "$JETKVM_FQDN"
```

`.CertDomains` 为空时不要伪造域名。按「Tailnet-only HTTPS Serve」处理 HTTPS 管理后台前置条件。

## 安装与更新

### 使用官方安装器

先完整下载安装器，再执行。这样能避免截断管道，也能在运行前检查当前内容：

```sh
INSTALLER="$(mktemp)"
trap 'rm -f "$INSTALLER"' EXIT

curl -fsSL https://jetkvm.com/install-tailscale.sh -o "$INSTALLER"
sh -n "$INSTALLER"

TARGET_VERSION="$(
  curl -fsSL 'https://pkgs.tailscale.com/stable/?mode=json&os=linux' |
    jq -er '.TarballsVersion'
)"
BEFORE_BOOT_ID="$(
  ssh "root@$JETKVM_LAN_IP" 'cat /proc/sys/kernel/random/boot_id'
)"

sh "$INSTALLER" --version "$TARGET_VERSION" "$JETKVM_LAN_IP"
```

安装器会重启 JetKVM，并要求完成 `tailscale up` 登录。执行前查看现场下载的安装器如何处理远端 SSH 错误；若安装块以 `|| true` 等方式容错退出，中间失败仍可能打印 `SUCCESS`。无论实现如何，登录完成后都要验证实际启动和版本：

```sh
AFTER_BOOT_ID="$(
  ssh "root@$JETKVM_LAN_IP" 'cat /proc/sys/kernel/random/boot_id'
)"
test "$BEFORE_BOOT_ID" != "$AFTER_BOOT_ID"

ssh "root@$JETKVM_LAN_IP" '
  set -eu
  test -x /userdata/tailscale/tailscale
  test -x /userdata/tailscale/tailscaled
  test "$(readlink /bin/tailscale)" = "/userdata/tailscale/tailscale"
  test -x /userdata/init.d/S22tailscale
  sh -n /userdata/init.d/S22tailscale
'

VERSION_STATUS="$(
  ssh "root@$JETKVM_LAN_IP" 'tailscale version --daemon --json'
)"
printf '%s\n' "$VERSION_STATUS" |
  jq -e --arg version "$TARGET_VERSION" '
    (.long | startswith($version)) and
    (.daemonLong | startswith($version)) and
    (.long == .daemonLong)
  '

ssh "root@$JETKVM_LAN_IP" 'tailscale status --json' |
  jq -e '
    .BackendState == "Running" and
    .Self.Online == true and
    ((.Health // []) | length == 0)
  '
```

### 更新策略

先检查当前 `/userdata/init.d/S22tailscale` 是否实现 `restart`，以及 updater 能否发现该脚本：

```sh
ssh "root@$JETKVM_LAN_IP" '
  sed -n "1,200p" /userdata/init.d/S22tailscale
  ls -l /etc/init.d/*tailscale 2>/dev/null || true
  tailscale update --dry-run
'
```

当前 init 没有 `restart`，且 updater 无法发现或重启它时，只开启更新检查，不自动应用：

```sh
ssh "root@$JETKVM_LAN_IP" \
  'tailscale set --update-check=true --auto-update=false'
```

以后版本若已提供可验证的 JetKVM restart 支持，以当前源码和实测为准，不延续旧结论。

### 固定版本与 clean 边界

读取 stable feed 后由操作者选择版本：

```sh
curl -fsSL 'https://pkgs.tailscale.com/stable/?mode=json&os=linux' | jq .

export TAILSCALE_VERSION='REPLACE_WITH_AVAILABLE_VERSION'
PINNED_INSTALLER="$(mktemp)"
trap 'rm -f "$PINNED_INSTALLER"' EXIT
curl -fsSL https://jetkvm.com/install-tailscale.sh -o "$PINNED_INSTALLER"
sh "$PINNED_INSTALLER" --version "$TAILSCALE_VERSION" "$JETKVM_LAN_IP"
```

`--clean` 只用于用户明确要求把设备作为全新 Tailscale 节点重新入网。它删除 `/userdata/tailscale`，不能作为修复或升级手段。执行前要确认旧节点、ACL／grants、tags 和管理后台清理方案。

## 持久 CA trust store

`x509: certificate signed by unknown authority` 只证明当前 TLS 链不受信任，不证明系统一定缺 CA。先检查：

```sh
ssh "root@$JETKVM_LAN_IP" '
  date -u
  ls -ld /etc/ssl /etc/ssl/certs 2>&1 || true
  ls -l /etc/ssl/certs/ca-certificates.crt 2>&1 || true
  pid=$(pidof tailscaled)
  tr "\0" "\n" < "/proc/$pid/environ" |
    grep -E "^(SSL_CERT_FILE|SSL_CERT_DIR)=" || true
  tail -n 200 /userdata/tailscale/var/tailscaled.log*.txt 2>/dev/null || true
'
```

只有设备时间正确、日志中的失败目标符合预期、并确认系统没有可读 trust store 时才安装 shim。已有普通 CA 文件时停止，改查文件损坏、TLS 拦截或新固件的 CA 路径。Tailscale 管理后台的 HTTPS Certificates 权限不能替代操作系统 CA。

在操作机下载 Mozilla CA bundle，并原子传输：

```sh
CA_TMP="$(mktemp)"
trap 'rm -f "$CA_TMP"' EXIT

curl -fsSL https://curl.se/ca/cacert.pem -o "$CA_TMP"
test "$(grep -c 'BEGIN CERTIFICATE' "$CA_TMP")" -gt 100

ssh "root@$JETKVM_LAN_IP" '
  set -eu
  umask 022
  mkdir -p /userdata/tailscale
  cat > /userdata/tailscale/cacert.pem.new
  chmod 0644 /userdata/tailscale/cacert.pem.new
  mv /userdata/tailscale/cacert.pem.new /userdata/tailscale/cacert.pem
' < "$CA_TMP"
```

先确认当前固件仍从 `/oem/usr/bin/RkLunch.sh` 顺序执行 `/userdata/init.d/S??*`。然后安装排在 `S22tailscale` 前的 rootfs 投影脚本：

```sh
INIT_TMP="$(mktemp)"
trap 'rm -f "$INIT_TMP"' EXIT

cat > "$INIT_TMP" <<'EOF'
#!/bin/sh
# Recreate rootfs links to support files kept on persistent /userdata.

case "$1" in
  start)
    if [ -f /userdata/tailscale/cacert.pem ]; then
      mkdir -p /etc/ssl/certs
      if [ -L /etc/ssl/certs/ca-certificates.crt ]; then
        ln -sf /userdata/tailscale/cacert.pem /etc/ssl/certs/ca-certificates.crt
      elif [ ! -e /etc/ssl/certs/ca-certificates.crt ]; then
        ln -s /userdata/tailscale/cacert.pem /etc/ssl/certs/ca-certificates.crt
      fi
    fi
    ;;
  stop)
    ;;
  *)
    echo "Usage: $0 {start|stop}"
    exit 1
    ;;
esac
EOF

ssh "root@$JETKVM_LAN_IP" '
  set -eu
  grep -n "/userdata/init.d/S??" /oem/usr/bin/RkLunch.sh
  umask 022
  TARGET=/userdata/init.d/S21persistent-data
  if [ -e "$TARGET" ] || [ -L "$TARGET" ]; then
    echo "$TARGET already exists; inspect and integrate it before continuing" >&2
    exit 1
  fi
  cat > "$TARGET.new"
  sh -n "$TARGET.new"
  chmod 0755 "$TARGET.new"
  mv "$TARGET.new" "$TARGET"
  "$TARGET" start
' < "$INIT_TMP"
```

从 LAN SSH 让当前 daemon 读取新 trust store：

```sh
ssh "root@$JETKVM_LAN_IP" '
  set -eu
  /userdata/init.d/S22tailscale stop
  sleep 2
  /userdata/init.d/S21persistent-data start
  /userdata/init.d/S22tailscale start
'
```

验证：

```sh
ssh "root@$JETKVM_LAN_IP" '
  test "$(readlink /etc/ssl/certs/ca-certificates.crt)" = \
    "/userdata/tailscale/cacert.pem"
  tailscale update --dry-run
  tailscale status
'
```

只有采用该 shim 的设备才需要定期更新自带 CA bundle。仍由可信操作机下载，再按上述原子写入步骤替换；不要从 JetKVM 的 BusyBox `wget` 更新。

## 精简内核与 netfilter

只有同时满足以下条件，才考虑 `netfilter-mode=off`：节点不广播子网路由、不是出口节点、不是 App Connector，也不依赖 Tailscale 管理 host firewall、转发、NAT 或防伪规则。

```sh
PREFS="$(ssh "root@$JETKVM_LAN_IP" 'tailscale debug prefs')"
STATUS="$(ssh "root@$JETKVM_LAN_IP" 'tailscale status --json')"

jq -e '
  ((.AdvertiseRoutes // []) | length == 0) and
  ((.AppConnector.Advertise // false) == false)
' <<EOF
$PREFS
EOF

jq -e '
  (.Self.ExitNodeOption == false) and
  all(.Self.AllowedIPs[]; . != "0.0.0.0/0" and . != "::/0")
' <<EOF
$STATUS
EOF
```

再证明内核没有可用实现：

```sh
ssh "root@$JETKVM_LAN_IP" '
  for command_name in nft iptables ip6tables modprobe lsmod; do
    printf "%s: " "$command_name"
    command -v "$command_name" || true
  done
  nft list tables 2>&1 || true
  find /lib/modules -type f \
    \( -name "*nf_tables*.ko*" -o -name "*ip_tables*.ko*" -o -name "*x_tables*.ko*" \) \
    2>/dev/null
'
```

典型证据是 `nft list tables` 返回 `Unable to initialize Netlink socket: Protocol not supported`，并且没有相关内核模块。满足全部前提后：

```sh
ssh "root@$JETKVM_LAN_IP" 'tailscale set --netfilter-mode=off'

ssh "root@$JETKVM_LAN_IP" 'tailscale debug prefs' |
  jq -e '.NetfilterMode == 0'
ssh "root@$JETKVM_LAN_IP" 'tailscale status --json' |
  jq -e '(.Health // []) | length == 0'
```

CLI 的 `netfilter=off` warning 在纯终端节点上是预期提示。Tailnet ACL／grants 仍过滤 Tailscale 入站流量，但 Linux netfilter 的 host firewall 接入、转发、NAT 和防伪规则不再可用。以后要启用路由、出口节点或 App Connector，必须先换成具备 netfilter 支持的内核，再恢复合适的 netfilter 模式。

## Tailnet-only HTTPS Serve

### 管理后台前置条件

MagicDNS 和 HTTPS Certificates 是 tailnet 级设置。启用 HTTPS 前先告知用户：设备 FQDN 会进入公开的 Certificate Transparency ledger，设备名不能包含敏感信息。取得明确授权后，用户或有权限的操作者才能在 Tailscale DNS 管理页启用这两项。

启用后从节点状态读取允许签发的域名：

```sh
export JETKVM_FQDN="$(
  ssh "root@$JETKVM_LAN_IP" 'tailscale status --json' |
    jq -er '.CertDomains[0]'
)"
printf 'Certificate domain: %s\n' "$JETKVM_FQDN"
```

`.CertDomains` 为空时停止，不要反复运行 `tailscale cert`。回管理后台核对 MagicDNS、HTTPS Certificates 和设备名。

### 创建 Serve

先验证本机 UI：

```sh
ssh "root@$JETKVM_LAN_IP" 'curl -fsS http://127.0.0.1:80/ >/dev/null' 2>/dev/null || \
  ssh "root@$JETKVM_LAN_IP" 'wget -qO /dev/null http://127.0.0.1:80/'
```

这里的 BusyBox `wget` 只访问本机明文 HTTP。创建持久 Serve：

```sh
ssh "root@$JETKVM_LAN_IP" \
  'tailscale serve --bg http://127.0.0.1:80'
```

`--bg` 配置会在 daemon 和设备重启后恢复。人类可读状态必须显示 tailnet only：

```sh
ssh "root@$JETKVM_LAN_IP" 'tailscale serve status'
```

机器校验以 `AllowFunnel` 为准，不能只看 HTTPS handler：

```sh
SERVE_STATUS="$(ssh "root@$JETKVM_LAN_IP" 'tailscale serve status --json')"
HOSTPORT="$JETKVM_FQDN:443"

jq -e --arg host_port "$HOSTPORT" '
  (.TCP["443"].HTTPS == true) and
  (.Web[$host_port].Handlers["/"].Proxy == "http://127.0.0.1:80") and
  all((.AllowFunnel // {})[]; . != true)
' <<EOF
$SERVE_STATUS
EOF
```

发现 Funnel 时先报告。用户授权关闭后，定点关闭 443 并重建 Serve；`reset` 会清空整台节点的全部 Serve 配置，不用它替代定点关闭。

```sh
ssh "root@$JETKVM_LAN_IP" '
  tailscale serve --https=443 off
  tailscale serve --bg http://127.0.0.1:80
'
```

### 从 tailnet 客户端验证

```sh
curl --noproxy '*' --connect-timeout 10 -fsS \
  -o /tmp/jetkvm-index.html \
  -w 'HTTP %{http_code}\n' \
  "https://$JETKVM_FQDN/"
grep -o '<title>[^<]*</title>' /tmp/jetkvm-index.html | head -n 1
rm -f /tmp/jetkvm-index.html

ssh "root@$JETKVM_LAN_IP" \
  'netstat -lntp 2>/dev/null | grep ":443 " || true'

openssl s_client \
  -connect "$JETKVM_FQDN:443" \
  -servername "$JETKVM_FQDN" \
  -showcerts </dev/null 2>/dev/null |
  openssl x509 -noout \
    -subject -issuer -dates -ext subjectAltName -fingerprint -sha256
```

当前实现能在本机观察到 443 socket 时，它不应绑定 `0.0.0.0:443`、`:::443` 或 LAN IP。socket 形状不是跨版本契约；安全结论优先依据 Serve 配置中没有 Funnel，以及非 tailnet 路径不可达。证书缓存通常位于 `/userdata/tailscale/var/certs/`；私钥和 ACME account key 保持 `0600`，不得复制到聊天、Issue 或运维笔记。

## Ghostty terminfo

Ghostty 会尝试在远端运行 `tic`。JetKVM 精简固件没有 ncurses 工具时，自动安装失败只影响终端能力，不影响 SSH、Tailscale 或 HTTPS。

优先核对当前 Ghostty help。若本机 app bundle 带预编译 `xterm-ghostty` entry，可传到持久分区：

```sh
GHOSTTY_ENTRY='/Applications/Ghostty.app/Contents/Resources/terminfo/78/xterm-ghostty'
test -f "$GHOSTTY_ENTRY"

ssh "root@$JETKVM_LAN_IP" '
  set -eu
  umask 022
  mkdir -p /userdata/terminfo/78 /userdata/terminfo/x
  cat > /userdata/terminfo/78/xterm-ghostty.new
  chmod 0644 /userdata/terminfo/78/xterm-ghostty.new
  mv /userdata/terminfo/78/xterm-ghostty.new /userdata/terminfo/78/xterm-ghostty
  cp /userdata/terminfo/78/xterm-ghostty /userdata/terminfo/x/xterm-ghostty
' < "$GHOSTTY_ENTRY"
```

需要 rootfs 链接跨重启存在时，让 Ghostty 章节独立拥有 `S20terminfo`，不要扩展 CA 的 `S21persistent-data`：

```sh
ssh "root@$JETKVM_LAN_IP" '
  set -eu
  TARGET=/userdata/init.d/S20terminfo
  if [ -e "$TARGET" ] || [ -L "$TARGET" ]; then
    echo "$TARGET already exists; inspect and integrate it before continuing" >&2
    exit 1
  fi
  cat > "$TARGET.new"
' <<'EOF'
#!/bin/sh
case "$1" in
  start)
    if [ -d /userdata/terminfo ]; then
      if [ -L /root/.terminfo ]; then
        ln -sf /userdata/terminfo /root/.terminfo
      elif [ ! -e /root/.terminfo ]; then
        ln -s /userdata/terminfo /root/.terminfo
      fi
    fi
    ;;
  stop)
    ;;
  *)
    echo "Usage: $0 {start|stop}"
    exit 1
    ;;
esac
EOF

ssh "root@$JETKVM_LAN_IP" '
  set -eu
  TARGET=/userdata/init.d/S20terminfo
  sh -n "$TARGET.new"
  chmod 0755 "$TARGET.new"
  mv "$TARGET.new" "$TARGET"
  "$TARGET" start
'
```

再按当前 `ghostty +ssh-cache --help` 为实际使用的 `user@hostname` 加本地缓存。不能安装时，在该 SSH Host 上回退 `TERM=xterm-256color`。

## 证书分诊

线上证书是验收对象：

```sh
openssl s_client \
  -connect "$JETKVM_FQDN:443" \
  -servername "$JETKVM_FQDN" </dev/null 2>/dev/null |
  openssl x509 -noout -dates -fingerprint -sha256
```

Serve 使用 daemon 管理的证书，不要把手工 `tailscale cert --cert-file` 输出当作同一续期路径。手工落盘的证书由操作者负责续期。例行检查同时读取 Serve、节点健康、线上证书和相关日志：

```sh
ssh "root@$JETKVM_LAN_IP" 'tailscale status --json' |
  jq '{Health, CertDomains}'
ssh "root@$JETKVM_LAN_IP" 'tailscale serve status'
ssh "root@$JETKVM_LAN_IP" \
  'tail -n 200 /userdata/tailscale/var/tailscaled.log*.txt 2>/dev/null'
```

按证据分三类：

| 现象 | 结论 | 下一步 |
| --- | --- | --- |
| `unknown authority` | TLS 链不受信任，根因未定 | 检查时间、系统 CA、daemon 环境和失败目标 |
| control、Noise 或登录请求超时 | 到 Tailscale control plane 的网络路径异常 | 先修网络；不把临时代理固化成依赖 |
| `SetDNS` 成功后 authorization／order 很快 `invalid` | 疑似 DNS-01 传播竞态 | 停止重试，遵守 `Retry-After`，核对精确版本和上游现状 |

只有第三类且精确版本为 v1.102.2 时，才考虑专门的历史恢复 reference。其他情形不启动自编译 daemon。

## 更新、回滚与固件

升级前保存不含节点 state 的回滚集：

```sh
VERSION_STATUS="$(
  ssh "root@$JETKVM_LAN_IP" 'tailscale version --daemon --json'
)"
printf '%s\n' "$VERSION_STATUS" | jq -e '.long == .daemonLong'
CURRENT_VERSION="$(printf '%s\n' "$VERSION_STATUS" | jq -er '.short')"
export ROLLBACK_DIR="/userdata/tailscale-rollback-$CURRENT_VERSION"

ssh "root@$JETKVM_LAN_IP" "
  set -eu
  umask 077
  mkdir -p '$ROLLBACK_DIR'
  cp /userdata/tailscale/tailscale '$ROLLBACK_DIR/tailscale'
  cp /userdata/tailscale/tailscaled '$ROLLBACK_DIR/tailscaled'
  cp /userdata/init.d/S22tailscale '$ROLLBACK_DIR/S22tailscale'
  chmod 0755 '$ROLLBACK_DIR/tailscale' \
    '$ROLLBACK_DIR/tailscaled' '$ROLLBACK_DIR/S22tailscale'
  cd '$ROLLBACK_DIR'
  sha256sum tailscale tailscaled S22tailscale > SHA256SUMS
  cat SHA256SUMS
"
```

回滚目录只包含上述 CLI、daemon、init 脚本和校验文件。禁止加入 `tailscaled.state`、`var/certs`、ACME account key 或任何私钥。

在维护窗口用官方 JetKVM 安装器和明确版本升级。不要直接运行 generic `tailscale update --yes`，除非现场已证明它能重启当前 JetKVM init 形状。

需要回退时，通过 LAN SSH 校验备份并逐文件落位。三个文件不是一个原子事务，所以 LAN 控制路径必须持续可用，并用退出 trap 尝试启动当前已落位版本：

```sh
export ROLLBACK_DIR='/userdata/tailscale-rollback-REPLACE_WITH_VERSION'

ssh "root@$JETKVM_LAN_IP" "
  set -eu
  start_current() {
    if [ -x /userdata/init.d/S21persistent-data ]; then
      /userdata/init.d/S21persistent-data start
    fi
    /userdata/init.d/S22tailscale start
  }
  trap start_current EXIT
  trap 'exit 1' HUP INT TERM

  cd '$ROLLBACK_DIR'
  sha256sum -c SHA256SUMS
  test -x tailscale
  test -x tailscaled
  test -x S22tailscale

  /userdata/init.d/S22tailscale stop
  sleep 2
  cp tailscale /userdata/tailscale/tailscale.rollback
  cp tailscaled /userdata/tailscale/tailscaled.rollback
  cp S22tailscale /userdata/init.d/S22tailscale.rollback
  chmod 0755 /userdata/tailscale/tailscale.rollback \
    /userdata/tailscale/tailscaled.rollback \
    /userdata/init.d/S22tailscale.rollback
  sh -n /userdata/init.d/S22tailscale.rollback
  mv /userdata/tailscale/tailscale.rollback /userdata/tailscale/tailscale
  mv /userdata/tailscale/tailscaled.rollback /userdata/tailscale/tailscaled
  mv /userdata/init.d/S22tailscale.rollback /userdata/init.d/S22tailscale

  start_current
  trap - EXIT HUP INT TERM
"

ssh "root@$JETKVM_LAN_IP" 'pidof tailscaled'
ssh "root@$JETKVM_LAN_IP" 'tailscale version --daemon --json' |
  jq -e '.long == .daemonLong'
ssh "root@$JETKVM_LAN_IP" 'tailscale status --json' |
  jq -e '.BackendState == "Running" and .Self.Online == true'
```

固件升级后先证明 `/userdata`、启动入口、init 文件和二进制仍存在：

```sh
ssh "root@$JETKVM_LAN_IP" '
  mount | grep " on /userdata "
  grep -n "/userdata/init.d/S??" /oem/usr/bin/RkLunch.sh
  ls -l /userdata/init.d/S21persistent-data /userdata/init.d/S22tailscale
  ls -l /userdata/tailscale/tailscale /userdata/tailscale/tailscaled
'
```

任一条件不成立时停止 daemon、Serve 和证书写操作。先恢复挂载与 init 链。JetKVM 固件 DFU 恢复按官方文档执行，不在本 Runbook 中重写。

## 验收

### 不重启验收

```sh
curl --noproxy '*' --connect-timeout 5 -fsS \
  -o /dev/null -w 'LAN HTTP %{http_code}\n' \
  "http://$JETKVM_LAN_IP/"

ssh "root@$JETKVM_LAN_IP" 'tailscale status --json' |
  jq -e '
    .BackendState == "Running" and
    .Self.Online == true and
    ((.Health // []) | length == 0)
  '

ssh "root@$JETKVM_LAN_IP" 'tailscale version --daemon --json' |
  jq -e '.long == .daemonLong'

SERVE_STATUS="$(ssh "root@$JETKVM_LAN_IP" 'tailscale serve status --json')"
HOSTPORT="$JETKVM_FQDN:443"
jq -e --arg host_port "$HOSTPORT" '
  (.TCP["443"].HTTPS == true) and
  (.Web[$host_port].Handlers["/"].Proxy == "http://127.0.0.1:80") and
  all((.AllowFunnel // {})[]; . != true)
' <<EOF
$SERVE_STATUS
EOF

ssh -o BatchMode=yes "root@$JETKVM_TS_IP" 'echo tailnet-ssh-ok'
curl --noproxy '*' --connect-timeout 10 -fsS \
  -o /dev/null -w 'HTTPS %{http_code}\n' \
  "https://$JETKVM_FQDN/"

LISTEN_443="$(
  ssh "root@$JETKVM_LAN_IP" \
    'netstat -lntp 2>/dev/null | grep ":443 "'
)"
printf '%s\n' "$LISTEN_443"
if [ -n "$LISTEN_443" ]; then
  if printf '%s\n' "$LISTEN_443" | grep -Fq '0.0.0.0:443' ||
    printf '%s\n' "$LISTEN_443" | grep -Fq ':::443' ||
    printf '%s\n' "$LISTEN_443" | grep -Fq "$JETKVM_LAN_IP:443"; then
    echo 'unexpected non-tailnet HTTPS listener' >&2
    exit 1
  fi
fi
```

条件修复另验：

```sh
# 仅当节点已被证明是无 netfilter 的纯终端时执行。
ssh "root@$JETKVM_LAN_IP" 'tailscale debug prefs' |
  jq -e '.NetfilterMode == 0'

# 仅当安装了 CA shim 时执行。
ssh "root@$JETKVM_LAN_IP" '
  test "$(readlink /etc/ssl/certs/ca-certificates.crt)" = \
    "/userdata/tailscale/cacert.pem"
  test -f /userdata/tailscale/cacert.pem
'

# 仅当安装了 Ghostty entry 时执行。
ssh "root@$JETKVM_LAN_IP" '
  test -f /root/.terminfo/78/xterm-ghostty
  test -x /userdata/init.d/S20terminfo
'
```

### 重启验收

取得重启授权后，从 LAN SSH 重启的是 JetKVM 自身，不是受控主机：

```sh
ssh "root@$JETKVM_LAN_IP" 'sync; reboot' || true
```

等待 LAN SSH 恢复后完整重跑不重启验收。只有重启后仍通过，才能断言 init、Serve、CA 和节点状态持久有效。

### load average 不是 Tailscale 健康信号

不要仅凭 load average 把故障归因于 Tailscale。Tailscale `Health`、相关日志、连接响应和实际 CPU／I/O 证据均正常时，转入 JetKVM 系统诊断；本 Skill 不判断媒体栈或 JetKVM 应用进程是否健康。

## 上游入口

- <https://jetkvm.com/docs/networking/remote-access>
- <https://jetkvm.com/install-tailscale.sh>
- <https://tailscale.com/docs/reference/tailscale-cli/serve>
- <https://tailscale.com/docs/how-to/set-up-https-certificates>
- <https://tailscale.com/docs/features/tailscale-funnel>
- <https://github.com/tailscale/tailscale/blob/v1.102.2/cmd/tailscale/cli/configure-jetkvm.go>
- <https://github.com/tailscale/tailscale/blob/v1.102.2/clientupdate/clientupdate.go>
- <https://ghostty.org/docs/features/ssh>
- <https://ghostty.org/docs/help/terminfo>
