from __future__ import annotations

import os
import subprocess
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
SENDER = SKILL_ROOT / "scripts" / "brrr-send.sh"
UNIT_NOTIFIER = SKILL_ROOT / "scripts" / "notify-brrr-unit.sh"
SYSTEMD_PATTERN = SKILL_ROOT / "references" / "systemd-pattern.md"


def run_sender(
    tmp_path: Path,
    *,
    secret: str | None,
    exe_dev: bool,
    http_status: int = 202,
    extra_args: list[str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], str]:
    marker = tmp_path / "shelley.json"
    if exe_dev:
        marker.write_text("{}\n")

    sender = tmp_path / "brrr-send.sh"
    sender.write_text(SENDER.read_text().replace("/exe.dev/shelley.json", str(marker)))
    sender.chmod(0o755)

    curl_args = tmp_path / "curl.args"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_curl = bin_dir / "curl"
    fake_curl.write_text(
        '#!/bin/bash\nprintf "%s\\n" "$@" >"$BRRR_TEST_CURL_ARGS"\nprintf "%s" "$BRRR_TEST_HTTP_STATUS"\n'
    )
    fake_curl.chmod(0o755)

    home = tmp_path / "home"
    home.mkdir()
    env: dict[str, str] = dict(os.environ)
    env.update(
        {
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "HOME": str(home),
            "BRRR_TEST_CURL_ARGS": str(curl_args),
            "BRRR_TEST_HTTP_STATUS": str(http_status),
        }
    )
    env.pop("BRRR_ENV_FILE", None)
    if secret is None:
        env.pop("BRRR_SECRET", None)
    else:
        env["BRRR_SECRET"] = secret

    result = subprocess.run(
        [str(sender), "--title", "test", "--message", "test", *(extra_args or [])],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    return result, curl_args.read_text() if curl_args.exists() else ""


def test_explicit_secret_wins_over_exe_dev_proxy(tmp_path: Path) -> None:
    result, curl_args = run_sender(tmp_path, secret="test-secret", exe_dev=True)

    assert result.returncode == 0
    assert result.stdout == "auth_mode=bearer\nhttp_status=202\n"
    assert "https://api.brrr.now/v1/send" in curl_args
    assert "Authorization: Bearer test-secret" in curl_args
    assert "brrr.int.exe.xyz" not in curl_args


def test_exe_dev_proxy_is_fallback_without_secret(tmp_path: Path) -> None:
    result, curl_args = run_sender(tmp_path, secret=None, exe_dev=True)

    assert result.returncode == 0
    assert result.stdout == "auth_mode=exe.dev-proxy\nhttp_status=202\n"
    assert "https://brrr.int.exe.xyz/v1/send" in curl_args
    assert "Authorization:" not in curl_args


def test_sender_includes_notification_content_fields(tmp_path: Path) -> None:
    result, curl_args = run_sender(
        tmp_path,
        secret="test-secret",
        exe_dev=False,
        extra_args=[
            "--subtitle",
            "production host",
            "--image-url",
            "https://example.invalid/image.png",
            "--expiration-date",
            "2026-07-13T18:00:00Z",
            "--filter-criteria",
            "host=ci-01",
        ],
    )

    assert result.returncode == 0
    assert '"subtitle":"production host"' in curl_args
    assert '"image_url":"https://example.invalid/image.png"' in curl_args
    assert '"expiration_date":"2026-07-13T18:00:00Z"' in curl_args
    assert '"filter_criteria":"host=ci-01"' in curl_args


def test_sender_rejects_expiration_without_timezone(tmp_path: Path) -> None:
    result, _curl_args = run_sender(
        tmp_path,
        secret="test-secret",
        exe_dev=False,
        extra_args=["--expiration-date", "2026-07-13T18:00:00"],
    )

    assert result.returncode == 2
    assert "expiration_date must be an ISO 8601 date and time with a timezone" in result.stderr


def run_unit_notifier(
    tmp_path: Path, *, argument: str, monitor_unit: str | None
) -> tuple[subprocess.CompletedProcess[str], str]:
    sender_args = tmp_path / "sender.args"
    fake_sender = tmp_path / "brrr-send"
    fake_sender.write_text('#!/bin/bash\nprintf "%s\\n" "$@" >"$BRRR_TEST_SENDER_ARGS"\n')
    fake_sender.chmod(0o755)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_systemctl = bin_dir / "systemctl"
    fake_systemctl.write_text('#!/bin/bash\nprintf "LoadState=loaded\\nActiveState=failed\\nSubState=failed\\n"\n')
    fake_systemctl.chmod(0o755)

    env: dict[str, str] = dict(os.environ)
    env.update(
        {
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "BRRR_SENDER": str(fake_sender),
            "BRRR_TEST_SENDER_ARGS": str(sender_args),
        }
    )
    if monitor_unit is None:
        env.pop("MONITOR_UNIT", None)
    else:
        env["MONITOR_UNIT"] = monitor_unit

    result = subprocess.run([str(UNIT_NOTIFIER), argument], capture_output=True, text=True, check=False, env=env)
    return result, sender_args.read_text() if sender_args.exists() else ""


def test_systemd_service_handler_prefers_exact_monitor_unit(tmp_path: Path) -> None:
    result, sender_args = run_unit_notifier(tmp_path, argument="worker-blue", monitor_unit="worker@blue.service")

    assert result.returncode == 0
    assert ": worker@blue.service failed" in sender_args
    assert "systemd unit" in sender_args
    assert "Inspect its journal before restarting." in sender_args
    assert "systemd-" in sender_args
    assert "-worker@blue.service" in sender_args
    assert "worker-blue" not in sender_args


def test_systemd_non_service_handler_uses_full_argument(tmp_path: Path) -> None:
    result, sender_args = run_unit_notifier(tmp_path, argument="backup.timer", monitor_unit=None)

    assert result.returncode == 0
    assert ": backup.timer failed" in sender_args
    assert "systemd unit" in sender_args


def test_systemd_handler_rejects_lossy_fallback_identity(tmp_path: Path) -> None:
    result, sender_args = run_unit_notifier(tmp_path, argument="worker-blue", monitor_unit=None)

    assert result.returncode == 2
    assert sender_args == ""
    assert result.stderr == "expected a complete systemd unit name when MONITOR_UNIT is unavailable\n"


def test_systemd_pattern_uses_source_specific_handler_forms() -> None:
    pattern = SYSTEMD_PATTERN.read_text()

    assert "OnFailure=notify-brrr@%n.service" in pattern
    assert "OnFailure=notify-brrr@%p-%i.service" in pattern
    assert "OnFailure=notify-brrr@%p.service" not in pattern
    assert 'journalctl -u "$unit"' not in UNIT_NOTIFIER.read_text()


def test_non_2xx_status_does_not_print_success_receipt(tmp_path: Path) -> None:
    result, _curl_args = run_sender(tmp_path, secret="test-secret", exe_dev=False, http_status=302)

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == "brrr returned unexpected HTTP status: 302\n"
