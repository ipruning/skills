from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shlex
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "snell_audit.py"
PAYLOAD = ROOT / "scripts" / "payloads" / "snell_debian_payload.sh"
SKILL = ROOT / "SKILL.md"
TRIAGE = ROOT / "references" / "snell" / "audit.md"
SERVER = ROOT / "references" / "snell" / "deploy.md"
TUNING = ROOT / "references" / "snell" / "tuning.md"
CREDENTIALS = ROOT / "references" / "snell" / "credentials.md"
TEST_PORT = 24680
ALT_TEST_PORT = 24681
TEST_SOURCE_IP = "192.0.2.10"


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
        "snell_port": str(TEST_PORT),
        "snell_version_text": "snell-server v5.0.1",
        "snell_binary_path": "/usr/local/bin/snell-server",
        "snell_binary_sha256": "a" * 64,
        "snell_config_path": "/etc/snell/snell-server.conf",
        "snell_service_name": "snell-server.service",
        "config_present": "yes",
        "config_owner_user": "root",
        "config_owner_group": "snell",
        "config_mode": "640",
        "config_service_readable": "yes",
        "config_service_writable": "no",
        "config_parent_path": "/etc/snell",
        "config_parent_owner_user": "root",
        "config_parent_owner_group": "snell",
        "config_parent_mode": "750",
        "config_parent_service_writable": "no",
        "config_psk_present": "yes",
        "config_listen": f"0.0.0.0:{TEST_PORT}",
        "config_legacy_keys": "",
        "config_dns_ip_preference_present": "no",
        "config_dns_ip_preference": "",
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
        "sysctl_net_ipv4_ip_local_reserved_ports": str(TEST_PORT),
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


def finding_ids(pack: dict[str, Any]) -> set[str]:
    return {item["id"] for item in pack["findings"]}


def test_validate_host_rejects_option_looking_values():
    snell_audit = load_module()

    assert snell_audit.validate_host("operator@node.example.invalid") == "operator@node.example.invalid"
    # A leading "-" would be parsed by ssh/scp as an option (e.g. ProxyCommand
    # injection from an untrusted hosts file), not as a destination.
    with pytest.raises(snell_audit.CliError):
        snell_audit.validate_host("-oProxyCommand=evil")
    with pytest.raises(snell_audit.CliError):
        snell_audit.validate_host("-v")


def test_fleet_run_id_keeps_distinct_host_suffix(tmp_path: Path):
    snell_audit = load_module()

    # A user run-id near the 80-char cap must not truncate the host suffix and
    # collapse two hosts onto the same run dir.
    long_prefix = "weekly-fleet-audit-" + "x" * 60
    run_ids = set()
    for host in ("operator@node-a.example.invalid", "operator@node-b.example.invalid"):
        args = argparse.Namespace(
            run_id=long_prefix,
            command="audit-fleet",
            out=tmp_path,
            remote_base="/var/tmp/surge-snell-runs",
            service="",
            overwrite=False,
            journal_since="10 min ago",
            port=TEST_PORT,
        )
        local_dir, _ = snell_audit.prepare_audit_run(args, host)
        run_ids.add(local_dir.name)
        assert len(local_dir.name) <= snell_audit.RUN_ID_MAX_LEN
        snell_audit.validate_run_id(local_dir.name)
        for name in ("manifest.json", "input.json"):
            assert json.loads((local_dir / name).read_text())["schema_version"] == "surge-snell.audit-run.v2"
    assert len(run_ids) == 2


def test_snell_major_ignores_timestamp_prefix():
    snell_audit = load_module()

    assert (
        snell_audit.snell_major_from_text("2000-01-01 00:00:00.000000 [server_main] <NOTIFY> snell-server v6.0.0-test")
        == "6"
    )
    assert snell_audit.snell_major_from_text("snell-server v5.0.1") == "5"


def test_v5_udp_crash_is_high_issue(tmp_path: Path):
    snell_audit = load_module()
    journal = "\n".join([
        "2000-01-01T00:00:01 host snell-server[1234]: UDP socket send error: invalid argument",
        "2000-01-01T00:00:02 host snell-server[1234]: uv_close: Assertion `0' failed",
        "2000-01-01T00:00:03 host systemd[1]: snell-server.service: Main process exited, signal 6",
    ])
    run_dir = write_audit_fixture(tmp_path, kv=base_kv(), journal=journal)

    pack = snell_audit.build_evidence_pack(local_dir=run_dir, target="root@example", transport_status="ok")

    assert pack["status"] == "issue"
    assert "snell.v5.udp_crash" in finding_ids(pack)
    crash = next(item for item in pack["findings"] if item["id"] == "snell.v5.udp_crash")
    assert crash["severity"] == "high"
    assert crash["persistent_change"] is False


def test_tuning_and_noise_stay_in_facts_without_findings(tmp_path: Path):
    snell_audit = load_module()
    journal = "\n".join([
        f"2000-01-01T00:00:01 host snell-server[1234]: Decryption failed from {TEST_SOURCE_IP}",
        f"2000-01-01T00:00:02 host snell-server[1234]: Decryption failed from {TEST_SOURCE_IP}",
    ])
    kv = base_kv(
        sysctl_net_ipv4_tcp_congestion_control="cubic",
        sysctl_net_core_somaxconn="128",
        systemd_limit_nofile="1024",
        swap_total_kib="0",
        mem_total_kib="1048576",
    )
    run_dir = write_audit_fixture(tmp_path, kv=kv, journal=journal)

    pack = snell_audit.build_evidence_pack(local_dir=run_dir, target="root@example", transport_status="ok")

    assert pack["schema_version"] == 2
    assert pack["status"] == "ok"
    assert pack["findings"] == []
    facts = pack["facts"]
    assert facts["logs"]["decryption_failed_count"] == 2
    assert facts["logs"]["top_decryption"] == f"2:{TEST_SOURCE_IP}"
    assert facts["sysctl"]["tcp_congestion_control"] == "cubic"
    assert facts["sysctl"]["somaxconn"] == 128
    assert facts["systemd"]["limit_nofile"] == 1024
    assert facts["swap"]["swap_total_kib"] == 0


@pytest.mark.parametrize(
    ("overrides", "expected_finding"),
    [
        ({"systemd_user": "", "systemd_group": ""}, "snell.service_identity_mismatch"),
        (
            {"config_owner_user": "root", "config_owner_group": "root", "config_mode": "644"},
            "snell.config_permissions_mismatch",
        ),
        ({"config_owner_user": "snell", "config_mode": "600"}, "snell.config_permissions_mismatch"),
        ({"config_service_writable": "yes"}, "snell.config_permissions_mismatch"),
        ({"config_parent_service_writable": "yes"}, "snell.config_permissions_mismatch"),
    ],
)
def test_insecure_service_identity_or_config_permissions_are_findings(
    tmp_path: Path, overrides: dict[str, str], expected_finding: str
):
    snell_audit = load_module()
    run_dir = write_audit_fixture(tmp_path, kv=base_kv(**overrides))

    pack = snell_audit.build_evidence_pack(local_dir=run_dir, target="root@example", transport_status="ok")

    assert pack["status"] == "warn"
    assert expected_finding in finding_ids(pack)


def test_non_root_identity_and_root_owned_group_readable_config_are_valid(tmp_path: Path):
    snell_audit = load_module()
    run_dir = write_audit_fixture(
        tmp_path,
        kv=base_kv(
            systemd_user="svc-snell",
            systemd_group="",
            config_owner_user="root",
            config_owner_group="svc-snell",
            config_mode="640",
            config_service_readable="yes",
            config_service_writable="no",
            config_parent_service_writable="no",
        ),
    )

    pack = snell_audit.build_evidence_pack(local_dir=run_dir, target="root@example", transport_status="ok")

    assert pack["status"] == "ok"
    assert pack["findings"] == []


def test_root_service_reports_identity_without_restating_config_permissions(tmp_path: Path):
    snell_audit = load_module()
    run_dir = write_audit_fixture(
        tmp_path,
        kv=base_kv(
            systemd_user="root",
            systemd_group="root",
            config_owner_user="root",
            config_owner_group="root",
            config_mode="600",
            config_service_readable="yes",
            config_service_writable="yes",
            config_parent_owner_group="root",
            config_parent_mode="700",
            config_parent_service_writable="yes",
        ),
    )

    pack = snell_audit.build_evidence_pack(local_dir=run_dir, target="root@example", transport_status="ok")

    assert "snell.service_identity_mismatch" in finding_ids(pack)
    assert "snell.config_permissions_mismatch" not in finding_ids(pack)


def test_root_service_with_loose_config_mode_still_reports_permissions(tmp_path: Path):
    snell_audit = load_module()
    run_dir = write_audit_fixture(
        tmp_path,
        kv=base_kv(
            systemd_user="root",
            systemd_group="root",
            config_owner_user="root",
            config_owner_group="root",
            config_mode="644",
            config_service_readable="yes",
            config_service_writable="yes",
            config_parent_owner_group="root",
            config_parent_mode="700",
            config_parent_service_writable="yes",
        ),
    )

    pack = snell_audit.build_evidence_pack(local_dir=run_dir, target="root@example", transport_status="ok")

    assert "snell.service_identity_mismatch" in finding_ids(pack)
    assert "snell.config_permissions_mismatch" in finding_ids(pack)


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


def test_binary_digest_and_dns_preference_values_are_enforced(tmp_path: Path):
    snell_audit = load_module()
    expected_digest = "b" * 64
    run_dir = write_audit_fixture(
        tmp_path,
        kv=base_kv(
            snell_version_text="snell-server v6.0.0",
            config_dns_ip_preference_present="yes",
            config_dns_ip_preference="ipv4_only",
        ),
    )

    pack = snell_audit.build_evidence_pack(
        local_dir=run_dir,
        target="root@example",
        transport_status="ok",
        expected_binary_sha256=expected_digest,
    )

    assert pack["facts"]["snell"]["binary_sha256"] == "a" * 64
    assert pack["facts"]["snell"]["expected_binary_sha256"] == expected_digest
    assert pack["facts"]["snell"]["config"]["dns_ip_preference"] == "ipv4_only"
    assert "snell.binary_digest_mismatch" in finding_ids(pack)
    assert "snell.invalid_dns_ip_preference" in finding_ids(pack)
    assert pack["status"] == "issue"


@pytest.mark.parametrize(
    "value",
    ["default", "prefer-ipv4", "prefer-ipv6", "ipv4-only", "ipv6-only"],
)
def test_documented_dns_ip_preference_values_are_valid(tmp_path: Path, value: str):
    snell_audit = load_module()
    run_dir = write_audit_fixture(
        tmp_path,
        kv=base_kv(config_dns_ip_preference_present="yes", config_dns_ip_preference=value),
    )

    pack = snell_audit.build_evidence_pack(local_dir=run_dir, target="root@example", transport_status="ok")

    assert "snell.invalid_dns_ip_preference" not in finding_ids(pack)


def test_audit_snell_dry_run_plans_without_connecting(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    snell_audit = load_module()

    def boom(*_args, **_kwargs):
        raise AssertionError("dry-run must not touch the host")

    monkeypatch.setattr(snell_audit, "run_audit_for_host", boom)
    monkeypatch.setattr(snell_audit, "run_subprocess", boom)
    args = argparse.Namespace(
        host="operator@node.example.invalid",
        port=9999,
        service="",
        out=tmp_path,
        remote_base="/var/tmp/snell-runs",
        ssh_option=[],
        sudo=True,
        dry_run=True,
    )

    rc = snell_audit.command_audit_snell(args)

    assert rc == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["dry_run"] is True
    assert plan["target"] == "operator@node.example.invalid"
    assert plan["service"] == "auto-discover unique *snell*.service"
    assert len(plan["commands"]) == 5
    assert "ownership-nonce" in plan["commands"][0]
    assert "ownership-nonce" in plan["commands"][-1]
    prepare_args = shlex.split(plan["commands"][0].replace("<run-id>", "test-run"))
    assert prepare_args[-2] == "operator@node.example.invalid"
    assert "sudo -n test -d /var/tmp/snell-runs" in prepare_args[-1]
    assert "sudo -n mkdir -m 711" not in prepare_args[-1]
    assert "sudo -n mkdir -m 700" in prepare_args[-1]
    assert "/var/tmp/snell-runs/test-run" in prepare_args[-1]


def test_sudo_transport_is_noninteractive_and_returns_evidence_ownership(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    snell_audit = load_module()
    calls: list[list[str]] = []

    def fake_transport(command: list[str], *, timeout: int | None = None):
        del timeout
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(snell_audit, "run_transport_step", fake_transport)
    manifest = {
        "target": "operator@node.example.invalid",
        "remote_dir": "/var/tmp/surge-snell-runs/test-sudo-run",
        "ownership_nonce": "test-nonce",
    }
    args = argparse.Namespace(ssh_option=[], timeout=30, sudo=True)

    snell_audit.upload_audit_run(tmp_path, manifest, args)
    snell_audit.run_remote_audit(manifest, args)
    snell_audit.cleanup_remote_audit_run(manifest, args)

    prepare_command = calls[0][-1]
    assert "sudo -n mkdir -p" not in prepare_command
    assert "sudo -n mkdir -m 700 /var/tmp/surge-snell-runs/test-sudo-run" in prepare_command
    assert "sudo -n tee /var/tmp/surge-snell-runs/test-sudo-run/.snell-audit-owner" in prepare_command
    assert "sudo -n chown -R" in prepare_command
    assert "then sudo -n rm -rf" in prepare_command
    assert "sudo -n env" in calls[2][-1]
    assert "RUN_OWNER_UID" in calls[2][-1]
    assert "chown -R" in calls[2][-1]
    assert ".snell-audit-owner" in calls[3][-1]
    assert "sudo -n cat --" in calls[3][-1]
    assert 'test "$marker" = test-nonce' in calls[3][-1]
    assert "sudo -n rm -rf --" in calls[3][-1]


def test_remote_marker_commands_preserve_collisions_and_mismatches(tmp_path: Path):
    snell_audit = load_module()
    remote_dir = tmp_path / "remote-base" / "run"
    remote_dir.parent.mkdir()
    parent_sentinel = remote_dir.parent / "existing-evidence"
    parent_sentinel.write_text("keep parent contents")
    owner_nonce = "owner-nonce"

    prepare = snell_audit.remote_prepare_command(str(remote_dir), owner_nonce, sudo=False)
    assert subprocess.run(["bash", "-c", prepare], check=False).returncode == 0
    assert (remote_dir / ".snell-audit-owner").read_text() == f"{owner_nonce}\n"

    sentinel = remote_dir / "sentinel"
    sentinel.write_text("keep")
    collision = snell_audit.remote_prepare_command(str(remote_dir), "other-run", sudo=False)
    assert subprocess.run(["bash", "-c", collision], check=False).returncode != 0
    assert sentinel.read_text() == "keep"

    wrong_cleanup = snell_audit.remote_cleanup_command(str(remote_dir), "other-run", sudo=False)
    assert subprocess.run(["bash", "-c", wrong_cleanup], check=False).returncode != 0
    assert sentinel.read_text() == "keep"

    owner_cleanup = snell_audit.remote_cleanup_command(str(remote_dir), owner_nonce, sudo=False)
    assert subprocess.run(["bash", "-c", owner_cleanup], check=False).returncode == 0
    assert not remote_dir.exists()
    assert parent_sentinel.read_text() == "keep parent contents"


@pytest.mark.parametrize("sudo", [False, True])
def test_prepare_refuses_missing_parent_without_leaving_directories(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, sudo: bool
):
    snell_audit = load_module()
    if sudo:
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        fake_sudo = bin_dir / "sudo"
        fake_sudo.write_text('#!/bin/sh\ntest "${1:-}" != -n || shift\nexec "$@"\n')
        fake_sudo.chmod(0o755)
        monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    parent = tmp_path / "missing-parent"
    command = snell_audit.remote_prepare_command(str(parent / "run"), "test-nonce", sudo=sudo)

    result = subprocess.run(["bash", "-c", command], check=False, capture_output=True, text=True)
    assert result.returncode != 0
    assert "remote base" in result.stderr
    assert str(parent) in result.stderr
    assert not result.stdout
    assert not parent.exists()


def test_sudo_prepare_preserves_existing_parent_mode(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    snell_audit = load_module()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_sudo = bin_dir / "sudo"
    fake_sudo.write_text('#!/bin/sh\ntest "${1:-}" != -n || shift\nexec "$@"\n')
    fake_sudo.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")

    parent = tmp_path / "restricted-parent"
    parent.mkdir(mode=0o700)
    remote_dir = parent / "run"
    command = snell_audit.remote_prepare_command(str(remote_dir), "test-nonce", sudo=True)

    assert subprocess.run(["bash", "-c", command], check=False).returncode == 0
    assert parent.stat().st_mode & 0o777 == 0o700
    assert remote_dir.stat().st_mode & 0o777 == 0o700

    cleanup = snell_audit.remote_cleanup_command(str(remote_dir), "test-nonce", sudo=True)
    assert subprocess.run(["bash", "-c", cleanup], check=False).returncode == 0
    assert not remote_dir.exists()
    assert parent.stat().st_mode & 0o777 == 0o700


def test_parser_does_not_guess_endpoint_port():
    snell_audit = load_module()

    args = snell_audit.build_parser().parse_args(["audit-snell", "--host", "root@example"])

    assert args.out == Path("/tmp/surge-snell-runs")
    assert args.remote_base == "/var/tmp"
    assert args.service == ""
    assert args.port is None
    with pytest.raises(snell_audit.CliError, match="--port is required"):
        snell_audit.validate_port(args.port)
    assert snell_audit.RUN_SCHEMA_VERSION == "surge-snell.audit-run.v2"


def test_fleet_requires_port_from_command_or_target(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    snell_audit = load_module()
    json_hosts = tmp_path / "hosts.jsonl"
    json_hosts.write_text(json.dumps({"host": "node.example.invalid", "port": TEST_PORT}) + "\n")
    json_args = snell_audit.build_parser().parse_args(["audit-fleet", "--hosts", str(json_hosts), "--dry-run"])

    assert snell_audit.command_audit_fleet(json_args) == 0
    assert json.loads(capsys.readouterr().out)["hosts"][0]["port"] == TEST_PORT

    plain_hosts = tmp_path / "hosts.txt"
    plain_hosts.write_text("node.example.invalid\n")
    plain_args = snell_audit.build_parser().parse_args(["audit-fleet", "--hosts", str(plain_hosts), "--dry-run"])
    with pytest.raises(snell_audit.CliError, match="--port is required"):
        snell_audit.command_audit_fleet(plain_args)


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


def test_audit_fleet_applies_json_line_target_overrides(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    snell_audit = load_module()
    hosts = tmp_path / "hosts.jsonl"
    expected_digest = "c" * 64
    hosts.write_text(
        "root@one\n"
        + json.dumps({
            "host": "node-two.example.invalid",
            "port": ALT_TEST_PORT,
            "service": "snell-server.service",
            "expected_sha256": expected_digest,
            "sudo": True,
            "ssh_options": ["ControlMaster=auto", "ConnectTimeout=20"],
        })
        + "\n"
    )
    calls: list[tuple[str, int, str, str, bool, list[str]]] = []

    def fake_run(args: argparse.Namespace, host: str):
        calls.append((host, args.port, args.service, args.expected_sha256, args.sudo, args.ssh_option))
        return {
            "schema_version": 2,
            "operation": "audit-snell",
            "target": host,
            "transport_status": "ok",
            "status": "ok",
            "facts": {},
            "findings": [],
            "evidence_paths": {},
            "recommended_manual_actions": [],
            "persistent_effects": [],
        }, 0

    monkeypatch.setattr(snell_audit, "run_audit_for_host", fake_run)
    args = argparse.Namespace(
        hosts=hosts,
        fail_on_issue=False,
        port=TEST_PORT,
        service="",
        expected_sha256="",
        sudo=False,
        ssh_option=["ControlMaster=no", "ConnectTimeout=30"],
    )

    assert snell_audit.command_audit_fleet(args) == 0
    assert calls == [
        ("root@one", TEST_PORT, "", "", False, ["ControlMaster=no", "ConnectTimeout=30"]),
        (
            "node-two.example.invalid",
            ALT_TEST_PORT,
            "snell-server.service",
            expected_digest,
            True,
            ["ControlMaster=auto", "ConnectTimeout=20", "ControlMaster=no", "ConnectTimeout=30"],
        ),
    ]
    assert snell_audit.ssh_options(calls[1][-1]) == [
        "-o",
        "BatchMode=yes",
        "-o",
        "ControlMaster=auto",
        "-o",
        "ConnectTimeout=20",
        "-o",
        "ControlMaster=no",
        "-o",
        "ConnectTimeout=30",
        "-o",
        "ConnectTimeout=10",
    ]
    assert json.loads(capsys.readouterr().out)["host_count"] == 2


def test_fleet_manifest_rejects_unknown_keys_and_duplicate_hosts(tmp_path: Path):
    snell_audit = load_module()
    unknown = tmp_path / "unknown.jsonl"
    unknown.write_text('{"host":"root@one","password":"secret"}\n')
    invalid_host = tmp_path / "invalid-host.jsonl"
    invalid_host.write_text('{"host":123}\n')
    duplicate = tmp_path / "duplicate.jsonl"
    duplicate.write_text(f'root@one\n{{"host":"root@one","port":{ALT_TEST_PORT}}}\n')
    invalid_options = tmp_path / "invalid-options.jsonl"
    invalid_options.write_text('{"host":"root@one","ssh_options":"ControlMaster=auto"}\n')

    with pytest.raises(snell_audit.CliError, match="unknown fleet target keys: password"):
        snell_audit.read_hosts_file(unknown)
    with pytest.raises(snell_audit.CliError, match=r"invalid-host\.jsonl:1: host must be a string"):
        snell_audit.read_hosts_file(invalid_host)
    with pytest.raises(snell_audit.CliError, match="duplicate fleet host"):
        snell_audit.read_hosts_file(duplicate)
    with pytest.raises(snell_audit.CliError, match="ssh_options must be a list of strings"):
        snell_audit.read_hosts_file(invalid_options)


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
    manifest = {"target": "root@example", "remote_dir": "/var/tmp/snell-runs/test-run"}
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
    args = argparse.Namespace(port=TEST_PORT, fail_on_issue=False)

    pack, rc = snell_audit.run_audit_for_host(args, "root@example")

    assert pack["status"] == "issue"
    assert rc == 0


def test_single_audit_issue_respects_fail_on_issue(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    snell_audit = load_module()
    local_dir = tmp_path / "run"
    local_dir.mkdir()
    manifest = {"target": "root@example", "remote_dir": "/var/tmp/snell-runs/test-run"}
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
    args = argparse.Namespace(port=TEST_PORT, fail_on_issue=True)

    _, rc = snell_audit.run_audit_for_host(args, "root@example")

    assert rc == 1


def test_single_audit_cleanup_failure_records_remote_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    snell_audit = load_module()
    local_dir = tmp_path / "run"
    local_dir.mkdir()
    manifest = {"target": "root@example", "remote_dir": "/var/tmp/snell-runs/test-run"}
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
    args = argparse.Namespace(port=TEST_PORT, fail_on_issue=False)

    pack, rc = snell_audit.run_audit_for_host(args, "root@example")

    assert rc != 0
    assert pack["persistent_effects"] == ["remote audit directory may remain: /var/tmp/snell-runs/test-run"]


def test_single_audit_transport_failure_exits_nonzero(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    snell_audit = load_module()
    local_dir = tmp_path / "run"
    local_dir.mkdir()
    manifest = {
        "target": "root@example",
        "remote_dir": "/var/tmp/snell-runs/test-run",
        "ownership_nonce": "test-nonce",
    }
    failed = subprocess.CompletedProcess(["ssh"], 255, "", "ssh failed")
    cleanup_failed = subprocess.CompletedProcess(["ssh"], 1, "", "ownership marker not found")

    monkeypatch.setattr(snell_audit, "prepare_audit_run", lambda args, host: (local_dir, manifest))
    monkeypatch.setattr(snell_audit, "upload_audit_run", lambda local_dir, manifest, args: failed)
    monkeypatch.setattr(snell_audit, "cleanup_remote_audit_run", lambda manifest, args: cleanup_failed)
    args = argparse.Namespace(port=TEST_PORT, fail_on_issue=False)

    pack, rc = snell_audit.run_audit_for_host(args, "root@example")

    assert rc == 255
    assert pack["transport_status"] == "failed"
    assert "transport.audit_failed" in finding_ids(pack)
    assert pack["persistent_effects"] == ["remote audit directory may remain: /var/tmp/snell-runs/test-run"]


@pytest.mark.parametrize("failed_stage", ["upload", "execute", "collect"])
def test_single_audit_cleans_created_remote_dir_after_every_failed_stage(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failed_stage: str
):
    snell_audit = load_module()
    local_dir = tmp_path / "run"
    local_dir.mkdir()
    manifest = {
        "target": "root@example",
        "remote_dir": "/var/tmp/snell-runs/test-run",
        "ownership_nonce": "test-nonce",
    }
    ok = subprocess.CompletedProcess(["true"], 0, "", "")
    failed = subprocess.CompletedProcess([failed_stage], 23, "", f"{failed_stage} failed")
    cleanup_calls: list[str] = []

    monkeypatch.setattr(snell_audit, "prepare_audit_run", lambda args, host: (local_dir, manifest))
    monkeypatch.setattr(snell_audit, "upload_audit_run", lambda *args: failed if failed_stage == "upload" else ok)
    monkeypatch.setattr(snell_audit, "run_remote_audit", lambda *args: failed if failed_stage == "execute" else ok)
    monkeypatch.setattr(snell_audit, "collect_audit_run", lambda *args: failed if failed_stage == "collect" else ok)

    def cleanup(*_args):
        cleanup_calls.append("cleanup")
        return ok

    monkeypatch.setattr(snell_audit, "cleanup_remote_audit_run", cleanup)
    args = argparse.Namespace(port=TEST_PORT, fail_on_issue=False)

    _, rc = snell_audit.run_audit_for_host(args, "root@example")

    assert rc != 0
    assert cleanup_calls == ["cleanup"]


def test_single_audit_preserves_execution_failure_over_collect_and_cleanup_failures(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    snell_audit = load_module()
    local_dir = tmp_path / "run"
    local_dir.mkdir()
    manifest = {
        "target": "root@example",
        "remote_dir": "/var/tmp/snell-runs/test-run",
        "ownership_nonce": "test-nonce",
    }
    ok = subprocess.CompletedProcess(["upload"], 0, "", "")
    execute_failed = subprocess.CompletedProcess(["execute"], 23, "", "execute failed")
    collect_failed = subprocess.CompletedProcess(["collect"], 24, "", "collect failed")
    cleanup_failed = subprocess.CompletedProcess(["cleanup"], 25, "", "cleanup failed")

    monkeypatch.setattr(snell_audit, "prepare_audit_run", lambda args, host: (local_dir, manifest))
    monkeypatch.setattr(snell_audit, "upload_audit_run", lambda *args: ok)
    monkeypatch.setattr(snell_audit, "run_remote_audit", lambda *args: execute_failed)
    monkeypatch.setattr(snell_audit, "collect_audit_run", lambda *args: collect_failed)
    monkeypatch.setattr(snell_audit, "cleanup_remote_audit_run", lambda *args: cleanup_failed)

    pack, rc = snell_audit.run_audit_for_host(argparse.Namespace(port=TEST_PORT, fail_on_issue=False), "root@example")

    assert rc == 23
    assert pack["persistent_effects"] == ["remote audit directory may remain: /var/tmp/snell-runs/test-run"]


def test_single_audit_ssh_timeout_becomes_transport_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    snell_audit = load_module()
    local_dir = tmp_path / "run"
    local_dir.mkdir()
    manifest = {
        "target": "root@example",
        "remote_dir": "/var/tmp/snell-runs/test-run",
        "ownership_nonce": "test-nonce",
    }

    def hang(command: list[str], *, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(command, timeout or 0)

    monkeypatch.setattr(snell_audit, "prepare_audit_run", lambda args, host: (local_dir, manifest))
    monkeypatch.setattr(snell_audit, "run_subprocess", hang)
    args = argparse.Namespace(port=TEST_PORT, ssh_option=[], timeout=900, fail_on_issue=False)

    pack, rc = snell_audit.run_audit_for_host(args, "root@example")

    assert rc == 124
    assert pack["transport_status"] == "failed"
    transport = next(item for item in pack["findings"] if item["id"] == "transport.audit_failed")
    assert any("timed out after 900s" in line for line in transport["evidence"])
    assert pack["persistent_effects"] == ["remote audit directory may remain: /var/tmp/snell-runs/test-run"]


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


@pytest.mark.parametrize(
    ("test_name", "payload"),
    [
        ("tcp", {"policy": {"available": 187, "error": "Read stream EOF"}}),
        ("udp", {"policy": {}}),
        ("external-ip", {"address": ""}),
        ("nat", {"nat-type": None}),
        ("tcp", {"policy": {"latency": 10}}),
        ("udp", {"policy": {"available": 10}}),
        ("external-ip", {"address": "not-an-ip"}),
        ("external-ip", {"address": 1}),
        ("external-ip", {"address": True}),
        ("external-ip", {"address": None}),
        ("nat", {"nat-type": 4}),
        ("nat", {"nat-type": "1"}),
    ],
)
def test_surge_probe_rejects_semantically_failed_payloads(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, test_name: str, payload: dict[str, object]
):
    snell_audit = load_module()
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    monkeypatch.setattr(
        snell_audit,
        "run_subprocess",
        lambda command, timeout: subprocess.CompletedProcess(command, 0, json.dumps(payload), ""),
    )

    result = snell_audit.run_surge_probe(
        surge_cli="/tmp/fake-surge-cli",
        policy="policy",
        test_name=test_name,
        logs_dir=logs_dir,
        timeout=5,
    )

    assert result["status"] == "failed"
    assert result["json_ok"] is True


@pytest.mark.parametrize(
    ("test_name", "payload"),
    [
        ("tcp", {"policy": {"available": 244, "receive": 313}}),
        ("udp", {"policy": {"receive": 241}}),
        ("external-ip", {"address": TEST_SOURCE_IP}),
        ("nat", {"nat-type": 3}),
    ],
)
def test_surge_probe_accepts_known_measurements_and_legal_nat_observations(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, test_name: str, payload: dict[str, object]
):
    snell_audit = load_module()
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    monkeypatch.setattr(
        snell_audit,
        "run_subprocess",
        lambda command, timeout: subprocess.CompletedProcess(command, 0, json.dumps(payload), ""),
    )

    result = snell_audit.run_surge_probe(
        surge_cli="/tmp/fake-surge-cli",
        policy="policy",
        test_name=test_name,
        logs_dir=logs_dir,
        timeout=5,
    )

    assert result["status"] == "passed"
    assert result["json_ok"] is True


def test_fleet_aggregates_persistent_effects_with_target_context(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    snell_audit = load_module()
    hosts = tmp_path / "hosts.txt"
    hosts.write_text("root@one\n")

    def fake_run(args: argparse.Namespace, host: str):
        del args
        return {
            "schema_version": 2,
            "operation": "audit-snell",
            "target": host,
            "transport_status": "failed",
            "status": "issue",
            "facts": {},
            "findings": [],
            "evidence_paths": {},
            "recommended_manual_actions": [],
            "persistent_effects": ["remote audit directory may remain: /var/tmp/run"],
        }, 1

    monkeypatch.setattr(snell_audit, "run_audit_for_host", fake_run)
    rc = snell_audit.command_audit_fleet(argparse.Namespace(hosts=hosts, fail_on_issue=False))

    assert rc == 1
    assert json.loads(capsys.readouterr().out)["persistent_effects"] == [
        {"target": "root@one", "effect": "remote audit directory may remain: /var/tmp/run"}
    ]


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
    retired_secret = "retired-secret-psk"
    config.write_text(
        f"[snell-server]\nlisten = 0.0.0.0:{TEST_PORT}\ndns-ip-preference = ipv4_only\npsk = {secret}\n"
        f"# psk = {retired_secret}\n;PSK = {retired_secret}-ini\n"
    )
    binary.write_text("#!/usr/bin/env bash\nprintf 'snell-server v5.0.1\\n'\n")
    binary.chmod(0o755)
    (run_dir / "input.env").write_text(f"SNELL_AUDIT_OPERATION=audit-snell\nSNELL_PORT={TEST_PORT}\n")

    fake_systemctl = fake_bin / "systemctl"
    fake_systemctl.write_text(
        "#!/usr/bin/env bash\n"
        # systemd 255: pattern with no matches exits 1 (empty stderr) for
        # list-unit-files and 0 for list-units; failed units carry a leading
        # marker column in list-units output; real query failures report on stderr.
        'if [ "$1" = list-unit-files ] || [ "$1" = list-units ]; then\n'
        '  case "${FAKE_SYSTEMCTL_DISCOVERY:-unique}" in\n'
        '    unique) echo "snell.service enabled enabled"; exit 0;;\n'
        '    none) if [ "$1" = list-unit-files ]; then exit 1; else exit 0; fi;;\n'
        "    transient-failed)\n"
        '      if [ "$1" = list-unit-files ]; then exit 1; fi\n'
        '      echo "● snell.service loaded failed failed Fake snell"; exit 0;;\n'
        '    multiple) printf "snell.service enabled enabled\\nsnell-server.service enabled enabled\\n"; exit 0;;\n'
        '    failed) echo "Failed to list unit files: connection refused" >&2; exit 1;;\n'
        "  esac\n"
        "fi\n"
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
        "#!/usr/bin/env bash\n"
        f"printf 'tcp LISTEN 0 128 0.0.0.0:{TEST_PORT} 0.0.0.0:* users:((\"snell-server\",pid=1234,fd=3))\\n'\n"
        "printf 'tcp LISTEN 0 128 0.0.0.0:8080 0.0.0.0:* users:((\"nginx\",pid=99,fd=6))\\n'\n"
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
    (fake_bin / "ufw").write_text(
        "#!/usr/bin/env bash\n"
        f"printf 'Status: active\\n"
        f"{TEST_PORT}/tcp ALLOW IN Anywhere\\n"
        f"{TEST_PORT}/udp DENY IN Anywhere\\n"
        f"{TEST_PORT}/udp (v6) ALLOW IN Anywhere (v6)\\n"
        "80/tcp DENY IN Anywhere\\n"
        "8080/tcp ALLOW IN Anywhere\\n'\n"
    )
    (fake_bin / "nft").write_text("#!/usr/bin/env bash\ntrue\n")
    # These probes must not reach the caller's Docker daemon or firewall.
    for name in ["iptables", "ip6tables"]:
        (fake_bin / name).write_text("#!/usr/bin/env bash\nprintf '%s\\n' '-P INPUT ACCEPT'\n")
    (fake_bin / "docker").write_text(
        "#!/usr/bin/env bash\nprintf '%s\\n' 'fixture-container fixture-proxy 0.0.0.0:8080->80/tcp'\n"
    )
    for name in ["ss", "journalctl", "sysctl", "sshd", "ufw", "nft", "iptables", "ip6tables", "docker"]:
        (fake_bin / name).chmod(0o755)

    env = os.environ.copy()
    env.pop("RUN_DIR", None)
    env["FAKE_SYSTEMCTL_DISCOVERY"] = "unique"
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    result = subprocess.run(["bash", str(PAYLOAD)], cwd=run_dir, env=env, text=True, capture_output=True, check=False)

    assert result.returncode == 0, result.stderr
    raw_log = (run_dir / "logs" / "audit_raw.log").read_text()
    summary = (run_dir / "logs" / "audit_summary.kv").read_text()
    assert secret not in raw_log
    assert retired_secret not in raw_log
    assert "psk = <redacted>" in raw_log
    assert "# psk = <redacted>" in raw_log
    assert ";PSK = <redacted>" in raw_log
    assert "schema_version=surge-snell.audit.remote.v1" in summary
    assert "snell_service_name=snell.service" in summary
    assert "config_dns_ip_preference=ipv4_only" in summary
    assert "tcp_listen=yes" in summary
    assert (run_dir / "logs" / "iptables_rules.log").read_text() == "-P INPUT ACCEPT\n"
    assert (run_dir / "logs" / "ip6tables_rules.log").read_text() == "-P INPUT ACCEPT\n"
    assert (run_dir / "logs" / "docker_ports.log").read_text() == (
        "fixture-container fixture-proxy 0.0.0.0:8080->80/tcp\n"
    )
    assert "iptables_rules_lines=1" in summary
    assert "ip6tables_rules_lines=1" in summary
    assert "docker_present=yes" in summary
    assert "docker_published_ports_lines=1" in summary
    assert "ufw_snell_tcp=yes" in summary
    # UDP is denied on IPv4 but allowed by the "(v6)" row, whose Action column
    # shifts right by one: an IPv6-only ALLOW is still inbound exposure.
    assert "ufw_snell_udp=yes" in summary

    # Port 80 is a prefix of the bound 8080: substring matching would fabricate
    # tcp_listen/ufw evidence for a socket and rule that belong to another service.
    collision_dir = tmp_path / "port-prefix-collision"
    collision_dir.mkdir()
    (collision_dir / "input.env").write_text("SNELL_AUDIT_OPERATION=audit-snell\nSNELL_PORT=80\n")
    collision = subprocess.run(
        ["bash", str(PAYLOAD)], cwd=collision_dir, env=env, text=True, capture_output=True, check=False
    )
    assert collision.returncode == 0, collision.stderr
    collision_summary = (collision_dir / "logs" / "audit_summary.kv").read_text()
    assert "tcp_listen=no" in collision_summary
    # Port 80 has only a DENY IN rule; the 8080/tcp ALLOW must not leak into it.
    assert "ufw_snell_tcp=no" in collision_summary

    # The payload carries no port default of its own: input.env must supply it.
    missing_port_dir = tmp_path / "missing-port"
    missing_port_dir.mkdir()
    (missing_port_dir / "input.env").write_text("SNELL_AUDIT_OPERATION=audit-snell\n")
    missing_port = subprocess.run(
        ["bash", str(PAYLOAD)], cwd=missing_port_dir, env=env, text=True, capture_output=True, check=False
    )
    assert missing_port.returncode != 0
    assert "SNELL_PORT missing from input.env" in missing_port.stderr

    def run_discovery_case(name: str, discovery: str, service: str = "") -> subprocess.CompletedProcess[str]:
        case_dir = tmp_path / name
        case_dir.mkdir()
        (case_dir / "input.env").write_text(
            f"SNELL_AUDIT_OPERATION=audit-snell\nSNELL_PORT={TEST_PORT}\nSNELL_SERVICE_NAME={service}\n"
        )
        case_env = env.copy()
        case_env["FAKE_SYSTEMCTL_DISCOVERY"] = discovery
        return subprocess.run(
            ["bash", str(PAYLOAD)], cwd=case_dir, env=case_env, text=True, capture_output=True, check=False
        )

    for name, discovery, expected_error in [
        ("no-candidate", "none", "no Snell service unit found"),
        ("multiple-candidates", "multiple", "multiple Snell service units found"),
        ("discovery-failed", "failed", "failed to discover installed Snell service units"),
    ]:
        failed_result = run_discovery_case(name, discovery)
        assert failed_result.returncode != 0
        assert expected_error in failed_result.stderr

    transient_result = run_discovery_case("transient-failed", "transient-failed")
    assert transient_result.returncode == 0, transient_result.stderr
    transient_summary = (tmp_path / "transient-failed" / "logs" / "audit_summary.kv").read_text()
    assert "snell_service_name=snell.service" in transient_summary

    override_result = run_discovery_case("explicit-override", "failed", "custom-snell.service")
    assert override_result.returncode == 0, override_result.stderr
    override_summary = (tmp_path / "explicit-override" / "logs" / "audit_summary.kv").read_text()
    assert "snell_service_name=custom-snell.service" in override_summary


def test_service_override_must_be_a_systemd_service_name():
    snell_audit = load_module()

    with pytest.raises(snell_audit.CliError, match="--service"):
        snell_audit.build_audit_input_env(TEST_PORT, "10 min ago", "snell;reboot")

    assert "SNELL_SERVICE_NAME=custom-snell.service" in snell_audit.build_audit_input_env(
        TEST_PORT, "10 min ago", "custom-snell.service"
    )


def test_skill_docs_default_to_read_only_audit():
    triage = TRIAGE.read_text()
    tuning = TUNING.read_text()
    combined = "\n".join([SKILL.read_text(), triage, tuning, SERVER.read_text()])

    assert "审计只经 SSH 跑只读采集命令" in triage
    assert "诊断阶段不套用这里的做法" in tuning
    assert "给人看的操作示例" in tuning
    assert "audit-snell" in triage
    assert "audit-fleet" in triage
    # The audit must disclose its remote temporary write and owned cleanup.
    assert "只创建、清理带归属标记的那个运行目录" in triage
    assert "用户不许在目标上落盘时，用 `--dry-run`" in triage
    # No execution / persistence verbs leaked back in.
    assert "install-snell" not in combined
    assert "confirm-persistent" not in combined


def test_skill_does_not_embed_target_context():
    docs = [SKILL, TRIAGE, SERVER, TUNING, CREDENTIALS, *sorted((ROOT / "references").rglob("*.md"))]
    distributable = "\n".join([*(path.read_text() for path in docs), SCRIPT.read_text(), PAYLOAD.read_text()])

    for residue in ["alex@example", "203.0.113.", "DEFAULT_PORT"]:
        assert residue not in distributable


def test_surge_smoke_documents_active_policy_and_manual_mutation_boundary():
    triage = TRIAGE.read_text()
    triage_normalized = " ".join(triage.split())

    assert "`smoke-surge` 只探测当前运行时里已有的某个 policy，不生成、注册、切换或恢复 profile" in triage
    assert "只读审计里不做 `reload` 和 `switch-profile`" in triage
    assert "用户要改 profile 时交给 `$surge`" in triage
    assert "审计这条路不改 Surge 运行时和 profile" in triage_normalized
    assert "嵌套的 policy 对象是空的，就是探测失败" in triage_normalized
    assert "ControlMaster=auto" in triage
    assert "persistent_effects" in triage
    assert "用实际的请求记录确认最终命中的 policy" in triage_normalized
    assert "证明不了这个进程绕过了增强模式" in triage_normalized


def test_upgrade_docs_identify_prereleases_and_preserve_control_path():
    server = SERVER.read_text()
    triage = TRIAGE.read_text()
    server_normalized = " ".join(server.split())
    triage_normalized = " ".join(triage.split())

    assert "不带 beta 或 RC 后缀，不能只凭它认版本" in server_normalized
    assert "不能证明是发布者认证过的" in server_normalized
    assert "证明重启这个 Snell 服务不会断掉唯一的控制和回滚路径" in server_normalized
    assert "同一条依赖上开的 SSH ControlMaster 不算独立的恢复路径" in server_normalized
    assert "有些 beta 或 RC 只报基础版本号和构建日期" in triage_normalized
    assert "SHA-256 和从官方地址重新下载的产物字节一致" in server_normalized
    assert "SSH 和回滚路径已证明不依赖要重启的 Snell 服务或 policy" in server_normalized
    assert "`snell-server` 的 `--help`" in server_normalized


def test_credentials_preserve_base64_padding_when_reading_psk():
    credentials = CREDENTIALS.read_text()

    assert "末尾的 `=` padding" in credentials
    assert "不能按所有 `=` 分列" in credentials
    assert "`umask 077`" in credentials
    assert "立即注册 `EXIT` trap" in credentials


def test_server_recipe_preserves_security_and_runtime_guards():
    server_reference = SERVER.read_text()

    assert "install -d -o root -g snell -m 0750" in server_reference
    assert "install -o root -g snell -m 0640" in server_reference
    assert "runuser -u snell -- test -r" in server_reference
    assert "runuser -u snell -- test -w" in server_reference
    assert "先显式设可执行权限再运行" in server_reference
    assert 'findmnt -no OPTIONS --target "$staged_binary"' in server_reference
    assert "root 拥有、`0700` 的暂存文件" in server_reference
    assert "原子 rename" in server_reference
    assert "`ETXTBSY`" in server_reference
    assert "只有 root 能进的 `/root` 下面的文件，哪怕组可读，服务也读不到" in server_reference
    assert "轮询 `MainPID` 和 `ss -H -lntup`" in server_reference
    assert "超时就算修复失败，触发回滚" in server_reference
    assert "不用 `mkdir -p`" in server_reference
    assert "普通 `mv` 或 rename 可能覆盖盘点之后才出现的路径" in server_reference


def test_skill_defines_psk_sources_and_platform_scope():
    skill = SKILL.read_text()
    credentials = CREDENTIALS.read_text()

    assert "由 Snell 支撑的 Ponte NAT 类型" in skill
    assert "`smoke-surge`" in skill
    assert "iOS" in skill
    assert "不去翻凭据缓存" in credentials
    assert "PSK 不跨 VPS" in credentials
    assert "命令行参数" in credentials
