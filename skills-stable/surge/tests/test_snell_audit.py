from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "snell_audit.py"
PAYLOAD = ROOT / "scripts" / "payloads" / "snell_debian_payload.sh"
SKILL = ROOT / "SKILL.md"
TRIAGE = ROOT / "references" / "snell-vps-triage.md"
OPERATOR_ACTION_PATTERNS = ROOT / "references" / "snell-operator-action-patterns.md"
MACOS_TRIAGE = ROOT / "references" / "macos-network-triage.md"
MACOS_OPERATOR_ACTIONS = ROOT / "references" / "macos-surge-operator-actions.md"


def load_module():
    spec = importlib.util.spec_from_file_location("snell_audit", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_audit_fixture(tmp_path: Path, *, kv: dict[str, str], journal: str = "") -> Path:
    run_dir = tmp_path / "run"
    logs = run_dir / "logs"
    logs.mkdir(parents=True)
    (logs / "audit_summary.kv").write_text("\n".join(f"{key}={value}" for key, value in kv.items()) + "\n")
    (logs / "journal_recent.log").write_text(journal)
    for name in [
        "audit_raw.log",
        "service_cat.log",
        "listeners.log",
        "sshd_effective.log",
        "ufw_status.log",
        "nft_ruleset.log",
        "iptables_rules.log",
        "docker_ports.log",
    ]:
        (logs / name).write_text("")
    (run_dir / "stdout").write_text("")
    (run_dir / "stderr").write_text("")
    (run_dir / "exit_code").write_text("0\n")
    return run_dir


def base_kv(**overrides: str) -> dict[str, str]:
    values = {
        "snell_port": "14180",
        "snell_version_text": "snell-server v5.0.1",
        "snell_binary_path": "/usr/local/bin/snell-server",
        "snell_config_path": "/etc/snell/snell-server.conf",
        "config_present": "yes",
        "config_psk_present": "yes",
        "config_listen": "0.0.0.0:14180",
        "config_legacy_keys": "",
        "config_dns_ip_preference_present": "no",
        "systemd_active": "active",
        "systemd_sub": "running",
        "systemd_result": "success",
        "systemd_restart": "always",
        "systemd_user": "snell",
        "systemd_group": "snell",
        "systemd_main_pid": "1234",
        "systemd_nrestarts": "0",
        "systemd_limit_nofile": "1048576",
        "systemd_hardening_mentions": "0",
        "systemd_hardening_directives": "",
        "tcp_listen": "yes",
        "udp_listen": "yes",
        "ssh_permitrootlogin": "prohibit-password",
        "ssh_passwordauthentication": "no",
        "ssh_kbdinteractiveauthentication": "no",
        "ssh_pubkeyauthentication": "yes",
        "ssh_maxauthtries": "20",
        "ssh_authenticationmethods": "",
        "ssh_root_authorized_keys_count": "1",
        "ufw_status": "active",
        "ufw_snell_tcp": "yes",
        "ufw_snell_udp": "yes",
        "nft_ruleset_lines": "0",
        "iptables_rules_lines": "0",
        "ip6tables_rules_lines": "0",
        "docker_present": "no",
        "docker_published_ports_lines": "0",
        "sysctl_net_core_default_qdisc": "fq",
        "sysctl_net_ipv4_tcp_congestion_control": "bbr",
        "sysctl_net_core_somaxconn": "8192",
        "sysctl_net_ipv4_tcp_max_syn_backlog": "8192",
        "sysctl_net_ipv4_tcp_syncookies": "1",
        "sysctl_net_ipv4_ip_local_port_range": "10000 65001",
        "sysctl_net_ipv4_ip_local_reserved_ports": "14180",
        "sysctl_net_ipv4_tcp_mtu_probing": "0",
        "sysctl_net_netfilter_nf_conntrack_count": "10",
        "sysctl_net_netfilter_nf_conntrack_max": "65536",
        "mem_total_kib": "1048576",
        "swap_total_kib": "1048576",
        "swap_free_kib": "1048576",
        "fstab_swap_entries": "1",
        "root_available_kib": "1000000",
        "journald_disk_usage": "Archived and active journals take up 20.0M in the file system.",
    }
    values.update(overrides)
    return values


def finding_ids(pack: dict) -> set[str]:
    return {item["id"] for item in pack["findings"]}


def test_snell_major_ignores_timestamp_prefix():
    snell_audit = load_module()

    assert (
        snell_audit.snell_major_from_text(
            "2026-06-17 13:28:02.443716 [server_main] <NOTIFY> snell-server v6.0.0b3 (Jun 15 2026)"
        )
        == "6"
    )
    assert snell_audit.snell_major_from_text("snell-server v5.0.1") == "5"


def test_v5_udp_crash_is_high_issue(tmp_path: Path):
    snell_audit = load_module()
    journal = "\n".join(
        [
            "2026-06-13T00:00:01 host snell-server[1234]: UDP socket send error: invalid argument",
            "2026-06-13T00:00:02 host snell-server[1234]: uv_close: Assertion `0' failed",
            "2026-06-13T00:00:03 host systemd[1]: snell-server.service: Main process exited, signal 6",
        ]
    )
    run_dir = write_audit_fixture(tmp_path, kv=base_kv(), journal=journal)

    pack = snell_audit.build_evidence_pack(local_dir=run_dir, target="root@example", transport_status="ok")

    assert pack["status"] == "issue"
    assert "snell.v5.udp_crash" in finding_ids(pack)
    crash = next(item for item in pack["findings"] if item["id"] == "snell.v5.udp_crash")
    assert crash["severity"] == "high"
    assert crash["persistent_change"] is False


def test_tuning_and_noise_stay_in_facts_without_findings(tmp_path: Path):
    snell_audit = load_module()
    journal = "\n".join(
        [
            "2026-06-13T00:00:01 host snell-server[1234]: Decryption failed from 198.51.100.10",
            "2026-06-13T00:00:02 host snell-server[1234]: Decryption failed from 198.51.100.10",
        ]
    )
    kv = base_kv(
        sysctl_net_ipv4_tcp_congestion_control="cubic",
        sysctl_net_core_somaxconn="128",
        systemd_limit_nofile="1024",
        swap_total_kib="0",
        mem_total_kib="1048576",
    )
    run_dir = write_audit_fixture(tmp_path, kv=kv, journal=journal)

    pack = snell_audit.build_evidence_pack(local_dir=run_dir, target="root@example", transport_status="ok")

    assert pack["status"] == "ok"
    assert pack["findings"] == []
    facts = pack["facts"]
    assert facts["logs"]["decryption_failed_count"] == 2
    assert facts["logs"]["top_decryption"] == "2:198.51.100.10"
    assert facts["sysctl"]["tcp_congestion_control"] == "cubic"
    assert facts["sysctl"]["somaxconn"] == 128
    assert facts["systemd"]["limit_nofile"] == 1024
    assert facts["swap"]["swap_total_kib"] == 0


def test_v6_udp_and_legacy_config_are_version_aware(tmp_path: Path):
    snell_audit = load_module()
    run_dir = write_audit_fixture(
        tmp_path,
        kv=base_kv(
            snell_version_text="snell-server v6.0.0b1",
            config_legacy_keys="ipv6,obfs,reuse",
            udp_listen="yes",
            ufw_snell_udp="yes",
        ),
    )

    pack = snell_audit.build_evidence_pack(local_dir=run_dir, target="root@example", transport_status="ok")

    ids = finding_ids(pack)
    assert pack["status"] == "warn"
    assert "snell.v6.udp_listener_present" in ids
    assert "snell.v6.udp_firewall_exposed" in ids
    assert "snell.v6.legacy_config_keys" in ids
    assert "snell.v5.udp_crash" not in ids


def test_audit_snell_dry_run_plans_without_connecting(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    snell_audit = load_module()

    def boom(*_args, **_kwargs):
        raise AssertionError("dry-run must not touch the host")

    monkeypatch.setattr(snell_audit, "run_audit_for_host", boom)
    monkeypatch.setattr(snell_audit, "run_subprocess", boom)
    args = argparse.Namespace(
        host="root@203.0.113.10",
        port=9999,
        out=tmp_path,
        remote_base="/var/tmp/surge-snell-runs",
        ssh_option=[],
        dry_run=True,
    )

    rc = snell_audit.command_audit_snell(args)

    assert rc == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["dry_run"] is True
    assert plan["target"] == "root@203.0.113.10"
    assert len(plan["commands"]) == 5
    assert any("rm -rf" in cmd for cmd in plan["commands"])


def test_audit_fleet_continues_after_issue(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    snell_audit = load_module()
    hosts = tmp_path / "hosts.txt"
    hosts.write_text("root@one\nroot@two\n")
    calls: list[str] = []

    def fake_run(args: argparse.Namespace, host: str):
        calls.append(host)
        status = "issue" if host == "root@one" else "ok"
        return {
            "schema_version": 2,
            "operation": "audit-snell",
            "target": host,
            "transport_status": "ok",
            "status": status,
            "facts": {},
            "findings": [],
            "evidence_paths": {},
            "recommended_manual_actions": [],
            "persistent_effects": [],
        }, 0

    monkeypatch.setattr(snell_audit, "run_audit_for_host", fake_run)
    args = argparse.Namespace(hosts=hosts, fail_on_issue=False)

    rc = snell_audit.command_audit_fleet(args)

    assert rc == 0
    assert calls == ["root@one", "root@two"]
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "issue"
    assert output["host_count"] == 2


def test_audit_fleet_fail_on_issue(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    snell_audit = load_module()
    hosts = tmp_path / "hosts.txt"
    hosts.write_text("root@one\n")

    def fake_run(args: argparse.Namespace, host: str):
        return {
            "schema_version": 2,
            "operation": "audit-snell",
            "target": host,
            "transport_status": "ok",
            "status": "issue",
            "facts": {},
            "findings": [],
            "evidence_paths": {},
            "recommended_manual_actions": [],
            "persistent_effects": [],
        }, 0

    monkeypatch.setattr(snell_audit, "run_audit_for_host", fake_run)
    args = argparse.Namespace(hosts=hosts, fail_on_issue=True)

    assert snell_audit.command_audit_fleet(args) == 1


def test_single_audit_issue_exits_zero_without_fail_on_issue(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    snell_audit = load_module()
    local_dir = tmp_path / "run"
    local_dir.mkdir()
    manifest = {"target": "root@example", "remote_dir": "/var/tmp/surge-snell-runs/test-run"}
    completed = subprocess.CompletedProcess(["true"], 0, "", "")

    monkeypatch.setattr(snell_audit, "prepare_audit_run", lambda args, host: (local_dir, manifest))
    monkeypatch.setattr(snell_audit, "upload_audit_run", lambda local_dir, manifest, args: completed)
    monkeypatch.setattr(snell_audit, "run_remote_audit", lambda manifest, args: completed)
    monkeypatch.setattr(snell_audit, "collect_audit_run", lambda local_dir, manifest, args: completed)
    monkeypatch.setattr(snell_audit, "cleanup_remote_audit_run", lambda manifest, args: completed)
    monkeypatch.setattr(
        snell_audit,
        "build_evidence_pack",
        lambda **kwargs: {
            "schema_version": 2,
            "operation": "audit-snell",
            "target": "root@example",
            "transport_status": "ok",
            "status": "issue",
            "facts": {},
            "findings": [],
            "evidence_paths": {},
            "recommended_manual_actions": [],
            "persistent_effects": [],
        },
    )
    args = argparse.Namespace(port=14180, fail_on_issue=False)

    pack, rc = snell_audit.run_audit_for_host(args, "root@example")

    assert pack["status"] == "issue"
    assert rc == 0


def test_single_audit_issue_respects_fail_on_issue(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    snell_audit = load_module()
    local_dir = tmp_path / "run"
    local_dir.mkdir()
    manifest = {"target": "root@example", "remote_dir": "/var/tmp/surge-snell-runs/test-run"}
    completed = subprocess.CompletedProcess(["true"], 0, "", "")

    monkeypatch.setattr(snell_audit, "prepare_audit_run", lambda args, host: (local_dir, manifest))
    monkeypatch.setattr(snell_audit, "upload_audit_run", lambda local_dir, manifest, args: completed)
    monkeypatch.setattr(snell_audit, "run_remote_audit", lambda manifest, args: completed)
    monkeypatch.setattr(snell_audit, "collect_audit_run", lambda local_dir, manifest, args: completed)
    monkeypatch.setattr(snell_audit, "cleanup_remote_audit_run", lambda manifest, args: completed)
    monkeypatch.setattr(
        snell_audit,
        "build_evidence_pack",
        lambda **kwargs: {
            "schema_version": 2,
            "operation": "audit-snell",
            "target": "root@example",
            "transport_status": "ok",
            "status": "issue",
            "facts": {},
            "findings": [],
            "evidence_paths": {},
            "recommended_manual_actions": [],
            "persistent_effects": [],
        },
    )
    args = argparse.Namespace(port=14180, fail_on_issue=True)

    _, rc = snell_audit.run_audit_for_host(args, "root@example")

    assert rc == 1


def test_single_audit_cleanup_failure_records_remote_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    snell_audit = load_module()
    local_dir = tmp_path / "run"
    local_dir.mkdir()
    manifest = {"target": "root@example", "remote_dir": "/var/tmp/surge-snell-runs/test-run"}
    completed = subprocess.CompletedProcess(["true"], 0, "", "")
    cleanup_failed = subprocess.CompletedProcess(["ssh"], 255, "", "cleanup failed")

    monkeypatch.setattr(snell_audit, "prepare_audit_run", lambda args, host: (local_dir, manifest))
    monkeypatch.setattr(snell_audit, "upload_audit_run", lambda local_dir, manifest, args: completed)
    monkeypatch.setattr(snell_audit, "run_remote_audit", lambda manifest, args: completed)
    monkeypatch.setattr(snell_audit, "collect_audit_run", lambda local_dir, manifest, args: completed)
    monkeypatch.setattr(snell_audit, "cleanup_remote_audit_run", lambda manifest, args: cleanup_failed)
    monkeypatch.setattr(
        snell_audit,
        "build_evidence_pack",
        lambda **kwargs: {
            "schema_version": 2,
            "operation": "audit-snell",
            "target": kwargs["target"],
            "transport_status": kwargs["transport_status"],
            "status": "ok",
            "facts": {},
            "findings": [],
            "evidence_paths": {},
            "recommended_manual_actions": [],
            "persistent_effects": kwargs.get("persistent_effects") or [],
        },
    )
    args = argparse.Namespace(port=14180, fail_on_issue=False)

    pack, rc = snell_audit.run_audit_for_host(args, "root@example")

    assert rc == 0
    assert pack["persistent_effects"] == ["remote audit directory may remain: /var/tmp/surge-snell-runs/test-run"]


def test_single_audit_transport_failure_exits_nonzero(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    snell_audit = load_module()
    local_dir = tmp_path / "run"
    local_dir.mkdir()
    manifest = {"target": "root@example", "remote_dir": "/var/tmp/surge-snell-runs/test-run"}
    failed = subprocess.CompletedProcess(["ssh"], 255, "", "ssh failed")

    monkeypatch.setattr(snell_audit, "prepare_audit_run", lambda args, host: (local_dir, manifest))
    monkeypatch.setattr(snell_audit, "upload_audit_run", lambda local_dir, manifest, args: failed)
    args = argparse.Namespace(port=14180, fail_on_issue=False)

    pack, rc = snell_audit.run_audit_for_host(args, "root@example")

    assert rc == 255
    assert pack["transport_status"] == "failed"
    assert "transport.audit_failed" in finding_ids(pack)


def test_surge_probe_empty_json_fails(tmp_path: Path):
    snell_audit = load_module()
    fake_cli = tmp_path / "surge-cli"
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    fake_cli.write_text("#!/usr/bin/env bash\nprintf '{}\\n'\n")
    fake_cli.chmod(0o755)

    result = snell_audit.run_surge_probe(
        surge_cli=str(fake_cli),
        policy="missing-policy",
        test_name="tcp",
        logs_dir=logs_dir,
        timeout=5,
    )

    assert result["status"] == "failed"
    assert result["json_ok"] is True


def test_smoke_surge_unsupported_is_warn(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    snell_audit = load_module()

    monkeypatch.setattr(snell_audit, "resolve_surge_cli", lambda configured: "/tmp/fake-surge-cli")
    monkeypatch.setattr(
        snell_audit,
        "run_surge_probe",
        lambda **kwargs: {
            "test": kwargs["test_name"],
            "status": "unsupported",
            "return_code": 1,
            "timed_out": False,
            "json_ok": False,
            "stdout_file": "",
            "stderr_file": "",
            "parsed": None,
        },
    )
    args = argparse.Namespace(
        policy="policy",
        test=["nat"],
        run_id="smoke-test-0001",
        out=tmp_path,
        overwrite=False,
        surge_cli=None,
        host_ip=None,
        probe_timeout=5,
    )

    rc = snell_audit.command_smoke_surge(args)
    output = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert output["status"] == "warn"
    assert output["results"][0]["status"] == "unsupported"


def test_payload_redacts_psk_from_raw_log(tmp_path: Path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    config = tmp_path / "snell-server.conf"
    binary = tmp_path / "snell-server"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    secret = "super-secret-psk"
    config.write_text(f"[snell-server]\nlisten = 0.0.0.0:14180\npsk = {secret}\n")
    binary.write_text("#!/usr/bin/env bash\nprintf 'snell-server v5.0.1\\n'\n")
    binary.chmod(0o755)
    (run_dir / "input.env").write_text("SNELL_AUDIT_OPERATION=audit-snell\nSNELL_PORT=14180\n")

    fake_systemctl = fake_bin / "systemctl"
    fake_systemctl.write_text(
        "#!/usr/bin/env bash\n"
        'if [ "$1" = cat ]; then\n'
        f"  printf '[Service]\\nExecStart={binary} -c {config}\\n'\n"
        "  exit 0\n"
        "fi\n"
        'if [ "$1" = show ]; then\n'
        "  prop=''\n"
        '  for arg in "$@"; do case "$arg" in ActiveState|SubState|Result|NRestarts|LimitNOFILE|User|Group|Restart|MainPID) prop="$arg";; esac; done\n'
        "  case \"$prop\" in ActiveState) echo active;; SubState) echo running;; Result) echo success;; NRestarts) echo 0;; LimitNOFILE) echo 1048576;; User) echo snell;; Group) echo snell;; Restart) echo always;; MainPID) echo 1234;; *) echo '';; esac\n"
        "  exit 0\n"
        "fi\n"
        'if [ "$1" = is-enabled ]; then echo enabled; exit 0; fi\n'
    )
    fake_systemctl.chmod(0o755)
    (fake_bin / "ss").write_text(
        "#!/usr/bin/env bash\nprintf 'tcp LISTEN 0 128 0.0.0.0:14180 0.0.0.0:* users:((\"snell-server\",pid=1234,fd=3))\\n'\n"
    )
    (fake_bin / "journalctl").write_text(
        "#!/usr/bin/env bash\nif [ \"$1\" = --disk-usage ]; then echo 'Archived and active journals take up 1.0M.'; fi\n"
    )
    (fake_bin / "sysctl").write_text(
        '#!/usr/bin/env bash\ncase "$2" in net.core.default_qdisc) echo fq;; net.ipv4.tcp_congestion_control) echo bbr;; *) echo 0;; esac\n'
    )
    (fake_bin / "sshd").write_text(
        "#!/usr/bin/env bash\nprintf 'permitrootlogin prohibit-password\\npasswordauthentication no\\nkbdinteractiveauthentication no\\npubkeyauthentication yes\\nmaxauthtries 20\\n'\n"
    )
    (fake_bin / "ufw").write_text("#!/usr/bin/env bash\nprintf 'Status: active\\n14180/tcp ALLOW Anywhere\\n'\n")
    (fake_bin / "nft").write_text("#!/usr/bin/env bash\ntrue\n")
    for name in ["ss", "journalctl", "sysctl", "sshd", "ufw", "nft"]:
        (fake_bin / name).chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    result = subprocess.run(["bash", str(PAYLOAD)], cwd=run_dir, env=env, text=True, capture_output=True, check=False)

    assert result.returncode == 0, result.stderr
    raw_log = (run_dir / "logs" / "audit_raw.log").read_text()
    assert secret not in raw_log
    assert "psk = <redacted>" in raw_log


def test_skill_docs_default_to_read_only_audit():
    combined = "\n".join([SKILL.read_text(), TRIAGE.read_text(), OPERATOR_ACTION_PATTERNS.read_text()])

    # Anchor on read-only intent semantically, not on exact prose, so a doc
    # rewrite that keeps the meaning does not silently break this test.
    assert "read-only collection commands over SSH" in combined
    assert "do not apply them during diagnosis" in combined
    assert "human operator" in combined
    assert "audit-snell" in combined
    assert "audit-fleet" in combined
    # The SKILL description must be honest that a server-side temp dir is touched.
    skill = SKILL.read_text()
    assert "never changes local network settings or server configuration" in skill
    assert "create and delete a temporary evidence directory" in skill
    # No execution / persistence verbs leaked back in.
    assert "install-snell" not in combined
    assert "confirm-persistent" not in combined


def test_macos_triage_keeps_write_actions_in_operator_reference():
    triage_text = MACOS_TRIAGE.read_text()
    operator_text = MACOS_OPERATOR_ACTIONS.read_text()

    assert "xh POST" not in triage_text
    assert "export http_proxy" not in triage_text
    assert "unset http_proxy" not in triage_text
    assert "xh --verify no POST" in operator_text
    assert "export http_proxy" in operator_text
