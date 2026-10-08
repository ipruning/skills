# 审计和排查 Snell

Surge + Snell 出问题，可能在本机 Surge 路由、Snell listener、systemd、防火墙、云厂商网络、Linux 限制或 VPS 出站任何一层。先看再动：审计只经 SSH 跑只读采集命令，不改配置、不重启服务、不装软件、不调参。

## 本机 Surge 这一侧

先看本机状态，再判断 Surge 运行时或 profile：

```bash
surge-cli --raw environment
surge-cli --raw dump policy
surge-cli --raw dump profile
```

`smoke-surge` 只探测当前运行时里已有的某个 policy，不生成、注册、切换或恢复 profile。只读审计里不做 `reload` 和 `switch-profile`：它们会改本机网络，用户要配置、激活或验证客户端时才做。要找的 policy 不在当前 profile 里，不从审计这条路去改；用户要改 profile 时交给 `$surge`，由它管 profile 路径、控制路径和回滚。

测试正在查的 policy，可以直接跑 `surge-cli`：

```bash
surge-cli --raw test-policy <policy-name>
surge-cli --raw test-policy-udp <policy-name>
surge-cli --raw test-policy-external-ip <policy-name>
surge-cli --raw test-policy-nat-type <policy-name>
```

也可以用审计脚本的 `smoke-surge` 一次跑完并留下证据：

```bash
uv run --script "$SKILL_DIR/scripts/snell_audit.py" smoke-surge \
  --policy <policy-name> \
  --out /tmp/snell-runs
```

返回空对象或「找不到 policy」时，先确认它在当前 profile 里，再怀疑 VPS。

怎么读结果：

- 「命令成功」只是 `surge-cli` 退出码为 0 且输出能解析。TCP 或 UDP 的 policy 对象里带 `error`，或者嵌套的 policy 对象是空的，就是探测失败，哪怕退出码为 0 或报了延迟。
- `smoke-surge` 顶层 `status=ok` 表示所有探测都过了；`status=warn` 表示至少一项不支持。UDP relay 和 NAT 穿透要看 `results[]` 里对应那项是 `status="passed"`，且 `parsed` 是预期值，才能说正常。
- `test-policy-udp` 成功说明 UDP relay 经所选 policy 能走。Snell v6 一般是 UDP over TCP 代理连接，不需要 Snell 在服务端口上监听或暴露 UDP。
- `test-policy-nat-type` 看的是 Snell VPS 自己出站 UDP socket 的 NAT 穿透，和 UDP relay 是两回事。命令成功也可能报 Type C；Type C 是一个合法的观测，不等于通过了 Surge Ponte 默认要求的 Type A。TCP、出口 IP、UDP relay 都过而 NAT 是 Type C（`nat-type=3`）时，按 [tuning.md](tuning.md#surge-ponte-的-nat-类型是-type-c) 处理：放行的是 VPS 的临时 UDP 源端口段，不是 `<snell-port>/udp`。

### 别让测试切断控制路径

Surge 增强模式或规则模式开着时，本机的 CLI 工具可能正走在被测的代理上。用 SSH 或直连 TCP 碰 Snell 端点之前，用实际的请求记录确认最终命中的 policy，并确认改动不会切断唯一的控制路径。profile 规则或 `DIRECT` 只是 Surge 层的证据，证明不了这个进程绕过了增强模式，也证明不了端点公网可达。

需要临时加 `DIRECT` 规则时，作为人工操作写出来，附回滚方法；审计这条路不改 Surge 运行时和 profile。

## 远端审计

脚本是 `scripts/snell_audit.py`，下面的 `$SKILL_DIR` 指本 Skill 的安装目录。参数以 `uv run --script "$SKILL_DIR/scripts/snell_audit.py" <子命令> --help` 为准。端口必填，取自这台目标核实过的配置。

审计一台：

```bash
uv run --script "$SKILL_DIR/scripts/snell_audit.py" audit-snell \
  --host <ssh-target> \
  --port <snell-port> \
  --journal-since "6 hours ago" \
  --remote-base /var/tmp \
  --out /tmp/snell-runs
```

审计一批：

```bash
uv run --script "$SKILL_DIR/scripts/snell_audit.py" audit-fleet \
  --hosts ./snell-hosts.jsonl \
  --journal-since "6 hours ago" \
  --remote-base /var/tmp \
  --out /tmp/snell-runs
```

`--hosts` 文件每行一个 SSH 目标时，`--port`、`--service`、`--expected-sha256` 从命令行继承，`--port` 必填。各台不一样时每行写一个 JSON 对象，保存前替换占位符：

```text
{"host":"<ssh-target-1>","port":<snell-port-1>,"expected_sha256":"<64-hex-sha256>"}
{"host":"<ssh-target-2>","port":<snell-port-2>,"service":"<unit.service>","expected_sha256":"<64-hex-sha256>","sudo":true,"ssh_options":["ControlMaster=auto","ControlPersist=60s","ControlPath=/tmp/snell-audit-%C.sock"]}
```

只认 `host`、`port`、`service`、`expected_sha256`、`sudo`、`ssh_options` 这几个键。`sudo` 必须是布尔值，`true` 时只读采集和清理走 `sudo -n`，之后把证据的属主还给 SSH 用户。`ssh_options` 是普通的 `ssh -o` 值，用来给单台配连接复用，不能塞凭据。重复的 host 和未知的键直接失败。这个文件里永远不放密码、PSK、token 或私钥。

退出码：SSH 准备或传输、上传、远端执行、回收、清理任一步失败，`audit-snell` 非零退出；`audit-fleet` 只要有一台失败就退出 1，其余主机照常审计，结果都在输出的 `results[]` 里。审计跑完但 `status=issue` 时默认退出 0，加 `--fail-on-issue` 才是 1。

### 远端临时目录

采集脚本用 Bash，VPS 上不需要 Python 包。它把 payload 传到 `<remote-base>/<run_id>`，回收到本地 `--out`，回收成功后删掉远端目录。只创建、清理带归属标记的那个运行目录，父目录不动；`--remote-base` 默认 `/var/tmp`，父目录必须已存在，否则准备阶段报错。回收或清理失败时，`persistent_effects` 会写出可能残留的远端目录，重试前删掉那个确切的目录。用户不许在目标上落盘时，用 `--dry-run` 只打印计划，或者手工跑不落盘的只读命令。

### SSH 第一步通、SCP 被重置

第一步 SSH 成功、紧接着的 SCP 被重置，而 Surge 或别的本机路由改了控制机的出口时，不能算成 VPS 的问题。要么让用户加临时 `DIRECT` 规则，要么给这一次审计单独开一条复用连接：

```bash
control_socket=/tmp/snell-audit-example.sock
uv run --script "$SKILL_DIR/scripts/snell_audit.py" audit-snell \
  --host <ssh-target> \
  --port <snell-port> \
  --run-id snell-audit-example \
  --remote-base /var/tmp \
  --out /tmp/snell-runs \
  --ssh-option ControlMaster=auto \
  --ssh-option ControlPersist=60s \
  --ssh-option "ControlPath=$control_socket"
ssh -S "$control_socket" -O exit <ssh-target> 2>/dev/null || true
rm -f -- "$control_socket"
```

socket 按这次运行命名，不写进全局 SSH 配置。

### 采集了什么

远端只读这些，日志写在运行目录里（`snell-server` 只是示例，unit 名以脚本实际发现的为准，它默认找唯一的 `*snell*.service`）：

```bash
hostname -f || hostname
date -u
uname -a
snell-server -v
sha256sum <snell-binary>
systemctl show snell-server -p ActiveState -p SubState -p Result -p NRestarts -p LimitNOFILE -p User -p Group -p Restart -p MainPID
systemctl is-enabled snell-server
systemctl cat snell-server
ss -lntup
sshd -T
ufw status verbose
nft list ruleset
iptables -S
ip6tables -S
docker ps --format '{{.ID}} {{.Names}} {{.Ports}}'
sysctl net.core.default_qdisc net.ipv4.tcp_congestion_control net.core.somaxconn net.ipv4.tcp_max_syn_backlog net.ipv4.tcp_syncookies net.ipv4.ip_local_port_range net.ipv4.ip_local_reserved_ports net.ipv4.tcp_mtu_probing net.netfilter.nf_conntrack_count net.netfilter.nf_conntrack_max
swapon --show --bytes
df -Pk / /var /boot
journalctl -u snell-server --since <window> -o short-iso --no-pager
journalctl --disk-usage
```

另外数 `/root/.ssh/authorized_keys` 里能读到的条目，读 `ExecStart -c` 指向的 Snell 配置，读 `/proc/meminfo`、`/etc/fstab`、`/etc/os-release`。

一定要看 `systemctl cat`：主 unit 看着干净时，drop-in 里也可能还开着加固。

payload 打印 Snell 配置时会遮掉 `psk = ...` 这一行，但不保证每个证据文件都没有 secret。PSK 不放进 unit、journal、host 文件、policy 名或 run ID；运行目录要分享出去之前，先扫一遍 secret。profile 名、端点 IP 和 journal 原文也可能敏感。

## 读 audit.json

stdout 只输出一个 JSON 对象；日志和命令输出都留在运行目录里。

- `facts`：看到了什么。
- `findings`：哪里像有问题；每条带 id 和建议操作。
- `evidence_paths`：本地证据文件。
- `recommended_manual_actions`：值得考虑的操作，不是要执行的命令。

findings 只报结构性问题：崩溃特征、暴露面、加固、可用性。性能和容量由读的人从 `facts` 判断；`facts.sysctl`、`facts.swap`、`facts.systemd.limit_nofile`、`facts.ssh.max_auth_tries`、`facts.logs` 只给实测值，不打分。要调参时读 [tuning.md](tuning.md)。

`Decryption failed` 的次数在 `facts.logs.decryption_failed_count`，来源最多的在 `facts.logs.top_decryption`。`facts.logs.*` 都来自按关键词过滤、上限 500 行的 journal 摘录，是下限，日志多的主机上会封顶。`Decryption failed` 不自动等于服务端故障：可能是扫描器、错的 PSK、旧客户端，或者自己的测试。没有负载、资源压力或崩溃佐证时当噪声。

单看 `systemctl active`、端口在监听或一条 `Decryption failed`，都下不了端到端结论。

## v5 和 v6 的区别

| 版本 | listener | 配置 | 防火墙 |
| --- | --- | --- | --- |
| v5 | 用 UDP/QUIC 的部署里 TCP + UDP 都可能是对的 | `listen`、`psk`，可能留着旧字段 | 服务确实监听 UDP 时，暴露 UDP 可能是有意的 |
| v6 | 一般只有 TCP | 不用旧的 `ipv6`、`obfs`、`reuse`、`version` | 用户没给具体理由就不开 UDP |

`udp_listen=yes` 不一定健康，`udp_listen=no` 也不一定坏。用户请求、Snell 配置、listener／防火墙盘点或客户端 profile 能说明这是 v5 UDP/QUIC 部署时，才接受 TCP 和 UDP 都监听在 Snell 端口上。普通 v6 只预期 TCP。

`snell-server -v` 只能看大版本和构建信号：有些 beta 或 RC 只报基础版本号和构建日期。要确认具体版本，拿装着的二进制的 SHA-256 和从官方发布地址重新下载的字节比，或者和用户提供的摘要比。

## v5 UDP 崩溃

v5 的 UDP/QUIC 会被 systemd 加固堵住 socket 路径而崩溃。这几行一起出现时要当回事：

```text
UDP socket send error: invalid argument
uv_close: Assertion `0' failed
signal 6
Main process exited
```

drop-in 里有 `PrivateDevices`、`ProtectSystem`、`RestrictAddressFamilies`、`CapabilityBoundingSet`、`NoNewPrivileges` 或 `PrivateTmp` 的，人工看，不要自动删。

## 小节点的样子

只跑 Snell 的 VPS 该是什么样、容器或应用主机怎么区别对待，见 [deploy.md](deploy.md#先看是哪种主机)。审计时按那个基线评估 Snell，但它不是重写应用或容器主机的理由。
