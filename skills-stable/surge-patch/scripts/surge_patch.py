#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///

"""Small run-dir based CLI for Surge/Snell VPS operations."""

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

SCHEMA_VERSION = "surge-patch.run.v1"
DEFAULT_LOCAL_ROOT = Path("/tmp/surge-patch-runs")
DEFAULT_REMOTE_BASE = "/var/tmp/surge-patch-runs"
DEFAULT_PORT = 14180
DEFAULT_JOURNAL_SINCE = "10 min ago"
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{7,79}$")
SAFE_REMOTE_PATH_RE = re.compile(r"^/[A-Za-z0-9._/@+-][A-Za-z0-9._/@+-]*(?:/[A-Za-z0-9._@+-]+)*$")
SNELL_VERSION_RE = re.compile(r"^[A-Za-z0-9._-]+$")

OPERATION_DEFS: dict[str, dict[str, Any]] = {
    "install-snell": {
        "target": "remote",
        "persistent": True,
        "persistent_effects": [
            "install_or_replace_/usr/local/bin/snell-server",
            "backup_and_replace_/etc/snell/snell-server.conf",
            "backup_and_replace_/etc/systemd/system/snell-server.service",
            "remove_incompatible_snell_systemd_hardening_dropins",
            "enable_and_restart_snell-server",
        ],
    },
    "audit-snell": {
        "target": "remote",
        "persistent": False,
        "persistent_effects": [],
    },
    "surge-smoke": {
        "target": "local",
        "persistent": False,
        "persistent_effects": [],
    },
}

SURGE_TEST_COMMANDS = {
    "tcp": ("test-policy",),
    "udp": ("test-policy-udp",),
    "external-ip": ("test-policy-external-ip",),
    "nat": ("test-policy-nat-type",),
}


class CliError(Exception):
    def __init__(self, message: str, exit_code: int = 2) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def utc_now() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_run_id() -> str:
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"sp-{stamp}-{uuid.uuid4().hex[:8]}"


def eprint(message: str) -> None:
    print(message, file=sys.stderr)


def print_json(data: dict[str, Any]) -> None:
    print(json.dumps(data, sort_keys=True, separators=(",", ":")))


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError as exc:
        raise CliError(f"missing file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise CliError(f"invalid JSON in {path}: {exc}") from exc


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    path.chmod(0o600)


def write_text(path: Path, text: str, mode: int = 0o600) -> None:
    path.write_text(text)
    path.chmod(mode)


def validate_run_id(run_id: str) -> None:
    if not RUN_ID_RE.match(run_id):
        raise CliError("run_id must be 8-80 safe characters: letters, digits, dot, underscore, hyphen")


def validate_host(host: str | None) -> str:
    if not host:
        raise CliError("--host is required for this operation")
    if any(char.isspace() for char in host):
        raise CliError("--host must not contain whitespace")
    return host


def validate_port(port: int) -> int:
    if port < 1 or port > 65535:
        raise CliError("--port must be between 1 and 65535")
    return port


def validate_snell_version(value: str | None, *, required: bool) -> str:
    if not value:
        if required:
            raise CliError("--snell-version is required for install-snell")
        return ""
    if not SNELL_VERSION_RE.match(value):
        raise CliError("--snell-version contains unsupported characters")
    return value


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


def shell_assign(name: str, value: str | int | bool | None) -> str:
    if value is True:
        text = "true"
    elif value is False or value is None:
        text = "false" if isinstance(value, bool) else ""
    else:
        text = str(value)
    return f"{name}={shlex.quote(text)}\n"


def payload_source() -> Path:
    path = Path(__file__).resolve().parent / "payloads" / "snell_debian_payload.sh"
    if not path.exists():
        raise CliError(f"missing private payload template: {path}")
    return path


def ensure_new_dir(path: Path, overwrite: bool) -> None:
    if path.exists():
        if not overwrite:
            raise CliError(f"run dir already exists: {path}")
        shutil.rmtree(path)
    path.mkdir(parents=True, mode=0o700)


def build_manifest(args: argparse.Namespace, run_id: str, operation_def: dict[str, Any]) -> dict[str, Any]:
    remote_dir = ""
    if operation_def["target"] == "remote":
        remote_base = args.remote_base.rstrip("/")
        remote_dir = validate_remote_path(f"{remote_base}/{run_id}")
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "operation": args.operation,
        "target": operation_def["target"],
        "persistent": operation_def["persistent"],
        "persistent_effects": operation_def["persistent_effects"],
        "created_at": utc_now(),
        "host": args.host or "",
        "remote_dir": remote_dir,
        "local_contract": {
            "stdout": "public CLI commands print one JSON object to stdout",
            "stderr": "progress and diagnostics only",
        },
    }


def build_input(args: argparse.Namespace, operation_def: dict[str, Any]) -> dict[str, Any]:
    params: dict[str, Any] = {
        "port": args.port,
        "snell_version": args.snell_version or "",
        "journal_since": args.journal_since,
    }
    if args.operation == "install-snell":
        params.update(
            {
                "name": args.name or "",
                "psk": args.psk or "",
                "replace_psk": args.replace_psk,
                "sha256": args.sha256 or "",
                "open_ufw": args.open_ufw,
                "ensure_swap": args.ensure_swap,
                "swap_size_gib": args.swap_size_gib,
            }
        )
    if args.operation == "surge-smoke":
        params.update(
            {
                "policy": args.policy or "",
                "host_ip": args.host_ip or "",
                "surge_cli": args.surge_cli or "",
                "tests": args.test,
                "probe_timeout_seconds": args.probe_timeout,
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "operation": args.operation,
        "target": operation_def["target"],
        "parameters": params,
    }


def build_input_env(input_doc: dict[str, Any]) -> str:
    params = input_doc["parameters"]
    lines = [
        "# Generated by surge_patch.py. Private payload input for this run directory.\n",
        shell_assign("SURGE_PATCH_OPERATION", input_doc["operation"]),
        shell_assign("SNELL_PORT", params.get("port", DEFAULT_PORT)),
        shell_assign("SNELL_VERSION", params.get("snell_version", "")),
        shell_assign("SNELL_JOURNAL_SINCE", params.get("journal_since", DEFAULT_JOURNAL_SINCE)),
        shell_assign("SNELL_NAME", params.get("name", "")),
        shell_assign("SNELL_PSK", params.get("psk", "")),
        shell_assign("SNELL_REPLACE_PSK", params.get("replace_psk", False)),
        shell_assign("SNELL_SHA256", params.get("sha256", "")),
        shell_assign("SNELL_OPEN_UFW", params.get("open_ufw", False)),
        shell_assign("SNELL_ENSURE_SWAP", params.get("ensure_swap", False)),
        shell_assign("SNELL_SWAP_SIZE_GIB", params.get("swap_size_gib", 4)),
    ]
    return "".join(lines)


def command_prepare(args: argparse.Namespace) -> int:
    operation_def = OPERATION_DEFS[args.operation]
    validate_port(args.port)
    validate_snell_version(args.snell_version, required=args.operation == "install-snell")
    if operation_def["target"] == "remote":
        args.host = validate_host(args.host)
    if operation_def["persistent"] and not args.confirm_persistent:
        effects = ", ".join(operation_def["persistent_effects"])
        raise CliError(f"{args.operation} is persistent; re-run with --confirm-persistent. Effects: {effects}")
    if args.operation == "surge-smoke" and not args.policy:
        raise CliError("--policy is required for surge-smoke")

    run_id = args.run_id or new_run_id()
    validate_run_id(run_id)
    local_dir = args.run_root.expanduser() / run_id
    ensure_new_dir(local_dir, args.overwrite)

    manifest = build_manifest(args, run_id, operation_def)
    input_doc = build_input(args, operation_def)
    write_json(local_dir / "manifest.json", manifest)
    write_json(local_dir / "input.json", input_doc)

    if operation_def["target"] == "remote":
        write_text(local_dir / "input.env", build_input_env(input_doc))
        payload_dir = local_dir / "payloads"
        payload_dir.mkdir(mode=0o700)
        shutil.copy2(payload_source(), payload_dir / "snell_debian_payload.sh")
        (payload_dir / "snell_debian_payload.sh").chmod(0o700)

    print_json(
        {
            "status": "prepared",
            "run_id": run_id,
            "operation": args.operation,
            "target": operation_def["target"],
            "persistent": operation_def["persistent"],
            "persistent_effects": operation_def["persistent_effects"],
            "local_dir": str(local_dir),
            "remote_dir": manifest["remote_dir"],
            "next": next_steps(manifest, local_dir),
        }
    )
    return 0


def next_steps(manifest: dict[str, Any], local_dir: Path) -> list[str]:
    if manifest["target"] == "local":
        return [
            f"uv run --script scripts/surge_patch.py run --run-dir {shlex.quote(str(local_dir))}",
            f"uv run --script scripts/surge_patch.py collect --run-dir {shlex.quote(str(local_dir))} --local-only",
        ]
    return [
        f"uv run --script scripts/surge_patch.py upload --run-dir {shlex.quote(str(local_dir))}",
        f"uv run --script scripts/surge_patch.py run --run-dir {shlex.quote(str(local_dir))}",
        f"uv run --script scripts/surge_patch.py collect --run-dir {shlex.quote(str(local_dir))}",
    ]


def load_manifest_from_run_dir(run_dir: Path) -> dict[str, Any]:
    return read_json(run_dir / "manifest.json")


def ssh_options(extra: list[str] | None) -> list[str]:
    options = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]
    for option in extra or []:
        options.extend(["-o", option])
    return options


def run_subprocess(command: list[str], *, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    eprint(f"+ {shlex.join(command)}")
    return subprocess.run(command, text=True, capture_output=True, timeout=timeout, check=False)


def command_upload(args: argparse.Namespace) -> int:
    run_dir = args.run_dir.expanduser()
    manifest = load_manifest_from_run_dir(run_dir)
    if manifest["target"] != "remote":
        raise CliError("upload only applies to remote run dirs")
    host = args.host or manifest["host"]
    remote_dir = validate_remote_path(args.remote_dir or manifest["remote_dir"])
    validate_host(host)

    parent = str(Path(remote_dir).parent)
    if args.overwrite:
        remote_prepare = (
            "set -eu; "
            f"mkdir -p {shlex.quote(parent)}; "
            f"rm -rf -- {shlex.quote(remote_dir)}; "
            f"mkdir -m 700 -p {shlex.quote(remote_dir)}"
        )
    else:
        remote_prepare = (
            "set -eu; "
            f"mkdir -p {shlex.quote(parent)}; "
            f"if [ -e {shlex.quote(remote_dir)} ]; then echo 'remote run dir exists' >&2; exit 17; fi; "
            f"mkdir -m 700 -p {shlex.quote(remote_dir)}"
        )

    ssh_cmd = ["ssh", *ssh_options(args.ssh_option), host, remote_prepare]
    ssh_result = run_subprocess(ssh_cmd)
    if ssh_result.returncode != 0:
        emit_process_failure("upload_prepare_failed", ssh_result)
        return ssh_result.returncode

    scp_cmd = ["scp", "-r", *ssh_options(args.ssh_option), f"{run_dir}/.", f"{host}:{remote_dir}/"]
    scp_result = run_subprocess(scp_cmd)
    status = "uploaded" if scp_result.returncode == 0 else "upload_failed"
    print_json(
        {
            "status": status,
            "run_id": manifest["run_id"],
            "host": host,
            "remote_dir": remote_dir,
            "ssh_return_code": scp_result.returncode,
            "stderr": scp_result.stderr,
        }
    )
    return 0 if scp_result.returncode == 0 else scp_result.returncode


def emit_process_failure(status: str, process: subprocess.CompletedProcess[str]) -> None:
    print_json(
        {
            "status": status,
            "return_code": process.returncode,
            "stdout": process.stdout,
            "stderr": process.stderr,
        }
    )


def command_run(args: argparse.Namespace) -> int:
    run_dir = args.run_dir.expanduser()
    manifest = load_manifest_from_run_dir(run_dir)
    if manifest["target"] == "local":
        return run_local_operation(run_dir, manifest, args)
    return run_remote_operation(run_dir, manifest, args)


def run_remote_operation(
    _run_dir: Path,
    manifest: dict[str, Any],
    args: argparse.Namespace,
) -> int:
    host = validate_host(args.host or manifest["host"])
    remote_dir = validate_remote_path(args.remote_dir or manifest["remote_dir"])
    remote_command = "\n".join(
        [
            "set -u",
            f"cd {shlex.quote(remote_dir)}",
            "umask 077",
            "mkdir -p logs",
            "date -u '+%Y-%m-%dT%H:%M:%SZ' > started_at",
            "{",
            '  echo "run_id=$(sed -n \'s/.*"run_id": *"\\([^"]*\\)".*/\\1/p\' manifest.json | head -1)"',
            '  echo "started_at=$(cat started_at)"',
            "} > logs/runner.log",
            "set +e",
            "RUN_DIR=$PWD bash payloads/snell_debian_payload.sh > stdout 2> stderr",
            "rc=$?",
            "set -e",
            "printf '%s\\n' \"$rc\" > exit_code",
            "date -u '+%Y-%m-%dT%H:%M:%SZ' > finished_at",
            'echo "exit_code=$rc" >> logs/runner.log',
            'echo "finished_at=$(cat finished_at)" >> logs/runner.log',
            'exit "$rc"',
        ]
    )
    ssh_cmd = ["ssh", *ssh_options(args.ssh_option), host, remote_command]
    result = run_subprocess(ssh_cmd, timeout=args.timeout)
    status = "ran" if result.returncode != 255 else "ssh_failed"
    print_json(
        {
            "status": status,
            "run_id": manifest["run_id"],
            "operation": manifest["operation"],
            "host": host,
            "remote_dir": remote_dir,
            "ssh_return_code": result.returncode,
            "remote_exit_code": None if result.returncode == 255 else result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "collect_hint": f"collect --run-dir {shlex.quote(str(args.run_dir))}",
        }
    )
    return result.returncode


def run_local_operation(run_dir: Path, manifest: dict[str, Any], args: argparse.Namespace) -> int:
    if manifest["operation"] != "surge-smoke":
        raise CliError(f"unsupported local operation: {manifest['operation']}")
    input_doc = read_json(run_dir / "input.json")
    params = input_doc["parameters"]
    logs_dir = run_dir / "logs"
    logs_dir.mkdir(exist_ok=True, mode=0o700)
    write_text(run_dir / "started_at", utc_now() + "\n")

    results = []
    exit_code = 0
    surge_cli = resolve_surge_cli(params.get("surge_cli", ""))
    for test_name in params["tests"]:
        result = run_surge_probe(
            surge_cli=surge_cli,
            policy=params["policy"],
            test_name=test_name,
            logs_dir=logs_dir,
            timeout=int(params["probe_timeout_seconds"]),
        )
        results.append(result)
        if result["status"] == "failed":
            exit_code = 1

    summary = {
        "status": "passed" if exit_code == 0 else "failed",
        "operation": "surge-smoke",
        "run_id": manifest["run_id"],
        "policy": params["policy"],
        "host_ip": params.get("host_ip", ""),
        "surge_cli": surge_cli,
        "results": results,
    }
    write_json(run_dir / "result.json", summary)
    write_text(run_dir / "stdout", json.dumps(summary, sort_keys=True, separators=(",", ":")) + "\n")
    write_text(run_dir / "stderr", "")
    write_text(run_dir / "exit_code", f"{exit_code}\n")
    write_text(run_dir / "finished_at", utc_now() + "\n")
    print_json(
        {
            "status": "ran",
            "run_id": manifest["run_id"],
            "operation": manifest["operation"],
            "exit_code": exit_code,
            "result_file": str(run_dir / "result.json"),
        }
    )
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
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
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
    status = "unsupported" if unsupported else "passed"
    if timed_out or rc != 0 or not json_ok:
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


def command_collect(args: argparse.Namespace) -> int:
    run_dir = args.run_dir.expanduser() if args.run_dir else None
    manifest = load_manifest_from_run_dir(run_dir) if run_dir else None

    if args.local_only:
        if not run_dir:
            raise CliError("--local-only requires --run-dir")
        collected_dir = run_dir
    else:
        if not manifest:
            if not args.run_id:
                raise CliError("--run-id is required when collecting without --run-dir")
            validate_run_id(args.run_id)
            manifest = {
                "run_id": args.run_id,
                "operation": args.operation or "",
                "target": "remote",
                "host": args.host or "",
                "remote_dir": args.remote_dir or f"{DEFAULT_REMOTE_BASE}/{args.run_id}",
            }
        if manifest["target"] == "local":
            if not run_dir:
                raise CliError("local collect requires --run-dir")
            collected_dir = run_dir
        else:
            host = validate_host(args.host or manifest["host"])
            remote_dir = validate_remote_path(args.remote_dir or manifest["remote_dir"])
            out_root = args.out_dir.expanduser()
            collected_dir = out_root / manifest["run_id"]
            ensure_new_dir(collected_dir, args.overwrite)
            scp_cmd = ["scp", "-r", *ssh_options(args.ssh_option), f"{host}:{remote_dir}/.", f"{collected_dir}/"]
            scp_result = run_subprocess(scp_cmd)
            if scp_result.returncode != 0:
                emit_process_failure("collect_failed", scp_result)
                return scp_result.returncode

    summary = summarize_collected_dir(collected_dir)
    print_json(summary)
    return collect_exit_status(summary["exit_code"])


def collect_exit_status(value: int | str | None) -> int:
    if value in ("", None, 0):
        return 0
    if isinstance(value, int):
        return value
    if value.isdigit():
        return int(value)
    return 1


def summarize_collected_dir(collected_dir: Path) -> dict[str, Any]:
    manifest = read_json(collected_dir / "manifest.json")
    result_path = collected_dir / "result.json"
    result = read_json(result_path) if result_path.exists() else {}
    exit_code_text = read_optional_text(collected_dir / "exit_code").strip()
    exit_code: int | str = int(exit_code_text) if exit_code_text.isdigit() else exit_code_text
    files = {
        "manifest": str(collected_dir / "manifest.json"),
        "input": str(collected_dir / "input.json"),
        "stdout": str(collected_dir / "stdout"),
        "stderr": str(collected_dir / "stderr"),
        "exit_code": str(collected_dir / "exit_code"),
        "result": str(result_path),
        "logs": sorted(str(path) for path in (collected_dir / "logs").glob("*"))
        if (collected_dir / "logs").exists()
        else [],
    }
    return {
        "status": "collected",
        "run_id": manifest["run_id"],
        "operation": manifest["operation"],
        "target": manifest["target"],
        "persistent": manifest["persistent"],
        "persistent_effects": manifest["persistent_effects"],
        "collected_dir": str(collected_dir),
        "exit_code": exit_code,
        "files": files,
        "result": result,
    }


def read_optional_text(path: Path) -> str:
    try:
        return path.read_text()
    except FileNotFoundError:
        return ""


def add_common_prepare_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--operation", choices=sorted(OPERATION_DEFS), required=True)
    parser.add_argument("--run-root", type=Path, default=DEFAULT_LOCAL_ROOT)
    parser.add_argument("--run-id")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--host", help="SSH target such as root@203.0.113.10 for remote operations")
    parser.add_argument("--remote-base", default=DEFAULT_REMOTE_BASE)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--snell-version")
    parser.add_argument("--journal-since", default=DEFAULT_JOURNAL_SINCE)
    parser.add_argument("--confirm-persistent", action="store_true", help="Required for persistent operations")
    parser.add_argument("--name", help="Snell instance name used in install output")
    parser.add_argument("--psk", help="Snell PSK; omit to reuse or generate on the VPS")
    parser.add_argument("--replace-psk", action="store_true", help="Persistent: generate a new PSK instead of reusing")
    parser.add_argument("--sha256", help="Expected sha256 of the Snell zip archive")
    parser.add_argument("--open-ufw", action="store_true", help="Persistent: allow Snell TCP/UDP in ufw")
    parser.add_argument("--ensure-swap", action="store_true", help="Persistent: create/activate a swap file if needed")
    parser.add_argument("--swap-size-gib", type=int, default=4)
    parser.add_argument("--policy", help="Surge policy name for surge-smoke")
    parser.add_argument("--host-ip", help="IP under test, recorded in surge-smoke output")
    parser.add_argument("--surge-cli", help="Path to surge-cli for surge-smoke")
    parser.add_argument("--probe-timeout", type=int, default=60)
    parser.add_argument(
        "--test",
        choices=sorted(SURGE_TEST_COMMANDS),
        action="append",
        default=[],
        help="Surge smoke test to run; defaults to tcp, udp, external-ip, nat",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="surge_patch.py",
        description="Prepare, upload, run, and collect recoverable Surge/Snell operation run dirs.",
        epilog=(
            "Persistent operation: install-snell installs or replaces the Snell binary, config, "
            "systemd service, removes incompatible hardening drop-ins, and restarts snell-server. "
            "Use --confirm-persistent when preparing it."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser(
        "prepare",
        help="create a local run dir and input files; prints JSON",
        description=(
            "Create a recoverable run dir. install-snell is persistent and requires "
            "--confirm-persistent; audit-snell and surge-smoke are read-only."
        ),
    )
    add_common_prepare_args(prepare)
    prepare.set_defaults(func=command_prepare)

    upload = subparsers.add_parser("upload", help="upload a prepared remote run dir; prints JSON")
    upload.add_argument("--run-dir", type=Path, required=True)
    upload.add_argument("--host")
    upload.add_argument("--remote-dir")
    upload.add_argument("--overwrite", action="store_true")
    upload.add_argument("--ssh-option", action="append", default=[])
    upload.set_defaults(func=command_upload)

    run = subparsers.add_parser("run", help="execute a prepared run dir locally or remotely; prints JSON")
    run.add_argument("--run-dir", type=Path, required=True)
    run.add_argument("--host")
    run.add_argument("--remote-dir")
    run.add_argument("--timeout", type=int, default=900)
    run.add_argument("--ssh-option", action="append", default=[])
    run.set_defaults(func=command_run)

    collect = subparsers.add_parser("collect", help="collect run-dir outputs and summarize them as JSON")
    collect.add_argument("--run-dir", type=Path)
    collect.add_argument("--run-id")
    collect.add_argument("--operation")
    collect.add_argument("--host")
    collect.add_argument("--remote-dir")
    collect.add_argument("--out-dir", type=Path, default=Path("/tmp/surge-patch-collected"))
    collect.add_argument("--local-only", action="store_true")
    collect.add_argument("--overwrite", action="store_true")
    collect.add_argument("--ssh-option", action="append", default=[])
    collect.set_defaults(func=command_collect)
    return parser


def normalize_args(args: argparse.Namespace) -> None:
    if getattr(args, "command", "") == "prepare" and not args.test:
        args.test = ["tcp", "udp", "external-ip", "nat"]


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    normalize_args(args)
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
