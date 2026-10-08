from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REALITY = ROOT / "references" / "reality-hy2"


def read(name: str) -> str:
    return (REALITY / name).read_text()


def flat(text: str) -> str:
    return " ".join(text.split())


def test_version_selection_and_package_reload_are_explicit():
    server = read("server.md")
    linux = read("linux-client.md")

    assert "最新稳定版，不写死补丁版本" in server
    assert "apt-cache policy sing-box" in server
    assert '"${SINGBOX_VERSION:?select the latest stable candidate' in server
    assert "悄悄降级" in server
    assert "SINGBOX_PIN" not in server
    assert "1.13." not in server
    assert "1.13." not in linux
    assert "systemctl daemon-reload" in server
    assert "server.md#选版本" in linux
    assert "Certbot 按可执行位挑 deploy hook" in server
    assert "`.bak` 后缀也照样会跑" in server
    assert "find -L" in server
    assert "-perm /111" in server


def test_server_external_targets_require_explicit_source():
    server = read("server.md")
    testing = read("testing.md")
    normalized = flat(server)
    fixture_text = flat(testing)

    assert "长期使用的 `REALITY_SNI`" in server
    assert "不从「部署一台」的要求、别的服务器或全局默认值推出来" in server
    assert "只停下依赖它的配置" in server
    assert "公开域名的一次性 DNS 取证" in server
    assert "私有、敏感域名不发给用户没认可的第三方 resolver" in server
    assert '@"$DNS_RESOLVER_IP"' in server
    assert '"type": "string"' in server
    assert "不需要 `MASQUERADE_URL`" in server
    assert "198.18.0.0/15" in server
    assert "`nc -z` 可能报 TCP 连接成功" in server
    assert "不能当公网端口的证据" in normalized
    assert "可以只上 HY2（下称 HY2-only）" in server
    assert "去掉 `443/tcp` 那条" in server
    assert "不生成、不保存没有 inbound 用的" in server
    assert "REALITY 报为未配置、未验证" in normalized
    assert "canceled by remote with error code 0" in server
    assert "testing.md#一次性-reality-源站" in server
    assert "## 一次性 REALITY 源站" in testing
    assert '"server_port": __REALITY_HANDSHAKE_PORT__' in server
    assert "-cert_chain" in testing
    assert "不会发送完整证书链" in fixture_text
    assert "HTTP/1.1 的 curl 探测不等价" in fixture_text
    assert "EXPECTED_TCP_443" in server
    assert 'main_pid="$(systemctl show sing-box -p MainPID --value)"' in server
    assert "REALITY: processed invalid connection" in server
    assert "不能引入第二个防火墙管理者" in server
    assert "各记一次 `MainPID` 和 `NRestarts`" in server
    assert "rollback()" in server
    assert 'if test "$ready" -ne 1' in server
    assert "was_enabled=0" in server
    assert "--no-random-sleep-on-renew" in server
    assert "单进程的测试夹具" in testing
    assert "立即重启这个临时 unit" in fixture_text
    assert "无关的公网扫描器" in testing
    assert "已有的 sing-box、Snell、xray、Mihomo" in server
    assert "归属不明时，停下" in server


def test_reality_short_id_matches_current_binary():
    server = read("server.md")

    assert 'REALITY_SHORT_ID="$(openssl rand -hex 8)"' in server
    assert "最多 16 位的十六进制串" in server


def test_skill_routes_and_owns_the_status_contract():
    skill = (ROOT / "SKILL.md").read_text()

    for status in ("`pass`", "`fail`", "`not-configured`", "`not-attempted`", "`inconclusive`", "`blocked`"):
        assert status in skill
    assert "REALITY 和 HY2 分开报" in skill
    assert "```mermaid" in skill
    for target in (
        "references/snell/audit.md",
        "references/snell/deploy.md",
        "references/snell/tuning.md",
        "references/reality-hy2/server.md",
        "references/reality-hy2/linux-client.md",
        "references/reality-hy2/clients.md",
        "references/reality-hy2/testing.md",
        "references/reality-hy2/monitoring.md",
        "references/fleet/bandwagonhost.md",
        "references/fleet/cn-reachability.md",
    ):
        assert f"({target})" in skill


def test_one_shot_monitor_rejects_existing_listener_and_ties_readiness_to_pid():
    monitoring = read("monitoring.md")

    assert "set -euo pipefail" in monitoring
    assert "--head" in monitoring
    assert "--noproxy '*'" in monitoring
    assert "[1-5][0-9][0-9])" in monitoring
    assert "http3_result=fail" in monitoring
    assert "tls_result=unknown" in monitoring
    assert "monitor_result=pass" in monitoring
    assert "53|58|59|66|77|82) monitor_result=invalid" in monitoring
    assert "60) tls_result=invalid" in monitoring
    assert "51|53|58|59|60|64|66|77|80|82|83|90|91" not in monitoring
    assert "`--disable` 让探针用户的 `.curlrc` 不生效" in monitoring
    assert monitoring.count("if curl --disable") == 2
    assert "SecureTransport" in monitoring
    assert "HTTP/3 probe returned no valid HTTP status" in monitoring
    assert "local monitor port 2089 is already owned" in monitoring
    assert 'grep -Fq "pid=$sidecar_pid,"' in monitoring
    assert "sidecar_listening && break" in monitoring
    assert "DNS_RESOLVER_IP" in monitoring
    assert "EGRESS_ECHO_URL" in monitoring
    assert "不等于同意把它的域名和出口发给第三方 DNS 或 IP 回显服务" in monitoring
    assert "配置文件里写了路由排除只是意图，不是运行时证据" in monitoring
    for run_class in (
        "AUTH_OR_ECHO_UNREACHABLE",
        "HTTP3_DEGRADED",
        "MONITOR_LOCAL_FAILURE",
        "DIRECT_AND_AUTH_UNREACHABLE",
        "MONITOR_INCONCLUSIVE",
        "ECHO_DEPENDENCY_DEGRADED",
        "AUTH_EGRESS_MISMATCH",
        "TLS_INVALID",
    ):
        assert run_class in monitoring
    assert "有 HTTP 响应但没有可用 IP" in monitoring
    assert "可能是 HY2 认证、sidecar 出口或回显服务出了问题" in monitoring
    assert "最后永远不告警" in monitoring
    assert "通知成功记为 API 已接受，不算设备已收到" in monitoring
    assert "create netlink socket: address family not supported by protocol" in monitoring


def test_linux_validation_fails_closed_for_journal_and_old_proxy_units():
    linux = read("linux-client.md")
    migration = read("linux-migration.md")
    clients = read("clients.md")
    testing = read("testing.md")
    linux_normalized = flat(linux)
    testing_normalized = flat(testing)

    assert 'if ! recent_log="$(journalctl' in linux
    assert "cannot read the bounded sing-box journal" in linux
    assert 'test -n "$validation_log"' in linux
    assert "missing VLESS packet evidence" in linux
    assert 'unexpected_log="$(' in linux
    assert "canceled by remote with error code 0" in linux
    assert linux.index("把常驻的日志级别切回 `warn`") < linux.index("做完稳态验证")
    assert "systemctl --user list-unit-files" in migration
    assert "enabled system proxy unit or unreadable system unit inventory" in migration
    assert "enabled user proxy unit or unreadable user unit inventory" in migration
    assert 'if ! system_running="$(systemctl list-units' in migration
    assert 'if ! user_running="$(systemctl --user list-units' in migration
    assert "pgrep_code=$?" in migration
    assert 'if ! socket_inventory="$(ss -lntup)"' in migration
    assert "grep_code=$?" in migration
    assert "用户级清理就算没验证" in migration
    assert "certificate_path" in clients
    assert "它不是按顺序的主备切换" in clients
    assert "所选版本的 URLTest 文档" in clients
    assert "每个不同的 outbound 服务端 IP 都加进 `route_exclude_address`" in linux_normalized
    assert "## 虚拟机和容器的转发流量" in linux
    assert '"source_ip_cidr": ["__DOWNSTREAM_CIDR__"]' in linux
    assert '"action": "bypass"' in linux
    assert '"listen": "__PRIVATE_GATEWAY_IP__"' in linux
    assert "不会让 guest 或容器走宿主的代理" in linux_normalized
    assert "`systemctl is-active` 和监听中的 socket 只能证明控制面状态" in linux_normalized
    assert "## 转发流量的数据路径" in testing
    assert "path=host-tun" in testing
    assert "path=guest-direct" in testing
    assert "path=guest-proxy" in testing
    assert 'RUNS="${RUNS:-1}"' in testing
    assert "先让这个候选单独当 selector 默认" in testing_normalized
    assert "远程 DNS 可能随所选 outbound 一起失败" in testing_normalized
    assert "## 私有 CA 的协议端到端测试" in testing
    assert "tls_choose_sigalg:no suitable signature algorithm" in testing
    assert "http_version=%{http_version}" in testing
    assert "只改错一个凭据的候选" in testing
    assert "排队的有效请求看起来像认证回归" in testing


def test_hy2_buffer_guidance_matches_current_quic_behavior():
    linux = read("linux-client.md")

    assert "UnbindPacketConn" not in linux
    assert "rmem_default" not in linux
    assert "QUIC 会主动给新 socket 申请大缓冲" in linux
    assert "不写 `up_mbps` 时上传用 BBR" in linux


def test_common_client_profile_owns_shared_shape_without_linux_routing_dependency():
    clients = read("clients.md")
    linux = read("linux-client.md")

    assert "## 共用的 mixed profile" in clients
    assert '"tag": "vless-reality-out"' in clients
    assert '"tag": "hy2-h3-out"' in clients
    assert "clients.md" in linux
    assert "不要套用 Linux TUN 的服务语义" in clients
    assert "不要把 Linux 的 `route_exclude_address` 做法抄过来" in clients


def test_references_keep_cli_and_surges_runtime_ownership_separate():
    triage = (ROOT / "references" / "snell" / "audit.md").read_text()

    assert "uv run --script" in triage
    assert "ConfigDirectoryPath" not in triage
    assert "SelectedConfigName" not in triage
    assert "KDDefaults.plist" not in triage
    assert "用户要改 profile 时交给 `$surge`" in triage


def test_protocol_monitoring_delegates_long_running_monitoring_contract():
    monitoring = read("monitoring.md")

    assert "把类别和证据交给 `$monitoring`" in monitoring
    assert "那边管探测频率、新鲜度" in monitoring
    assert "告警送达" in monitoring


def test_linux_durable_activation_has_preflight_and_rollback_gates():
    linux = read("linux-client.md")
    normalized = flat(linux)

    assert "启用或重启常驻服务之前" in linux
    assert "sing-box|snell|xray|mihomo" in linux
    assert "盘点读不出来或有归属不明的，就停下" in linux
    assert "candidate=/etc/sing-box/<name>.json.new" in linux
    assert 'sing-box format -w -c "$candidate"' in linux
    assert "had_target=0" in linux
    assert "was_active=0" in linux
    assert "rollback()" in linux
    assert 'if test "$ready" -ne 1' in linux
    assert "候选校验、上线、就绪和回滚都在下面这一段里" in normalized


def test_macos_client_stays_native_hy2_and_avoids_a_second_runtime():
    clients = read("clients.md")
    testing = read("testing.md")

    assert "## macOS（Surge 原生 HY2）" in clients
    assert "归 `$surge`" in clients
    assert "Surge 不原生支持 VLESS REALITY" in clients
    assert "那是另一个设计决定" in clients
    assert "Fake IP" in clients
    assert "不要为了在 Mac 上测 REALITY 再装一个运行时" in testing


def test_macos_routes_snell_work_to_its_own_skill():
    clients = read("clients.md")

    assert "已有 Snell policy 和它的服务健康归 `references/snell/`" in clients
    assert "不顺手生成新的备用 policy" in clients


def test_android_full_device_profile_has_a_tun_baseline():
    clients = read("clients.md")
    normalized = flat(clients)

    assert '"type": "tun"' in clients
    assert '"auto_route": true' in clients
    assert '"strict_route": true' in clients
    assert "只有 mixed inbound 时，验到的只是显式走代理的那些应用流量" in normalized
    assert "不能承诺两个同时作为整机 VPN 运行" in normalized
