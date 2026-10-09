from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("lint_excludes", ROOT / "scripts/lint-excludes.py")
assert SPEC and SPEC.loader
excludes = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(excludes)


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    for name in {block[0] for block in excludes.BLOCKS} | {".metadata.json"}:
        shutil.copyfile(ROOT / name, tmp_path / name)
    return tmp_path


def contents(root: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in root.iterdir()}


def assert_biome_format_stable(checkout: Path) -> None:
    shutil.copyfile(ROOT / ".gitignore", checkout / ".gitignore")
    config_path = checkout / "biome.jsonc"
    expected = config_path.read_bytes()
    subprocess.run(["biome", "format", "--write", "biome.jsonc"], cwd=checkout, check=True, capture_output=True)
    assert config_path.read_bytes() == expected


def test_check_is_read_only(checkout: Path) -> None:
    before = contents(checkout)
    assert excludes.sync_excludes(checkout) == []
    assert contents(checkout) == before


def test_package_changes_regenerate_all_configs(checkout: Path) -> None:
    path = checkout / ".metadata.json"
    metadata = json.loads(path.read_text())
    del metadata["entries"]["skills-beta/cascade"]
    metadata["entries"]["vendor/example.v2"] = {}
    metadata["entries"]["_ignored-package"] = {}
    path.write_text(json.dumps(metadata))
    before = contents(checkout)

    assert len(excludes.sync_excludes(checkout)) == 6
    assert contents(checkout) == before
    assert len(excludes.sync_excludes(checkout, write=True)) == 6
    assert excludes.sync_excludes(checkout) == []

    for name in before.keys() - {".metadata.json"}:
        source = (checkout / name).read_text()
        assert "vendor/example.v2" in source or r"vendor/example\\.v2" in source
        assert "skills-beta/cascade" not in source
        assert "_ignored-package" not in source

    typos = tomllib.loads((checkout / ".typos.toml").read_text())
    assert ".metadata.json" in typos["files"]["extend-exclude"]
    project = tomllib.loads((checkout / "pyproject.toml").read_text())
    for tool in ["ruff", "ty", "tombi"]:
        config = project["tool"][tool]
        rules = config["src"] if tool == "ty" else config["files"] if tool == "tombi" else config
        assert any(value.startswith("vendor/example.v2/") for value in rules["exclude"])
    prek = tomllib.loads((checkout / "prek.toml").read_text().split("[[repos]]")[0])
    assert re.search(prek["exclude"], "vendor/example.v2/SKILL.md")
    assert not re.search(prek["exclude"], "vendor/exampleXv2/SKILL.md")


def test_missing_marker_leaves_all_files_untouched(checkout: Path) -> None:
    path = checkout / "prek.toml"
    path.write_text(path.read_text().replace("END GENERATED LINT EXCLUDES: prek", "missing marker"))
    before = contents(checkout)
    with pytest.raises(ValueError, match=r"prek\.toml"):
        excludes.sync_excludes(checkout, write=True)
    assert contents(checkout) == before


def test_no_external_packages_does_not_exclude_repository_files(checkout: Path) -> None:
    (checkout / ".metadata.json").write_text(json.dumps({"entries": {"_local": {}}}))
    excludes.sync_excludes(checkout, write=True)
    prek = tomllib.loads((checkout / "prek.toml").read_text().split("[[repos]]")[0])
    assert not re.search(prek["exclude"], "scripts/lint.sh")
    assert not re.search(prek["exclude"], "README.md")
    assert "    []\n" in (checkout / ".markdownlint-cli2.yaml").read_text()
    assert excludes.sync_excludes(checkout) == []
    assert_biome_format_stable(checkout)
    (checkout / "README.md").write_text("# Fixture\n")
    subprocess.run(
        ["markdownlint-cli2", "--config", ".markdownlint-cli2.yaml", "README.md"],
        cwd=checkout,
        check=True,
        capture_output=True,
    )


def test_generated_biome_config_survives_formatter(checkout: Path) -> None:
    metadata_path = checkout / ".metadata.json"
    metadata = json.loads(metadata_path.read_text())
    metadata["entries"]["vendor/new-package"] = {}
    metadata_path.write_text(json.dumps(metadata))
    excludes.sync_excludes(checkout, write=True)
    assert_biome_format_stable(checkout)
