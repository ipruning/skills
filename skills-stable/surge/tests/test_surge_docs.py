from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRIAGE = ROOT / "references" / "macos-network-triage.md"
OPERATOR_ACTIONS = ROOT / "references" / "macos-surge-operator-actions.md"
SKILL = ROOT / "SKILL.md"
COMPAT_AUDIT = ROOT / "scripts" / "snell_audit.py"
SING_BOX_MACOS = ROOT.parent / "sing-box-reality-hy2" / "references" / "macos-client.md"


def test_triage_keeps_write_actions_in_operator_reference():
    triage_text = TRIAGE.read_text()
    operator_text = OPERATOR_ACTIONS.read_text()

    assert "xh POST" not in triage_text
    assert "export http_proxy" not in triage_text
    assert "unset http_proxy" not in triage_text
    assert "xh --verify no POST" in operator_text
    assert "export http_proxy" in operator_text


def test_snell_routes_to_its_own_skill():
    skill_text = SKILL.read_text()
    sing_box_macos_text = SING_BOX_MACOS.read_text()

    assert "$operate-snell" in skill_text
    assert "audit-snell" not in skill_text
    assert "audit-fleet" not in skill_text
    assert "health and repair remain owned by `$operate-snell`" in sing_box_macos_text
    assert "health and repair remain owned by the `surge` skill" not in sing_box_macos_text


def test_legacy_snell_cli_forwards_to_new_owner():
    result = subprocess.run(
        [sys.executable, str(COMPAT_AUDIT), "--help"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "audit-snell" in result.stdout
    assert "audit-fleet" in result.stdout
