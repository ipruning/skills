from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_server_external_targets_require_explicit_source_authorization():
    server = (ROOT / "references" / "server.md").read_text()
    normalized = " ".join(server.split())

    assert "必须逐项由用户指定" in server
    assert "明确授权 Agent" in server
    assert "缺少来源授权时停止并询问" in server
    assert "DNS_RESOLVER_IP" in server
    assert '@"$DNS_RESOLVER_IP"' in server
    assert '"type": "string"' in server
    assert "不需要 `MASQUERADE_URL`" in server
    assert "198.18.0.0/15" in server
    assert "`nc -z` can report a successful TCP connect" in server
    assert "Do not use that result as public-port evidence" in normalized
    assert "HY2-only partial rollout" in server
    assert "omit the `443/tcp` rule" in server
    assert "Do not generate" in server
    assert "reports REALITY as not configured and unverified" in normalized
    assert "canceled by remote with error code 0" in server
    assert "Disposable Self-Contained REALITY Origin" in server
    assert "REALITY_HANDSHAKE_PORT" in server
    assert '"server_port": __REALITY_HANDSHAKE_PORT__' in server
    assert "-cert_chain" in server
    assert "does not send the complete chain" in normalized
    assert "an HTTP/1.1 curl probe is not equivalent" in normalized
    assert "EXPECTED_TCP_443" in server
    assert 'main_pid="$(systemctl show sing-box -p MainPID --value)"' in server
    assert "REALITY: processed invalid connection" in server
    assert "must not introduce a second firewall owner" in server
    assert "Record `MainPID` and `NRestarts`" in server
    assert "--no-random-sleep-on-renew" in server
    assert "single-process test fixture" in server
    assert "restart this transient unit" in normalized
    assert "unrelated public scanner" in server


def test_one_shot_monitor_rejects_existing_listener_and_ties_readiness_to_pid():
    monitoring = (ROOT / "references" / "monitoring.md").read_text()

    assert "set -euo pipefail" in monitoring
    assert "[1-5][0-9][0-9])" in monitoring
    assert "HTTP/3 probe returned no valid HTTP status" in monitoring
    assert "local monitor port 2089 is already owned" in monitoring
    assert 'grep -Fq "pid=$sidecar_pid,"' in monitoring
    assert "sidecar_listening && break" in monitoring
    assert "DNS_RESOLVER_IP" in monitoring
    assert "EGRESS_ECHO_URL" in monitoring
    assert "does not implicitly authorize third-party DNS or IP echo services" in monitoring


def test_linux_validation_fails_closed_for_journal_and_old_proxy_units():
    linux = (ROOT / "references" / "linux-client.md").read_text()
    testing = (ROOT / "references" / "testing.md").read_text()

    assert 'if ! recent_log="$(journalctl' in linux
    assert "cannot read the bounded sing-box journal" in linux
    assert 'test -n "$validation_log"' in linux
    assert "missing VLESS packet evidence" in linux
    assert 'unexpected_log="$(' in linux
    assert "canceled by remote with error code 0" in linux
    assert linux.index("restore durable log level to `warn`") < linux.index("Complete steady-state validation")
    assert "systemctl --user list-unit-files" in linux
    assert "enabled system proxy unit or unreadable system unit inventory" in linux
    assert "enabled user proxy unit or unreadable user unit inventory" in linux
    assert 'if ! system_running="$(systemctl list-units' in linux
    assert 'if ! user_running="$(systemctl --user list-units' in linux
    assert "pgrep_code=$?" in linux
    assert 'if ! socket_inventory="$(ss -lntup)"' in linux
    assert "grep_code=$?" in linux
    assert "user-level cleanup remains unverified" in linux
    assert "tls.certificate_path" in linux
    assert "Private-CA Protocol E2E" in testing
    assert "tls_choose_sigalg:no suitable signature algorithm" in testing
    assert "http_version=%{http_version}" in testing
    assert "one deliberately wrong credential" in testing
    assert "queued valid request" in testing


def test_macos_temporary_profile_switch_is_verified_and_restored():
    macos = (ROOT / "references" / "macos-client.md").read_text()
    testing = (ROOT / "references" / "testing.md").read_text()
    macos_normalized = " ".join(macos.split())
    testing_normalized = " ".join(testing.split())

    assert "returning exit code zero is not activation proof" in macos
    assert "Require a JSON" in macos
    assert "poll `dump policy`" in macos
    assert "activation is asynchronous" in macos
    assert "poll until both temporary entries are absent" in macos_normalized
    assert "`ConfigDirectoryPath`" in macos
    assert "basename without `.conf`" in macos
    assert "needs no" in macos and "registry edit" in macos
    assert 'config_dir="$(plutil -extract ConfigDirectoryPath raw' in macos
    assert 'config_name="$(plutil -extract SelectedConfigName raw' in macos
    assert 'profile_path="$config_dir/$config_name.conf"' in macos
    assert "Surge/Profiles/surge.conf" not in macos
    assert "official GitHub" in macos
    assert "local sing-box sidecar's own TCP" in macos
    assert "read udp 198.18.0.1:<port>" in macos
    assert "is local VIF path evidence" in macos_normalized
    assert "dedicated temporary `--user-data-dir`" in testing
    assert "explicit wall-clock deadline" in testing_normalized
    assert "browser startup or exit code alone is not protocol evidence" in testing_normalized
    assert "HTTP3_HEADERS_DECODED" in testing
    assert "HTTP3_DATA_FRAME_RECEIVED" in testing


def test_android_full_device_profile_has_a_tun_baseline():
    android = (ROOT / "references" / "android-client.md").read_text()
    normalized = " ".join(android.split())

    assert '"type": "tun"' in android
    assert '"auto_route": true' in android
    assert '"strict_route": true' in android
    assert "mixed inbound alone validates only explicit per-app proxy traffic" in normalized
