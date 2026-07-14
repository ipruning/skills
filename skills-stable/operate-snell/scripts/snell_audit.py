#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///

"""Read Snell VPS state and run local Surge checks without repairing servers."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
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
DEFAULT_REMOTE_BASE = "/var/tmp/surge-snell-runs"
DEFAULT_PORT = 14180
DEFAULT_JOURNAL_SINCE = "10 min ago"
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{7,79}$")
SERVICE_NAME_RE = re.compile(r"^[A-Za-z0-9_.@-]+\.service$")
SAFE_REMOTE_PATH_RE = re.compile(r"^/[A-Za-z0-9._/@+-][A-Za-z0-9._/@+-]*(?:/[A-Za-z0-9._@+-]+)*$")

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
    return host


def validate_port(port: int) -> int:
    if port < 1 or port > 65535:
        raise CliError("--port must be between 1 and 65535")
    return port


def validate_service_name(service: str | None) -> str:
    if service and not SERVICE_NAME_RE.match(service):
        raise CliError("--service must be a systemd .service unit name")
    return service or ""


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
    options = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]
    for option in extra or []:
        options.extend(["-o", option])
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
    return "".join(
        [
            "# Generated by snell_audit.py. Read-only remote audit input.\n",
            shell_assign("SNELL_AUDIT_OPERATION", "audit-snell"),
            shell_assign("SNELL_PORT", port),
            shell_assign("SNELL_JOURNAL_SINCE", journal_since),
            shell_assign("SNELL_SERVICE_NAME", validate_service_name(service)),
        ]
    )


def prepare_audit_run(args: argparse.Namespace, host: str) -> tuple[Path, dict[str, Any]]:
    if args.run_id and getattr(args, "command", "") == "audit-fleet":
        run_id = f"{args.run_id}-{safe_slug(host)}"[:80]
    else:
        run_id = args.run_id or new_run_id()
    validate_run_id(run_id)
    local_dir = args.out.expanduser() / run_id
    remote_dir = validate_remote_path(f"{args.remote_base.rstrip('/')}/{run_id}")
    service = validate_service_name(getattr(args, "service", ""))
    ensure_new_dir(local_dir, args.overwrite)

    manifest = {
        "schema_version": RUN_SCHEMA_VERSION,
        "run_id": run_id,
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


def upload_audit_run(
    local_dir: Path, manifest: dict[str, Any], args: argparse.Namespace
) -> subprocess.CompletedProcess[str]:
    host = validate_host(manifest["target"])
    remote_dir = validate_remote_path(manifest["remote_dir"])
    parent = str(Path(remote_dir).parent)
    remote_prepare = (
        "set -eu; "
        f"mkdir -p {shlex.quote(parent)}; "
        f"rm -rf -- {shlex.quote(remote_dir)}; "
        f"mkdir -m 700 -p {shlex.quote(remote_dir)}"
    )
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
    remote_command = "\n".join(
        [
            "set -u",
            f"cd {shlex.quote(remote_dir)}",
            "umask 077",
            "mkdir -p logs",
            "date -u '+%Y-%m-%dT%H:%M:%SZ' > started_at",
            "set +e",
            "RUN_DIR=$PWD bash payloads/snell_debian_payload.sh > stdout 2> stderr",
            "rc=$?",
            "printf '%s\\n' \"$rc\" > exit_code",
            "date -u '+%Y-%m-%dT%H:%M:%SZ' > finished_at",
            'exit "$rc"',
        ]
    )
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
    return run_transport_step(
        [
            "ssh",
            *ssh_options(getattr(args, "ssh_option", [])),
            host,
            f"rm -rf -- {shlex.quote(remote_dir)}",
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


def build_facts(summary: dict[str, str], journal_text: str) -> dict[str, Any]:
    version_text = summary.get("snell_version_text", "")
    major = snell_major_from_text(version_text)
    port = int_value(summary.get("snell_port"), DEFAULT_PORT)
    log_counts = parse_journal_counts(journal_text, summary.get("systemd_main_pid", ""))
    facts = {
        "snell": {
            "port": port,
            "version_text": version_text,
            "major": major,
            "binary_path": summary.get("snell_binary_path", ""),
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
) -> dict[str, Any]:
    summary_path = local_dir / "logs" / "audit_summary.kv"
    journal_path = local_dir / "logs" / "journal_recent.log"
    summary = read_kv(summary_path)
    facts = build_facts(summary, read_optional_text(journal_path)) if summary else {}
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
    service = validate_service_name(getattr(args, "service", ""))
    remote_dir = f"{args.remote_base.rstrip('/')}/<run-id>"
    ssh_opts = ssh_options(args.ssh_option)
    return {
        "operation": "audit-snell",
        "dry_run": True,
        "target": host,
        "port": args.port,
        "service": service or "auto-discover unique *snell*.service",
        "local_out": str(args.out.expanduser()),
        "server_writes": f"creates and removes a temporary evidence dir under {args.remote_base}",
        "commands": [
            " ".join(["ssh", *ssh_opts, host, f"mkdir -m 700 -p {remote_dir}"]),
            " ".join(["scp", "-r", *ssh_opts, "<local-run>/.", f"{host}:{remote_dir}/"]),
            " ".join(["ssh", *ssh_opts, host, "bash payloads/snell_debian_payload.sh (read-only collection)"]),
            " ".join(["scp", "-r", *ssh_opts, f"{host}:{remote_dir}/.", "<local-run>/"]),
            " ".join(["ssh", *ssh_opts, host, f"rm -rf -- {remote_dir}"]),
        ],
    }


def run_audit_for_host(args: argparse.Namespace, host: str) -> tuple[dict[str, Any], int]:
    validate_port(args.port)
    validate_service_name(getattr(args, "service", ""))
    host = validate_host(host)
    local_dir, manifest = prepare_audit_run(args, host)

    upload_result = upload_audit_run(local_dir, manifest, args)
    if upload_result.returncode != 0:
        pack = build_evidence_pack(
            local_dir=local_dir,
            target=host,
            transport_status="failed",
            transport_error=upload_result.stderr or upload_result.stdout,
            persistent_effects=remote_dir_effect(manifest, uncertain=True),
        )
        return pack, upload_result.returncode or 1

    run_result = run_remote_audit(manifest, args)
    collect_result = collect_audit_run(local_dir, manifest, args)
    if collect_result.returncode != 0:
        pack = build_evidence_pack(
            local_dir=local_dir,
            target=host,
            transport_status="failed",
            transport_error=collect_result.stderr or collect_result.stdout,
            persistent_effects=remote_dir_effect(manifest),
        )
        return pack, collect_result.returncode or 1

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
        return pack, run_result.returncode or 1

    pack = build_evidence_pack(
        local_dir=local_dir,
        target=host,
        transport_status="ok",
        persistent_effects=persistent_effects,
    )
    if args.fail_on_issue and pack["status"] == "issue":
        return pack, 1
    return pack, 0


def command_audit_snell(args: argparse.Namespace) -> int:
    if getattr(args, "dry_run", False):
        validate_port(args.port)
        print_json(audit_plan(args, args.host))
        return 0
    pack, exit_code = run_audit_for_host(args, args.host)
    print_json(pack)
    return exit_code


def read_hosts_file(path: Path) -> list[str]:
    hosts: list[str] = []
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        hosts.append(stripped)
    if not hosts:
        raise CliError(f"no hosts found in {path}")
    return hosts


def command_audit_fleet(args: argparse.Namespace) -> int:
    hosts = read_hosts_file(args.hosts.expanduser())
    if getattr(args, "dry_run", False):
        validate_port(args.port)
        print_json({"operation": "audit-fleet", "dry_run": True, "hosts": [audit_plan(args, h) for h in hosts]})
        return 0
    results: list[dict[str, Any]] = []
    exit_code = 0
    for host in hosts:
        try:
            pack, host_exit = run_audit_for_host(args, host)
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
        "persistent_effects": [],
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
        return (
            isinstance(policy_result, dict)
            and bool(policy_result)
            and not policy_result.get("error")
            and not policy_result.get("errors")
        )
    if test_name == "external-ip":
        return isinstance(payload.get("address"), str) and bool(payload["address"].strip())
    if test_name == "nat":
        return payload.get("nat-type") is not None
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
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Snell port to probe (default {DEFAULT_PORT})")
    parser.add_argument(
        "--service",
        default="",
        help="systemd unit to audit; defaults to unique *snell*.service discovery",
    )
    parser.add_argument(
        "--journal-since", default=DEFAULT_JOURNAL_SINCE, help="journalctl --since window for the remote log scan"
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_LOCAL_ROOT, help="local directory for evidence run dirs")
    parser.add_argument("--run-id", help="fixed run id instead of a generated one")
    parser.add_argument(
        "--remote-base", default=DEFAULT_REMOTE_BASE, help="parent dir on the server for the temporary evidence dir"
    )
    parser.add_argument("--overwrite", action="store_true", help="overwrite an existing local run dir")
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
    audit.add_argument("--host", required=True, help="SSH target such as root@203.0.113.10")
    add_audit_common_args(audit)
    audit.set_defaults(func=command_audit_snell)

    fleet = subparsers.add_parser("audit-fleet", help="read-only SSH audit of hosts listed in a file")
    fleet.add_argument("--hosts", type=Path, required=True, help="file with one SSH target per line")
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
