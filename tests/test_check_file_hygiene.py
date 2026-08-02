from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "check-file-hygiene.py"
SPEC = importlib.util.spec_from_file_location("check_file_hygiene", SCRIPT)
assert SPEC and SPEC.loader
hygiene = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(hygiene)


@pytest.mark.parametrize(
    ("contents", "expected_issue"),
    [
        (b"", None),
        (b"content\n", None),
        (b"content\r\n", None),
        (b"content\r", "trailing whitespace"),
        (b"content", "exactly one line ending"),
        (b"content\n\n", "exactly one line ending"),
        (b"\n", "should be empty"),
        (b"content \n", "trailing whitespace"),
        (b"one\nsecond\t\n", "trailing whitespace"),
        (b"one\v\n", "trailing whitespace"),
    ],
)
def test_check_file_is_read_only(tmp_path: Path, contents: bytes, expected_issue: str | None) -> None:
    path = tmp_path / "file.txt"
    path.write_bytes(contents)

    issues = hygiene.check_file(path)

    assert path.read_bytes() == contents
    if expected_issue is None:
        assert issues == []
    else:
        assert any(expected_issue in issue for issue in issues)


def test_main_reports_all_files_without_modifying_them(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    clean = tmp_path / "clean.txt"
    dirty = tmp_path / "dirty.txt"
    clean.write_bytes(b"clean\n")
    dirty.write_bytes(b"dirty \n")

    assert hygiene.main([str(clean), str(dirty)]) == 1
    assert "trailing whitespace" in capsys.readouterr().out
    assert clean.read_bytes() == b"clean\n"
    assert dirty.read_bytes() == b"dirty \n"
