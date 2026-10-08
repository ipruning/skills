#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///

"""Read Snell VPS state and run local Surge checks without repairing servers."""

from __future__ import annotations

import argparse
import datetime as dt
import ipaddress
import json
import os
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

EVIDENCE_SCHEMA_VERSION = 2
RUN_SCHEMA_VERSION = "surge-snell.audit-run.v2"
DEFAULT_LOCAL_ROOT = Path("/tmp/surge-snell-runs")
DEFAULT_REMOTE_BASE = "/var/tmp"
DEFAULT_JOURNAL_SINCE = "10 min ago"
RUN_ID_MAX_LEN = 80
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{7,79}$")
SERVICE_NAME_RE = re.compile(r"^[A-Za-z0-9_.@-]+\.service$")
SAFE_REMOTE_PATH_RE = re.compile(r"^/[A-Za-z0-9._/@+-][A-Za-z0-9._/@+-]*(?:/[A-Za-z0-9._@+-]+)*$")
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
FLEET_TARGET_KEYS = frozenset({"host", "port", "service", "expected_sha256", "sudo", "ssh_options"})
VALID_DNS_IP_PREFERENCES = frozenset({"default", "prefer-ipv4", "prefer-ipv6", "ipv4-only", "ipv6-only"})

SURGE_TEST_COMMANDS = {
    "tcp": ("test-policy",),
    "udp": ("test-policy-udp",),
    "external-ip": ("test-policy-external-ip",),
    "nat": ("test-policy-nat-type",),
}

HARDENING_DIRECTIVES = (
    "PrivateDevices",
    "ProtectSystem",
    "RestrictAddressFamilies",
    "CapabilityBoundingSet",
    "NoNewPrivileges",
    "PrivateTmp",
)

# Snell v5 UDP crash fingerprint. The per-needle counters and the
# since-current-MainPID marker check both derive from this table.
CRASH_NEEDLE_COUNTERS = {
    "uv_close": "uv_close_assert_count",
    "signal 6": "signal6_count",
    "Main process exited": "systemd_main_exited_count",
    "Failed with result": "systemd_failed_result_count",
}
CRASH_NEEDLES = ("UDP socket send error", *CRASH_NEEDLE_COUNTERS)


class CliError(Exception):
    def __init__(self, message: str, exit_code: int = 2) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def utc_now() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_run_id(prefix: str = "snell-audit") -> str:
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}-{stamp}-{uuid.uuid4().hex[:8]}"


def safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    return slug[:48] or "host"


def eprint(message: str) -> None:
    print(message, file=sys.stderr)


def print_json(data: dict[str, Any]) -> None:
    print(json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    path.chmod(0o600)


def write_text(path: Path, text: str, mode: int = 0o600) -> None:
    path.write_text(text)
    path.chmod(mode)


def subprocess_output_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value


def read_optional_text(path: Path) -> str:
    try:
        return path.read_text()
    except FileNotFoundError:
        return ""


def validate_host(host: str | None) -> str:
    if not host:
        raise CliError("--host is required")
    if any(char.isspace() for char in host):
        raise CliError("--host must not contain whitespace")
    # ssh/scp parse a leading "-" as an option, so a hosts-file entry like
    # -oProxyCommand=... would inject SSH options instead of naming a host.
    if host.startswith("-"):
        raise CliError("--host must not start with '-'")
    return host


def validate_port(port: int | None) -> int:
    if port is None:
        raise CliError("--port is required for audit-snell and for fleet targets without a port")
    if port < 1 or port > 65535:
        raise CliError("--port must be between 1 and 65535")
    return port


def validate_service_name(service: str | None) -> str:
    if service and not SERVICE_NAME_RE.match(service):
        raise CliError("--service must be a systemd .service unit name")
    return service or ""


def validate_sha256(digest: str | None) -> str:
    value = (digest or "").strip().lower()
    if value and not SHA256_RE.fullmatch(value):
        raise CliError("--expected-sha256 must be exactly 64 hexadecimal characters")
    return value


def validate_run_id(run_id: str) -> None:
    if not RUN_ID_RE.match(run_id):
        raise CliError("run id must be 8-80 safe characters: letters, digits, dot, underscore, hyphen")


def validate_remote_path(path: str) -> str:
    if not SAFE_REMOTE_PATH_RE.match(path):
        raise CliError(f"unsafe remote path: {path}")
    blocked = {"/", "/tmp", "/var", "/var/tmp", DEFAULT_REMOTE_BASE}
    normalized = path.rstrip("/") or "/"
    if normalized in blocked:
        raise CliError(f"remote run dir is too broad: {path}")
    if "/../" in f"{path}/" or path.endswith("/.."):
        raise CliError(f"remote run dir must not contain '..': {path}")
    return path


def ensure_new_dir(path: Path, overwrite: bool) -> None:
    if path.exists():
        if not overwrite:
            raise CliError(f"output dir already exists: {path}")
        shutil.rmtree(path)
    path.mkdir(parents=True, mode=0o700)


def shell_assign(name: str, value: str | int | bool | None) -> str:
    if value is True:
        text = "true"
    elif value is False:
        text = "false"
    elif value is None:
        text = ""
    else:
        text = str(value)
    return f"{name}={shlex.quote(text)}\n"


def payload_source() -> Path:
    path = Path(__file__).resolve().parent / "payloads" / "snell_debian_payload.sh"
    if not path.exists():
        raise CliError(f"missing private payload template: {path}")
    return path


def ssh_options(extra: list[str] | None) -> list[str]:
    options = ["-o", "BatchMode=yes"]
    for option in extra or []:
        options.extend(["-o", option])
    options.extend(["-o", "ConnectTimeout=10"])
    return options


def run_subprocess(command: list[str], *, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    eprint(f"+ {shlex.join(command)}")
    return subprocess.run(command, text=True, capture_output=True, timeout=timeout, check=False)


def run_transport_step(command: list[str], *, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    # A hung SSH step must land in the evidence pack as transport_status=failed
    # with persistent_effects, not escape as a TimeoutExpired traceback.
    try:
        return run_subprocess(command, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        stderr = subprocess_output_text(exc.stderr)
        message = f"timed out after {timeout}s: {shlex.join(command)}"
        if stderr.strip():
            message = f"{message}\n{stderr}"
        return subprocess.CompletedProcess(command, 124, subprocess_output_text(exc.stdout), message)


def build_audit_input_env(port: int, journal_since: str, service: str = "") -> str:
    return "".join([
        "# Generated by snell_audit.py. Read-only remote audit input.\n",
        shell_assign("SNELL_AUDIT_OPERATION", "audit-snell"),
        shell_assign("SNELL_PORT", port),
        shell_assign("SNELL_JOURNAL_SINCE", journal_since),
        shell_assign("SNELL_SERVICE_NAME", validate_service_name(service)),
    ])


def prepare_audit_run(args: argparse.Namespace, host: str) -> tuple[Path, dict[str, Any]]:
    if args.run_id and getattr(args, "command", "") == "audit-fleet":
        # Trim the shared prefix, never the host suffix: slicing the combined
        # string at 80 chars would drop the per-host part and collapse two
        # hosts onto the same run dir (overwriting each other's evidence).
        slug = safe_slug(host)
        max_prefix = RUN_ID_MAX_LEN - len(slug) - 1
        prefix = args.run_id[:max_prefix].rstrip("-._") or "fleet"
        run_id = f"{prefix}-{slug}"
    else:
        run_id = args.run_id or new_run_id()
    validate_run_id(run_id)
    local_dir = args.out.expanduser() / run_id
    remote_dir = validate_remote_path(f"{args.remote_base.rstrip('/')}/{run_id}")
    service = validate_service_name(getattr(args, "service", ""))
    expected_sha256 = validate_sha256(getattr(args, "expected_sha256", ""))
    ensure_new_dir(local_dir, args.overwrite)

    manifest = {
        "schema_version": RUN_SCHEMA_VERSION,
        "run_id": run_id,
        "ownership_nonce": secrets.token_hex(16),
        "operation": "audit-snell",
        "target": host,
        "remote_dir": remote_dir,
        "created_at": utc_now(),
        "persistent": False,
        "persistent_effects": [],
    }
    input_doc = {
        "schema_version": RUN_SCHEMA_VERSION,
        "operation": "audit-snell",
        "target": host,
        "parameters": {
            "port": args.port,
            "journal_since": args.journal_since,
            "service": service,
            "expected_sha256": expected_sha256,
            "sudo": bool(getattr(args, "sudo", False)),
        },
    }
    write_json(local_dir / "manifest.json", manifest)
    write_json(local_dir / "input.json", input_doc)
    write_text(local_dir / "input.env", build_audit_input_env(args.port, args.journal_since, service))
    payload_dir = local_dir / "payloads"
    payload_dir.mkdir(mode=0o700)
    shutil.copy2(payload_source(), payload_dir / "snell_debian_payload.sh")
    (payload_dir / "snell_debian_payload.sh").chmod(0o700)
    return local_dir, manifest


def remote_prepare_command(remote_dir: str, nonce: str, *, sudo: bool) -> str:
    parent = str(Path(remote_dir).parent)
    marker = f"{remote_dir}/.snell-audit-owner"
    if sudo:
        return (
            "set -eu; "
            f"if ! sudo -n test -d {shlex.quote(parent)}; then "
            "printf 'snell_audit: remote base is missing or inaccessible via sudo -n: %s\\n' "
            f"{shlex.quote(parent)} >&2; exit 1; fi; "
            'owner="$(id -u):$(id -g)"; '
            f"sudo -n mkdir -m 700 {shlex.quote(remote_dir)}; "
            f"if ! printf '%s\\n' {shlex.quote(nonce)} | sudo -n tee {shlex.quote(marker)} >/dev/null || "
            f'! sudo -n chown -R "$owner" {shlex.quote(remote_dir)}; then '
            f"sudo -n rm -rf -- {shlex.quote(remote_dir)}; exit 1; fi"
        )
    return (
        "set -eu; "
        f"if ! test -d {shlex.quote(parent)}; then "
        "printf 'snell_audit: remote base is not an existing directory: %s\\n' "
        f"{shlex.quote(parent)} >&2; exit 1; fi; "
        f"mkdir -m 700 {shlex.quote(remote_dir)}; "
        f"if ! printf '%s\\n' {shlex.quote(nonce)} > {shlex.quote(marker)}; then "
        f"rm -rf -- {shlex.quote(remote_dir)}; exit 1; fi"
    )


def remote_cleanup_command(remote_dir: str, nonce: str, *, sudo: bool) -> str:
    marker = f"{remote_dir}/.snell-audit-owner"
    cat_command = f"cat {shlex.quote(marker)}"
    rm_command = f"rm -rf -- {shlex.quote(remote_dir)}"
    if sudo:
        cat_command = f"sudo -n cat -- {shlex.quote(marker)}"
        rm_command = f"sudo -n {rm_command}"
    return f'marker=$({cat_command} 2>/dev/null) && test "$marker" = {shlex.quote(nonce)} && {rm_command}'


def upload_audit_run(
    local_dir: Path, manifest: dict[str, Any], args: argparse.Namespace
) -> subprocess.CompletedProcess[str]:
    host = validate_host(manifest["target"])
    remote_dir = validate_remote_path(manifest["remote_dir"])
    nonce = str(manifest["ownership_nonce"])
    remote_prepare = remote_prepare_command(remote_dir, nonce, sudo=bool(getattr(args, "sudo", False)))
    ssh_result = run_transport_step(["ssh", *ssh_options(args.ssh_option), host, remote_prepare], timeout=args.timeout)
    if ssh_result.returncode != 0:
        return ssh_result
    return run_transport_step(
        ["scp", "-r", *ssh_options(args.ssh_option), f"{local_dir}/.", f"{host}:{remote_dir}/"],
        timeout=args.timeout,
    )


def run_remote_audit(manifest: dict[str, Any], args: argparse.Namespace) -> subprocess.CompletedProcess[str]:
    host = validate_host(manifest["target"])
    remote_dir = validate_remote_path(manifest["remote_dir"])
    payload_command = "RUN_DIR=$PWD bash payloads/snell_debian_payload.sh"
    if getattr(args, "sudo", False):
        privileged_script = "\n".join([
            "bash payloads/snell_debian_payload.sh",
            "rc=$?",
            'chown -R -- "$RUN_OWNER_UID:$RUN_OWNER_GID" "$RUN_DIR" || rc=1',
            'exit "$rc"',
        ])
        payload_command = (
            'sudo -n env RUN_DIR="$PWD" RUN_OWNER_UID="$(id -u)" RUN_OWNER_GID="$(id -g)" '
            f"bash -c {shlex.quote(privileged_script)}"
        )
    remote_command = "\n".join([
        "set -u",
        f"cd {shlex.quote(remote_dir)}",
        "umask 077",
        "mkdir -p logs",
        "date -u '+%Y-%m-%dT%H:%M:%SZ' > started_at",
        "set +e",
        f"{payload_command} > stdout 2> stderr",
        "rc=$?",
        "printf '%s\\n' \"$rc\" > exit_code",
        "date -u '+%Y-%m-%dT%H:%M:%SZ' > finished_at",
        'exit "$rc"',
    ])
    return run_transport_step(["ssh", *ssh_options(args.ssh_option), host, remote_command], timeout=args.timeout)


def collect_audit_run(
    local_dir: Path, manifest: dict[str, Any], args: argparse.Namespace
) -> subprocess.CompletedProcess[str]:
    host = validate_host(manifest["target"])
    remote_dir = validate_remote_path(manifest["remote_dir"])
    return run_transport_step(
        ["scp", "-r", *ssh_options(args.ssh_option), f"{host}:{remote_dir}/.", f"{local_dir}/"],
        timeout=args.timeout,
    )


def cleanup_remote_audit_run(manifest: dict[str, Any], args: argparse.Namespace) -> subprocess.CompletedProcess[str]:
    host = validate_host(manifest["target"])
    remote_dir = validate_remote_path(manifest["remote_dir"])
    nonce = str(manifest["ownership_nonce"])
    cleanup_command = remote_cleanup_command(remote_dir, nonce, sudo=bool(getattr(args, "sudo", False)))
    return run_transport_step(
        [
            "ssh",
            *ssh_options(getattr(args, "ssh_option", [])),
            host,
            cleanup_command,
        ],
        timeout=getattr(args, "timeout", None),
    )


def remote_dir_effect(manifest: dict[str, Any], *, uncertain: bool = False) -> list[str]:
    remote_dir = manifest.get("remote_dir", "")
    if not remote_dir:
        return []
    verb = "may remain" if uncertain else "remains"
    return [f"remote audit directory {verb}: {remote_dir}"]


def read_kv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in read_optional_text(path).splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def int_value(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except TypeError:
        return default
    except ValueError:
        return default


def bool_yes(value: Any) -> bool:
    return str(value).strip().lower() in {"yes", "true", "1", "active", "enabled"}


def csv_values(value: str) -> list[str]:
    return [item for item in (part.strip() for part in value.split(",")) if item]


def snell_major_from_text(version_text: str) -> str:
    match = re.search(r"\bsnell-server\s+v?(\d+)(?:[.\s]|$)", version_text, re.IGNORECASE)
    if not match:
        match = re.search(r"\bv(\d+)(?:[.\s]|$)", version_text, re.IGNORECASE)
    return match.group(1) if match else ""


def parse_journal_counts(journal_text: str, current_main_pid: str) -> dict[str, Any]:
    counts: dict[str, Any] = {
        "udp_invalid_argument_count": 0,
        "uv_close_assert_count": 0,
        "signal6_count": 0,
        "systemd_main_exited_count": 0,
        "systemd_failed_result_count": 0,
        "decryption_failed_count": 0,
        "markers_since_current_mainpid": 0,
        "last_udp_crash_at": "",
    }
    top_decryption: dict[str, int] = {}
    for line in journal_text.splitlines():
        if "UDP socket send error" in line and "invalid argument" in line.lower():
            counts["udp_invalid_argument_count"] += 1
            counts["last_udp_crash_at"] = line[:80]
        for needle, counter in CRASH_NEEDLE_COUNTERS.items():
            if needle in line:
                counts[counter] += 1
                counts["last_udp_crash_at"] = line[:80]
        if "Decryption failed" in line:
            counts["decryption_failed_count"] += 1
            token = line.rsplit(maxsplit=1)[-1] if line.split() else "-"
            top_decryption[token] = top_decryption.get(token, 0) + 1
        if (
            current_main_pid
            and current_main_pid != "0"
            and f"[{current_main_pid}]" in line
            and any(needle in line for needle in CRASH_NEEDLES)
        ):
            counts["markers_since_current_mainpid"] += 1
    if top_decryption:
        top_ip, top_count = max(top_decryption.items(), key=lambda item: item[1])
        counts["top_decryption"] = f"{top_count}:{top_ip}"
    else:
        counts["top_decryption"] = "0:-"
    return counts


def build_facts(summary: dict[str, str], journal_text: str, *, expected_binary_sha256: str = "") -> dict[str, Any]:
    version_text = summary.get("snell_version_text", "")
    major = snell_major_from_text(version_text)
    port = int_value(summary.get("snell_port"))
    log_counts = parse_journal_counts(journal_text, summary.get("systemd_main_pid", ""))
    facts = {
        "snell": {
            "port": port,
            "version_text": version_text,
            "major": major,
            "binary_path": summary.get("snell_binary_path", ""),
            "binary_sha256": summary.get("snell_binary_sha256", "").lower(),
            "expected_binary_sha256": expected_binary_sha256,
            "config_path": summary.get("snell_config_path", ""),
            "tcp_listen": bool_yes(summary.get("tcp_listen")),
            "udp_listen": bool_yes(summary.get("udp_listen")),
            "config": {
                "present": bool_yes(summary.get("config_present")),
                "owner_user": summary.get("config_owner_user", ""),
                "owner_group": summary.get("config_owner_group", ""),
                "mode": summary.get("config_mode", ""),
                "service_readable": summary.get("config_service_readable", ""),
                "service_writable": summary.get("config_service_writable", ""),
                "parent_path": summary.get("config_parent_path", ""),
                "parent_owner_user": summary.get("config_parent_owner_user", ""),
                "parent_owner_group": summary.get("config_parent_owner_group", ""),
                "parent_mode": summary.get("config_parent_mode", ""),
                "parent_service_writable": summary.get("config_parent_service_writable", ""),
                "psk_present": bool_yes(summary.get("config_psk_present")),
                "listen": summary.get("config_listen", ""),
                "legacy_keys": csv_values(summary.get("config_legacy_keys", "")),
                "dns_ip_preference_present": bool_yes(summary.get("config_dns_ip_preference_present")),
                "dns_ip_preference": summary.get("config_dns_ip_preference", ""),
            },
        },
        "systemd": {
            "service_name": summary.get("snell_service_name", ""),
            "active": summary.get("systemd_active", ""),
            "sub": summary.get("systemd_sub", ""),
            "result": summary.get("systemd_result", ""),
            "restart": summary.get("systemd_restart", ""),
            "user": summary.get("systemd_user", ""),
            "group": summary.get("systemd_group", ""),
            "main_pid": summary.get("systemd_main_pid", ""),
            "n_restarts": int_value(summary.get("systemd_nrestarts")),
            "limit_nofile": int_value(summary.get("systemd_limit_nofile")),
            "hardening_mentions": int_value(summary.get("systemd_hardening_mentions")),
            "hardening_directives": csv_values(summary.get("systemd_hardening_directives", "")),
        },
        "ssh": {
            "permit_root_login": summary.get("ssh_permitrootlogin", ""),
            "password_authentication": summary.get("ssh_passwordauthentication", ""),
            "kbd_interactive_authentication": summary.get("ssh_kbdinteractiveauthentication", ""),
            "pubkey_authentication": summary.get("ssh_pubkeyauthentication", ""),
            "max_auth_tries": int_value(summary.get("ssh_maxauthtries")),
            "authentication_methods": summary.get("ssh_authenticationmethods", ""),
            "root_authorized_keys_count": int_value(summary.get("ssh_root_authorized_keys_count")),
        },
        "firewall": {
            "ufw_status": summary.get("ufw_status", ""),
            "ufw_snell_tcp": bool_yes(summary.get("ufw_snell_tcp")),
            "ufw_snell_udp": bool_yes(summary.get("ufw_snell_udp")),
            "nft_ruleset_lines": int_value(summary.get("nft_ruleset_lines")),
            "iptables_rules_lines": int_value(summary.get("iptables_rules_lines")),
            "ip6tables_rules_lines": int_value(summary.get("ip6tables_rules_lines")),
            "docker_present": bool_yes(summary.get("docker_present")),
            "docker_published_ports_lines": int_value(summary.get("docker_published_ports_lines")),
        },
        "sysctl": {
            "default_qdisc": summary.get("sysctl_net_core_default_qdisc", ""),
            "tcp_congestion_control": summary.get("sysctl_net_ipv4_tcp_congestion_control", ""),
            "somaxconn": int_value(summary.get("sysctl_net_core_somaxconn")),
            "tcp_max_syn_backlog": int_value(summary.get("sysctl_net_ipv4_tcp_max_syn_backlog")),
            "tcp_syncookies": int_value(summary.get("sysctl_net_ipv4_tcp_syncookies")),
            "ip_local_port_range": summary.get("sysctl_net_ipv4_ip_local_port_range", ""),
            "ip_local_reserved_ports": summary.get("sysctl_net_ipv4_ip_local_reserved_ports", ""),
            "tcp_mtu_probing": int_value(summary.get("sysctl_net_ipv4_tcp_mtu_probing"), -1),
            "nf_conntrack_count": int_value(summary.get("sysctl_net_netfilter_nf_conntrack_count"), -1),
            "nf_conntrack_max": int_value(summary.get("sysctl_net_netfilter_nf_conntrack_max"), -1),
        },
        "swap": {
            "mem_total_kib": int_value(summary.get("mem_total_kib")),
            "swap_total_kib": int_value(summary.get("swap_total_kib")),
            "swap_free_kib": int_value(summary.get("swap_free_kib")),
            "fstab_swap_entries": int_value(summary.get("fstab_swap_entries")),
            "root_available_kib": int_value(summary.get("root_available_kib")),
        },
        "journald": {
            "disk_usage": summary.get("journald_disk_usage", ""),
        },
        "logs": log_counts,
    }
    return facts


def finding(
    finding_id: str,
    severity: str,
    evidence: list[str],
    suggested_action: str,
    *,
    state: str = "present",
    persistent_change: bool = False,
) -> dict[str, Any]:
    return {
        "id": finding_id,
        "severity": severity,
        "state": state,
        "evidence": evidence,
        "suggested_action": suggested_action,
        "persistent_change": persistent_change,
    }


def build_findings(facts: dict[str, Any]) -> list[dict[str, Any]]:
    """Report structural problems only: crash fingerprints, exposure, hardening, availability.

    Performance and capacity tuning (sysctl, conntrack, swap, LimitNOFILE,
    MaxAuthTries, decryption noise) stays out of findings; the reader judges
    those from ``facts``.
    """
    findings: list[dict[str, Any]] = []
    snell = facts["snell"]
    systemd = facts["systemd"]
    firewall = facts["firewall"]
    logs = facts["logs"]
    port = int(snell["port"])
    major = str(snell["major"])

    expected_binary_sha256 = snell["expected_binary_sha256"]
    binary_sha256 = snell["binary_sha256"]
    if expected_binary_sha256 and binary_sha256 != expected_binary_sha256:
        findings.append(
            finding(
                "snell.binary_digest_mismatch",
                "high",
                [
                    f"expected_sha256={expected_binary_sha256}",
                    f"actual_sha256={binary_sha256 or 'missing'}",
                ],
                "stop the migration and verify the official artifact, architecture, and installed binary bytes",
            )
        )

    if systemd["active"] != "active":
        findings.append(
            finding(
                "snell.service_inactive",
                "high",
                [f"ActiveState={systemd['active']}", f"SubState={systemd['sub']}"],
                "inspect journal and unit state; start/restart only after reading the evidence",
            )
        )
    if systemd["sub"] and systemd["sub"] != "running":
        findings.append(
            finding(
                "snell.service_not_running",
                "high",
                [f"SubState={systemd['sub']}", f"Result={systemd['result']}"],
                "inspect systemctl status and journal before changing the unit",
            )
        )
    if not snell["tcp_listen"]:
        findings.append(
            finding(
                "snell.tcp_not_listening",
                "high",
                [f"port={port}", "tcp_listen=false"],
                "verify ExecStart, config listen address, and service logs",
            )
        )

    root_service = systemd["user"] in {"", "root"}
    if root_service:
        findings.append(
            finding(
                "snell.service_identity_mismatch",
                "medium",
                [f"User={systemd['user'] or 'root(default)'}"],
                "run Snell under a dedicated non-root service identity after staging rollback",
            )
        )
    config = snell["config"]
    config_mode = config["mode"]
    try:
        config_mode_bits = int(config_mode, 8) if config_mode else None
    except ValueError:
        config_mode_bits = None
    insecure_mode = config_mode_bits is not None and bool(config_mode_bits & 0o037)
    unreadable = config["service_readable"] in {"no", "unknown"}
    # A root service inherently owns and can rewrite its config; those signals
    # restate service_identity_mismatch. Judge them only for a non-root service.
    service_owns_config = not root_service and config["owner_user"] == systemd["user"]
    service_can_write = not root_service and config["service_writable"] in {"yes", "unknown"}
    service_can_replace = not root_service and config["parent_service_writable"] in {"yes", "unknown"}
    if config["present"] and (
        insecure_mode or unreadable or service_owns_config or service_can_write or service_can_replace
    ):
        findings.append(
            finding(
                "snell.config_permissions_mismatch",
                "medium",
                [
                    f"owner={config['owner_user'] or 'unknown'}:{config['owner_group'] or 'unknown'}",
                    f"mode={config['mode'] or 'unknown'}",
                    f"service_readable={config['service_readable'] or 'not-collected'}",
                    f"service_writable={config['service_writable'] or 'not-collected'}",
                    f"parent={config['parent_owner_user'] or 'unknown'}:{config['parent_owner_group'] or 'unknown'} {config['parent_mode'] or 'unknown'}",
                    f"parent_service_writable={config['parent_service_writable'] or 'not-collected'}",
                ],
                "make the config and parent directory root-owned and readable but not writable by the non-root service",
            )
        )

    true_udp_crash = (
        major == "5"
        and snell["udp_listen"]
        and logs["udp_invalid_argument_count"] > 0
        and (logs["uv_close_assert_count"] > 0 or logs["signal6_count"] > 0 or logs["systemd_main_exited_count"] > 0)
    )
    if true_udp_crash:
        findings.append(
            finding(
                "snell.v5.udp_crash",
                "high",
                [
                    f"udp_invalid_argument_count={logs['udp_invalid_argument_count']}",
                    f"uv_close_assert_count={logs['uv_close_assert_count']}",
                    f"signal6_count={logs['signal6_count']}",
                    f"systemd_main_exited_count={logs['systemd_main_exited_count']}",
                ],
                "inspect Snell v5 UDP listener and active systemd drop-ins; do not auto-delete hardening",
            )
        )
    elif (
        major == "5"
        and snell["udp_listen"]
        and (logs["uv_close_assert_count"] > 0 or logs["signal6_count"] > 0 or logs["systemd_main_exited_count"] > 0)
    ):
        findings.append(
            finding(
                "snell.v5.historical_crash_markers",
                "medium",
                [
                    f"uv_close_assert_count={logs['uv_close_assert_count']}",
                    f"signal6_count={logs['signal6_count']}",
                    f"systemd_main_exited_count={logs['systemd_main_exited_count']}",
                    f"markers_since_current_mainpid={logs['markers_since_current_mainpid']}",
                ],
                "compare marker timestamps with current MainPID before changing the service",
            )
        )

    if major == "6" and snell["udp_listen"]:
        findings.append(
            finding(
                "snell.v6.udp_listener_present",
                "medium",
                [f"port={port}", "udp_listen=true"],
                "confirm UDP is intentionally required; ordinary Snell v6 deployments should stay TCP-only",
            )
        )
    if major == "6" and firewall["ufw_snell_udp"]:
        findings.append(
            finding(
                "snell.v6.udp_firewall_exposed",
                "medium",
                [f"port={port}", "ufw_snell_udp=true"],
                "close UDP only after confirming no v5/QUIC workload depends on it",
            )
        )
    legacy_keys = snell["config"]["legacy_keys"]
    if major == "6" and legacy_keys:
        findings.append(
            finding(
                "snell.v6.legacy_config_keys",
                "medium",
                [f"legacy_keys={','.join(legacy_keys)}"],
                "rewrite the config manually for Snell v6 semantics; do not reuse old v5 templates",
            )
        )

    dns_ip_preference = snell["config"]["dns_ip_preference"]
    if dns_ip_preference and dns_ip_preference not in VALID_DNS_IP_PREFERENCES:
        findings.append(
            finding(
                "snell.invalid_dns_ip_preference",
                "medium",
                [
                    f"dns_ip_preference={dns_ip_preference}",
                    f"valid_values={','.join(sorted(VALID_DNS_IP_PREFERENCES))}",
                ],
                "replace the value with one reported by the installed server binary's --help output",
            )
        )

    if systemd["hardening_mentions"]:
        severity = "high" if major == "5" and snell["udp_listen"] else "medium"
        findings.append(
            finding(
                "systemd.hardening_present",
                severity,
                [f"directives={','.join(systemd['hardening_directives']) or systemd['hardening_mentions']}"],
                "read systemctl cat output and decide manually; the tool must not remove drop-ins automatically",
            )
        )
    return findings


def status_from_findings(findings: list[dict[str, Any]]) -> str:
    if any(item["severity"] == "high" for item in findings):
        return "issue"
    if findings:
        return "warn"
    return "ok"


def build_evidence_pack(
    *,
    local_dir: Path,
    target: str,
    transport_status: str,
    transport_error: str = "",
    persistent_effects: list[str] | None = None,
    expected_binary_sha256: str = "",
) -> dict[str, Any]:
    summary_path = local_dir / "logs" / "audit_summary.kv"
    journal_path = local_dir / "logs" / "journal_recent.log"
    summary = read_kv(summary_path)
    facts = (
        build_facts(
            summary,
            read_optional_text(journal_path),
            expected_binary_sha256=validate_sha256(expected_binary_sha256),
        )
        if summary
        else {}
    )
    findings = build_findings(facts) if facts else []
    status = status_from_findings(findings) if transport_status == "ok" else "issue"
    if transport_status != "ok":
        findings.append(
            finding(
                "transport.audit_failed",
                "high",
                [transport_error or "remote audit did not complete"],
                "fix SSH, sudo/root access, or payload execution before interpreting server health",
            )
        )
    evidence_paths = {
        "audit_json": str(local_dir / "audit.json"),
        "remote_stdout": str(local_dir / "stdout"),
        "remote_stderr": str(local_dir / "stderr"),
        "remote_exit_code": str(local_dir / "exit_code"),
        "raw_log": str(local_dir / "logs" / "audit_raw.log"),
        "summary_kv": str(summary_path),
        "journal_recent": str(journal_path),
        "service_cat": str(local_dir / "logs" / "service_cat.log"),
        "listeners": str(local_dir / "logs" / "listeners.log"),
        "sshd_effective": str(local_dir / "logs" / "sshd_effective.log"),
        "ufw_status": str(local_dir / "logs" / "ufw_status.log"),
        "nft_ruleset": str(local_dir / "logs" / "nft_ruleset.log"),
        "iptables_rules": str(local_dir / "logs" / "iptables_rules.log"),
        "docker_ports": str(local_dir / "logs" / "docker_ports.log"),
    }
    recommended_manual_actions = [item["suggested_action"] for item in findings if item["state"] == "present"]
    pack = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "operation": "audit-snell",
        "target": target,
        "transport_status": transport_status,
        "status": status,
        "facts": facts,
        "findings": findings,
        "evidence_paths": evidence_paths,
        "recommended_manual_actions": recommended_manual_actions,
        "persistent_effects": persistent_effects or [],
        "created_at": utc_now(),
    }
    write_json(local_dir / "audit.json", pack)
    write_json(local_dir / "result.json", pack)
    return pack


def audit_plan(args: argparse.Namespace, host: str) -> dict[str, Any]:
    host = validate_host(host)
    port = validate_port(args.port)
    service = validate_service_name(getattr(args, "service", ""))
    expected_sha256 = validate_sha256(getattr(args, "expected_sha256", ""))
    remote_dir = f"{args.remote_base.rstrip('/')}/<run-id>"
    ssh_opts = ssh_options(args.ssh_option)
    use_sudo = bool(getattr(args, "sudo", False))
    sudo_prefix = "sudo -n " if use_sudo else ""
    prepare_command = remote_prepare_command(remote_dir, "<ownership-nonce>", sudo=use_sudo)
    cleanup_command = remote_cleanup_command(remote_dir, "<ownership-nonce>", sudo=use_sudo)
    return {
        "operation": "audit-snell",
        "dry_run": True,
        "target": host,
        "port": port,
        "service": service or "auto-discover unique *snell*.service",
        "expected_sha256": expected_sha256,
        "sudo": use_sudo,
        "local_out": str(args.out.expanduser()),
        "server_writes": f"creates and removes a temporary evidence dir under {args.remote_base}",
        "commands": [
            shlex.join(["ssh", *ssh_opts, host, prepare_command]),
            shlex.join(["scp", "-r", *ssh_opts, "<local-run>/.", f"{host}:{remote_dir}/"]),
            shlex.join([
                "ssh",
                *ssh_opts,
                host,
                f"{sudo_prefix}bash payloads/snell_debian_payload.sh (read-only collection)",
            ]),
            shlex.join(["scp", "-r", *ssh_opts, f"{host}:{remote_dir}/.", "<local-run>/"]),
            shlex.join(["ssh", *ssh_opts, host, cleanup_command]),
        ],
    }


def run_audit_for_host(args: argparse.Namespace, host: str) -> tuple[dict[str, Any], int]:
    validate_port(args.port)
    validate_service_name(getattr(args, "service", ""))
    expected_binary_sha256 = validate_sha256(getattr(args, "expected_sha256", ""))
    host = validate_host(host)
    local_dir, manifest = prepare_audit_run(args, host)

    upload_result = upload_audit_run(local_dir, manifest, args)
    if upload_result.returncode != 0:
        # Preparation may have completed remotely even when its SSH
        # acknowledgement was lost. Marker-gated cleanup is safe after both a
        # collision and an uncertain transport result.
        cleanup_result = cleanup_remote_audit_run(manifest, args)
        persistent_effects = [] if cleanup_result.returncode == 0 else remote_dir_effect(manifest, uncertain=True)
        pack = build_evidence_pack(
            local_dir=local_dir,
            target=host,
            transport_status="failed",
            transport_error=upload_result.stderr or upload_result.stdout,
            persistent_effects=persistent_effects,
        )
        return pack, upload_result.returncode or cleanup_result.returncode or 1

    run_result = run_remote_audit(manifest, args)
    collect_result = collect_audit_run(local_dir, manifest, args)
    cleanup_result = cleanup_remote_audit_run(manifest, args)
    persistent_effects = [] if cleanup_result.returncode == 0 else remote_dir_effect(manifest, uncertain=True)
    if run_result.returncode != 0:
        stderr = read_optional_text(local_dir / "stderr") or run_result.stderr or run_result.stdout
        pack = build_evidence_pack(
            local_dir=local_dir,
            target=host,
            transport_status="failed",
            transport_error=stderr,
            persistent_effects=persistent_effects,
        )
        return pack, run_result.returncode or cleanup_result.returncode or 1

    if collect_result.returncode != 0:
        pack = build_evidence_pack(
            local_dir=local_dir,
            target=host,
            transport_status="failed",
            transport_error=collect_result.stderr or collect_result.stdout,
            persistent_effects=persistent_effects,
        )
        return pack, collect_result.returncode or cleanup_result.returncode or 1

    pack = build_evidence_pack(
        local_dir=local_dir,
        target=host,
        transport_status="ok",
        persistent_effects=persistent_effects,
        expected_binary_sha256=expected_binary_sha256,
    )
    if args.fail_on_issue and pack["status"] == "issue":
        return pack, 1
    return pack, cleanup_result.returncode or 0


def command_audit_snell(args: argparse.Namespace) -> int:
    if getattr(args, "dry_run", False):
        validate_port(args.port)
        print_json(audit_plan(args, args.host))
        return 0
    pack, exit_code = run_audit_for_host(args, args.host)
    print_json(pack)
    return exit_code


def validate_fleet_target(value: Any, *, source: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CliError(f"{source}: JSON fleet target must be an object")
    unknown_keys = sorted(key for key in value if isinstance(key, str) and key not in FLEET_TARGET_KEYS)
    if unknown_keys:
        raise CliError(f"{source}: unknown fleet target keys: {', '.join(unknown_keys)}")

    raw_host = value.get("host")
    if not isinstance(raw_host, str):
        raise CliError(f"{source}: host must be a string")
    host = validate_host(raw_host)
    target: dict[str, Any] = {"host": host}
    if "port" in value:
        port = value["port"]
        if isinstance(port, bool) or not isinstance(port, int):
            raise CliError(f"{source}: port must be an integer")
        target["port"] = validate_port(port)
    if "service" in value:
        service = value["service"]
        if not isinstance(service, str):
            raise CliError(f"{source}: service must be a string")
        target["service"] = validate_service_name(service)
    if "expected_sha256" in value:
        digest = value["expected_sha256"]
        if not isinstance(digest, str):
            raise CliError(f"{source}: expected_sha256 must be a string")
        target["expected_sha256"] = validate_sha256(digest)
    if "sudo" in value:
        use_sudo = value["sudo"]
        if not isinstance(use_sudo, bool):
            raise CliError(f"{source}: sudo must be a boolean")
        target["sudo"] = use_sudo
    if "ssh_options" in value:
        options = value["ssh_options"]
        if not isinstance(options, list) or not all(isinstance(option, str) for option in options):
            raise CliError(f"{source}: ssh_options must be a list of strings")
        if any(not option or "\n" in option or "\0" in option for option in options):
            raise CliError(f"{source}: ssh_options entries must be non-empty single-line strings")
        target["ssh_options"] = options
    return target


def read_hosts_file(path: Path) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    seen_hosts: set[str] = set()
    for line_number, line in enumerate(path.read_text().splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        source = f"{path}:{line_number}"
        if stripped.startswith("{"):
            try:
                raw_target = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise CliError(f"{source}: invalid JSON fleet target: {exc.msg}") from exc
            target = validate_fleet_target(raw_target, source=source)
        else:
            target = {"host": validate_host(stripped)}
        host = target["host"]
        if host in seen_hosts:
            raise CliError(f"{source}: duplicate fleet host: {host}")
        seen_hosts.add(host)
        targets.append(target)
    if not targets:
        raise CliError(f"no hosts found in {path}")
    return targets


def fleet_target_args(args: argparse.Namespace, target: dict[str, Any]) -> argparse.Namespace:
    target_args = argparse.Namespace(**vars(args))
    target_args.port = target.get("port", getattr(args, "port", None))
    target_args.service = target.get("service", getattr(args, "service", ""))
    target_args.expected_sha256 = target.get("expected_sha256", getattr(args, "expected_sha256", ""))
    target_args.sudo = target.get("sudo", getattr(args, "sudo", False))
    target_args.ssh_option = [
        *target.get("ssh_options", []),
        *getattr(args, "ssh_option", []),
    ]
    return target_args


def command_audit_fleet(args: argparse.Namespace) -> int:
    targets = read_hosts_file(args.hosts.expanduser())
    if getattr(args, "dry_run", False):
        plans = [audit_plan(fleet_target_args(args, target), target["host"]) for target in targets]
        print_json({"operation": "audit-fleet", "dry_run": True, "hosts": plans})
        return 0
    results: list[dict[str, Any]] = []
    exit_code = 0
    for target in targets:
        host = target["host"]
        target_args = fleet_target_args(args, target)
        try:
            pack, host_exit = run_audit_for_host(target_args, host)
        except CliError as exc:
            host_exit = exc.exit_code
            pack = {
                "schema_version": EVIDENCE_SCHEMA_VERSION,
                "operation": "audit-snell",
                "target": host,
                "transport_status": "failed",
                "status": "issue",
                "facts": {},
                "findings": [
                    finding(
                        "transport.audit_failed",
                        "high",
                        [str(exc)],
                        "fix the host entry or SSH path before interpreting server health",
                    )
                ],
                "evidence_paths": {},
                "recommended_manual_actions": ["fix the host entry or SSH path before interpreting server health"],
                "persistent_effects": [],
                "created_at": utc_now(),
            }
        results.append(pack)
        if host_exit != 0:
            exit_code = 1
    if args.fail_on_issue and any(item["status"] == "issue" for item in results):
        exit_code = 1
    summary = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "operation": "audit-fleet",
        "transport_status": "ok" if all(item["transport_status"] == "ok" for item in results) else "failed",
        "status": "issue"
        if any(item["status"] == "issue" for item in results)
        else "warn"
        if any(item["status"] == "warn" for item in results)
        else "ok",
        "host_count": len(results),
        "results": results,
        "persistent_effects": [
            {"target": item["target"], "effect": effect}
            for item in results
            for effect in item.get("persistent_effects", [])
        ],
        "created_at": utc_now(),
    }
    print_json(summary)
    return exit_code


def resolve_surge_cli(configured: str) -> str:
    if configured:
        path = Path(configured).expanduser()
        if not path.exists() or not os.access(path, os.X_OK):
            raise CliError(f"--surge-cli is not executable: {configured}")
        return str(path)
    path = shutil.which("surge-cli")
    if path:
        return path
    app_path = Path("/Applications/Surge.app/Contents/Applications/surge-cli")
    if app_path.exists() and os.access(app_path, os.X_OK):
        return str(app_path)
    raise CliError("surge-cli not found")


def surge_probe_payload_is_valid(payload: Any, *, test_name: str, policy: str) -> bool:
    if not isinstance(payload, dict) or not payload:
        return False
    if payload.get("error") or payload.get("errors"):
        return False
    message_text = " ".join(str(payload.get(key, "")) for key in ("message", "msg", "detail", "reason")).lower()
    if any(term in message_text for term in ("missing", "not found", "not exist", "unknown")):
        return False
    if test_name in {"tcp", "udp"}:
        policy_result = payload.get(policy)
        if not isinstance(policy_result, dict) or policy_result.get("error") or policy_result.get("errors"):
            return False
        keys = ("receive",) if test_name == "udp" else ("available", "receive", "tcp")
        return any(
            isinstance(policy_result.get(key), (int, float))
            and not isinstance(policy_result.get(key), bool)
            and policy_result[key] > 0
            for key in keys
        )
    if test_name == "external-ip":
        address = payload.get("address")
        if not isinstance(address, str):
            return False
        try:
            ipaddress.ip_address(address)
        except ValueError:
            return False
        return True
    if test_name == "nat":
        nat_type = payload.get("nat-type")
        return isinstance(nat_type, int) and not isinstance(nat_type, bool) and nat_type in {1, 2, 3}
    return False


def run_surge_probe(
    *,
    surge_cli: str,
    policy: str,
    test_name: str,
    logs_dir: Path,
    timeout: int,
) -> dict[str, Any]:
    command_tail = SURGE_TEST_COMMANDS[test_name]
    command = [surge_cli, "--raw", *command_tail, policy]
    stdout_file = logs_dir / f"surge_{test_name}.stdout"
    stderr_file = logs_dir / f"surge_{test_name}.stderr"
    result_file = logs_dir / f"surge_{test_name}.result.json"
    try:
        result = run_subprocess(command, timeout=timeout)
        stdout = result.stdout
        stderr = result.stderr
        rc = result.returncode
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        stdout = subprocess_output_text(exc.stdout)
        stderr = subprocess_output_text(exc.stderr)
        rc = 124
        timed_out = True

    write_text(stdout_file, stdout)
    write_text(stderr_file, stderr)
    parsed_json: Any = None
    json_ok = False
    if stdout.strip():
        try:
            parsed_json = json.loads(stdout)
            json_ok = True
        except json.JSONDecodeError:
            parsed_json = None
    unsupported = "unknown command" in stderr.lower() or "not support" in stderr.lower()
    valid_payload = surge_probe_payload_is_valid(parsed_json, test_name=test_name, policy=policy)
    status = "unsupported" if unsupported else "passed"
    if timed_out or rc != 0 or not json_ok or not valid_payload:
        status = "unsupported" if unsupported else "failed"
    probe_result = {
        "test": test_name,
        "status": status,
        "return_code": rc,
        "timed_out": timed_out,
        "json_ok": json_ok,
        "stdout_file": str(stdout_file),
        "stderr_file": str(stderr_file),
        "parsed": parsed_json,
    }
    write_json(result_file, probe_result)
    return probe_result


def command_smoke_surge(args: argparse.Namespace) -> int:
    tests = args.test or ["tcp", "udp", "external-ip", "nat"]
    run_id = args.run_id or new_run_id("sp-smoke")
    validate_run_id(run_id)
    local_dir = args.out.expanduser() / run_id
    ensure_new_dir(local_dir, args.overwrite)
    logs_dir = local_dir / "logs"
    logs_dir.mkdir(mode=0o700)
    surge_cli = resolve_surge_cli(args.surge_cli or "")

    results = [
        run_surge_probe(
            surge_cli=surge_cli,
            policy=args.policy,
            test_name=test_name,
            logs_dir=logs_dir,
            timeout=args.probe_timeout,
        )
        for test_name in tests
    ]
    if any(item["status"] == "failed" for item in results):
        status = "issue"
    elif any(item["status"] == "unsupported" for item in results):
        status = "warn"
    else:
        status = "ok"
    summary = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "operation": "smoke-surge",
        "status": status,
        "policy": args.policy,
        "host_ip": args.host_ip or "",
        "surge_cli": surge_cli,
        "results": results,
        "evidence_paths": {"run_dir": str(local_dir), "logs": str(logs_dir)},
        "persistent_effects": [],
        "created_at": utc_now(),
    }
    write_json(local_dir / "result.json", summary)
    print_json(summary)
    return 0 if status in {"ok", "warn"} else 1


def add_audit_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--port",
        type=int,
        help="Snell port to probe; required for audit-snell and inherited by fleet targets without a port",
    )
    parser.add_argument(
        "--service",
        default="",
        help="systemd unit to audit; defaults to unique *snell*.service discovery",
    )
    parser.add_argument(
        "--expected-sha256",
        default="",
        help="expected installed Snell binary SHA-256; mismatch is a high-severity finding",
    )
    parser.add_argument(
        "--sudo",
        action="store_true",
        help="run the remote payload and cleanup through non-interactive sudo",
    )
    parser.add_argument(
        "--journal-since", default=DEFAULT_JOURNAL_SINCE, help="journalctl --since window for the remote log scan"
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_LOCAL_ROOT, help="local directory for evidence run dirs")
    parser.add_argument("--run-id", help="fixed run id instead of a generated one")
    parser.add_argument(
        "--remote-base",
        default=DEFAULT_REMOTE_BASE,
        help="existing parent dir on the server for the temporary evidence dir (default /var/tmp)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="overwrite an existing local run dir; remote run-dir collisions always fail closed",
    )
    parser.add_argument("--timeout", type=int, default=900, help="per-SSH-step timeout in seconds (default 900)")
    parser.add_argument("--ssh-option", action="append", default=[], help="extra ssh -o option, repeatable")
    parser.add_argument(
        "--fail-on-issue", action="store_true", help="exit 1 when findings report an issue (for CI gating)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the plan (host, remote dir, ssh/scp/rm commands) and exit without connecting",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="snell_audit.py",
        description="Read Snell VPS state and run local Surge checks. It does not repair VPSes.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    audit = subparsers.add_parser("audit-snell", help="read-only SSH audit of one Snell VPS")
    audit.add_argument("--host", required=True, help="SSH target such as user@host")
    add_audit_common_args(audit)
    audit.set_defaults(func=command_audit_snell)

    fleet = subparsers.add_parser("audit-fleet", help="read-only SSH audit of hosts listed in a file")
    fleet.add_argument(
        "--hosts",
        type=Path,
        required=True,
        help="file with one plain SSH target or JSON object per line",
    )
    add_audit_common_args(fleet)
    fleet.set_defaults(func=command_audit_fleet)

    smoke = subparsers.add_parser("smoke-surge", help="local Surge policy smoke checks; does not touch VPSes")
    smoke.add_argument("--policy", required=True)
    smoke.add_argument("--host-ip", help="IP under test, recorded in output")
    smoke.add_argument("--surge-cli", help="Path to surge-cli")
    smoke.add_argument("--probe-timeout", type=int, default=60)
    smoke.add_argument("--out", type=Path, default=DEFAULT_LOCAL_ROOT)
    smoke.add_argument("--run-id")
    smoke.add_argument("--overwrite", action="store_true")
    smoke.add_argument(
        "--test",
        choices=sorted(SURGE_TEST_COMMANDS),
        action="append",
        default=[],
        help="Surge smoke test to run; defaults to tcp, udp, external-ip, nat",
    )
    smoke.set_defaults(func=command_smoke_surge)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except CliError as exc:
        eprint(f"error: {exc}")
        return exc.exit_code
    except KeyboardInterrupt:
        eprint("error: interrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main())
