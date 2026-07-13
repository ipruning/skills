from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_server_external_targets_require_explicit_source_authorization():
    server = (ROOT / "references" / "server.md").read_text()

    assert "必须逐项由用户指定" in server
    assert "明确授权 Agent" in server
    assert "缺少来源授权时停止并询问" in server
    assert "DNS_RESOLVER_IP" in server
    assert '@"$DNS_RESOLVER_IP"' in server


def test_one_shot_monitor_rejects_existing_listener_and_ties_readiness_to_pid():
    monitoring = (ROOT / "references" / "monitoring.md").read_text()

    assert "local monitor port 2089 is already owned" in monitoring
    assert 'grep -Fq "pid=$sidecar_pid,"' in monitoring
    assert "sidecar_listening && break" in monitoring
    assert "DNS_RESOLVER_IP" in monitoring
    assert "EGRESS_ECHO_URL" in monitoring
    assert "does not implicitly authorize third-party DNS or IP echo services" in monitoring


def test_linux_validation_fails_closed_for_journal_and_old_proxy_units():
    linux = (ROOT / "references" / "linux-client.md").read_text()

    assert 'if ! recent_log="$(journalctl' in linux
    assert "cannot read the bounded sing-box journal" in linux
    assert 'test -n "$validation_log"' in linux
    assert "missing VLESS packet evidence" in linux
    assert linux.index("restore durable log level to `warn`") < linux.index("Complete steady-state validation")
    assert "systemctl --user list-unit-files" in linux
    assert "enabled system proxy unit or unreadable system unit inventory" in linux
    assert "enabled user proxy unit or unreadable user unit inventory" in linux
    assert 'if ! system_running="$(systemctl list-units' in linux
    assert 'if ! user_running="$(systemctl --user list-units' in linux
    assert "pgrep_code=$?" in linux
    assert 'if ! socket_inventory="$(ss -lntup)"' in linux
    assert "rg_code=$?" in linux
    assert "user-level cleanup remains unverified" in linux
