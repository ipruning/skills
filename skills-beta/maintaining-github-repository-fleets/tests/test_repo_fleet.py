from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

SCRIPT = Path(__file__).parents[1] / "scripts" / "repo_fleet.py"
SPEC = importlib.util.spec_from_file_location("repo_fleet", SCRIPT)
assert SPEC and SPEC.loader
fleet = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fleet)


class FakeRunner:
    def __init__(self, responses: dict[tuple[str, ...], str] | None = None, delegate: Any | None = None) -> None:
        self.responses = responses or {}
        self.delegate = delegate
        self.calls: list[tuple[str, ...]] = []
        self.invocations: list[dict[str, Any]] = []

    def __call__(
        self,
        argv: list[str] | tuple[str, ...],
        cwd: Path | None = None,
        *,
        env: dict[str, str] | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        key = tuple(argv)
        self.calls.append(key)
        self.invocations.append({"argv": key, "cwd": cwd, "env": env, "check": check})
        if key not in self.responses:
            if self.delegate is not None:
                return self.delegate(argv, cwd, env=env, check=check)
            raise fleet.CommandError(f"unexpected: {key}")
        return subprocess.CompletedProcess(argv, 0, self.responses[key], "")


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, text=True, capture_output=True).stdout.strip()


def init_repo(path: Path, remote: str | None = None) -> None:
    path.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(path)], check=True, capture_output=True)
    git(path, "config", "user.email", "test@example.com")
    git(path, "config", "user.name", "Test")
    (path / "file").write_text("one")
    git(path, "add", "file")
    git(path, "commit", "-m", "one")
    if remote:
        git(path, "remote", "add", "origin", remote)


def test_discovery_direct_children_no_origin_and_remote_separation(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    init_repo(repo)
    git(repo, "remote", "add", "upstream", "https://github.com/up/project.git")
    nested = tmp_path / "container" / "nested"
    nested.parent.mkdir()
    init_repo(nested)
    found = {item["name"]: item for item in fleet.discover_children(tmp_path)}
    assert found["repo"]["origin_repo"] is None
    assert found["repo"]["upstream_repo"] == ("up", "project")
    assert found["container"]["kind"] == "non_repo"


def test_git_file_worktree_is_never_managed(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    init_repo(primary)
    worktree = tmp_path / "worktree"
    git(primary, "worktree", "add", "-b", "other", str(worktree))
    item = next(item for item in fleet.discover_children(tmp_path) if item["name"] == "worktree")
    assert item["kind"] == "external_gitdir"


def test_workspace_plan_clone_ff_archived_empty_and_no_mutations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local = tmp_path / "local"
    init_repo(local, "https://github.com/acme/local.git")
    head = git(local, "rev-parse", "HEAD")
    monkeypatch.setattr(
        fleet,
        "remote_inventory",
        lambda *_: [
            {"name": "new", "isArchived": False, "defaultBranchRef": {"name": "main"}},
            {"name": "local", "isArchived": False, "defaultBranchRef": {"name": "main"}},
            {"name": "old", "isArchived": True, "defaultBranchRef": {"name": "main"}},
            {"name": "empty", "isArchived": False, "defaultBranchRef": None},
        ],
    )
    monkeypatch.setattr(fleet, "exact_remote_sha", lambda *_: "f" * 40)
    monkeypatch.setattr(
        fleet,
        "repository_state",
        lambda *_: {
            "head": head,
            "branch": "main",
            "clean": True,
            "tracking": "origin/main",
            "operation_in_progress": False,
            "eligible": True,
        },
    )
    monkeypatch.setattr(fleet, "cached_relation", lambda *_: "unknown_until_fetch")
    runner = FakeRunner(delegate=fleet.run_command)
    plan = fleet.make_workspace_plan("acme", "me", tmp_path, True, [], ["clone", "fast-forward"], runner)
    assert {action["kind"] for action in plan["actions"]} == {"clone_workspace", "fast_forward_workspace"}
    assert {item["reason"] for item in plan["blocked"]} >= {"archived", "empty_repository"}
    assert not any(set(call) & fleet.MUTATING_GIT_WORDS for call in runner.calls)
    fleet.validate_plan(plan)


def test_audit_plan_reports_missing_requested_repo_and_validates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        fleet,
        "remote_inventory",
        lambda *_: [{"name": "found", "isArchived": False, "defaultBranchRef": {"name": "main"}}],
    )
    monkeypatch.setattr(fleet, "exact_remote_sha", lambda *_: "f" * 40)
    plan = fleet.make_audit_plan("acme", "planned", tmp_path, False, ["found", "Typo"], "shallow")
    assert [action["name"] for action in plan["actions"]] == ["found"]
    assert {"name": "Typo", "reason": "not_found_case_sensitive"} in plan["blocked"]
    fleet.validate_plan(plan)


def test_repository_state_rejects_dirty_detached_and_in_progress(tmp_path: Path) -> None:
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    source = tmp_path / "source"
    init_repo(source, str(remote))
    git(source, "push", "-u", "origin", "main")
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "--branch", "main", str(remote), str(clone)], check=True, capture_output=True)
    assert fleet.repository_state(clone, "main")["eligible"] is True
    (clone / "untracked").write_text("dirty")
    assert fleet.repository_state(clone, "main")["eligible"] is False
    (clone / "untracked").unlink()
    git(clone, "checkout", "--detach")
    assert fleet.repository_state(clone, "main")["eligible"] is False
    git(clone, "checkout", "main")
    (clone / ".git" / "MERGE_HEAD").write_text("0" * 40)
    assert fleet.repository_state(clone, "main")["eligible"] is False


def minimal_plan(tmp_path: Path, action: dict[str, Any] | None = None) -> dict[str, Any]:
    plan = fleet.base_plan(
        "workspace-sync",
        "acme",
        "me",
        tmp_path,
        {"mode": "all"},
        {"allowed_actions": ["clone"]},
        [action] if action else [],
        [],
        [],
    )
    return plan


def test_plan_hash_tamper_and_confirmation_precede_mutation(tmp_path: Path) -> None:
    plan = minimal_plan(tmp_path)
    plan["owner"] = "evil"
    with pytest.raises(Exception, match="hash"):
        fleet.validate_plan(plan)
    path = tmp_path / "plan.json"
    valid = minimal_plan(tmp_path)
    path.write_bytes(fleet.canonical_bytes(valid))
    result = CliRunner().invoke(
        fleet.app,
        [
            "apply",
            str(path),
            "--confirm-owner",
            "wrong",
            "--confirm-plan-sha256",
            valid["plan_sha256"],
            "--result",
            str(tmp_path / "result"),
        ],
    )
    assert result.exit_code != 0
    assert not (tmp_path / "result").exists()


def test_stale_ff_does_not_fetch_or_merge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    action = {
        "kind": "fast_forward_workspace",
        "name": "repo",
        "target": str(tmp_path),
        "default_branch": "main",
        "expected_local_sha": "a",
        "expected_remote_sha": "b",
    }
    monkeypatch.setattr(fleet, "precondition_ff", lambda *_: (False, {"head": "changed"}))
    runner = FakeRunner()
    status, _ = fleet.apply_ff(action, "acme", "me", runner)
    assert status == "stale"
    assert runner.calls == []


@pytest.mark.parametrize("relation", ["ahead", "diverged", "unrelated"])
def test_workspace_plan_blocks_known_non_fast_forward(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, relation: str
) -> None:
    local = tmp_path / "local"
    init_repo(local, "https://github.com/acme/local.git")
    head = git(local, "rev-parse", "HEAD")
    monkeypatch.setattr(
        fleet,
        "remote_inventory",
        lambda *_: [{"name": "local", "isArchived": False, "defaultBranchRef": {"name": "main"}}],
    )
    monkeypatch.setattr(fleet, "exact_remote_sha", lambda *_: "f" * 40)
    monkeypatch.setattr(
        fleet,
        "repository_state",
        lambda *_: {
            "head": head,
            "branch": "main",
            "clean": True,
            "tracking": "origin/main",
            "operation_in_progress": False,
            "eligible": True,
        },
    )
    monkeypatch.setattr(fleet, "cached_relation", lambda *_: relation)
    plan = fleet.make_workspace_plan("acme", "me", tmp_path, True, [], ["fast-forward"])
    assert plan["actions"] == []
    assert any(item["reason"] == relation for item in plan["blocked"])


def test_exact_fast_forward_happy_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    source = tmp_path / "source"
    init_repo(source, str(remote))
    git(source, "push", "-u", "origin", "main")
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "--branch", "main", str(remote), str(clone)], check=True, capture_output=True)
    old = git(clone, "rev-parse", "HEAD")
    (source / "file").write_text("two")
    git(source, "commit", "-am", "two")
    git(source, "push")
    new = git(source, "rev-parse", "HEAD")
    action = {
        "name": "repo",
        "target": str(clone),
        "default_branch": "main",
        "expected_local_sha": old,
        "expected_remote_sha": new,
    }
    monkeypatch.setattr(fleet, "gh_env", lambda *_: {})
    monkeypatch.setattr(fleet, "parse_github_remote", lambda *_: ("acme", "repo"))
    status, after = fleet.apply_ff(action, "acme", "me", fleet.run_command)
    assert status == "updated_verified"
    assert after["head"] == new


def test_lease_guard_release_and_symlink(tmp_path: Path) -> None:
    arbitrary = tmp_path / "arbitrary"
    arbitrary.mkdir()
    with pytest.raises(fleet.typer.BadParameter):
        fleet.make_release_plan(arbitrary)
    lease = tmp_path / "lease"
    lease.mkdir()
    marker = {
        "schema_version": 1,
        "owner": "acme",
        "repo": "x",
        "resolved_path": str(lease.resolve()),
        "plan_sha256": "a" * 64,
    }
    fleet.write_atomic(lease / ".repo-fleet-lease.json", marker)
    plan = fleet.make_release_plan(lease)
    fleet.validate_plan(plan)
    link = tmp_path / "link"
    link.symlink_to(lease, target_is_directory=True)
    with pytest.raises(fleet.typer.BadParameter):
        fleet.make_release_plan(link)
    status, _ = fleet.apply_release(plan["actions"][0])
    assert status == "released_verified"
    assert not lease.exists()


def test_result_checkpoint_resume(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    action = {"kind": "clone_workspace", "name": "x", "target": str(tmp_path / "x")}
    plan = minimal_plan(tmp_path, action)
    calls = 0

    def fake_apply(*_: object) -> tuple[str, dict[str, str]]:
        nonlocal calls
        calls += 1
        return "cloned_verified", {"head": "a"}

    monkeypatch.setattr(fleet, "apply_clone", fake_apply)
    monkeypatch.setattr(fleet, "verified_action_still_holds", lambda *_: True)
    result_path = tmp_path / "result.json"
    fleet.execute(plan, result_path)
    fleet.execute(plan, result_path)
    assert calls == 1
    assert json.loads(result_path.read_text())["items"]["0"]["status"] == "cloned_verified"


def test_stdout_is_one_json_object_for_empty_apply(tmp_path: Path) -> None:
    managed = tmp_path / "managed"
    managed.mkdir()
    plan = minimal_plan(managed)
    path = tmp_path / "plan.json"
    path.write_bytes(fleet.canonical_bytes(plan))
    result = CliRunner().invoke(
        fleet.app,
        [
            "apply",
            str(path),
            "--confirm-owner",
            "acme",
            "--confirm-plan-sha256",
            plan["plan_sha256"],
            "--result",
            str(tmp_path / "result"),
        ],
    )
    assert result.exit_code == 0
    assert isinstance(json.loads(result.stdout), dict)
    assert result.stdout.count("\n") == 1


def test_authenticated_inventory_uses_env_without_token_in_argv() -> None:
    token_call = ("gh", "auth", "token", "--user", "planned")
    inventory_call = (
        "gh",
        "repo",
        "list",
        "acme",
        "--limit",
        str(fleet.INVENTORY_LIMIT),
        "--json",
        "name,nameWithOwner,url,visibility,isArchived,isFork,parent,defaultBranchRef,diskUsage",
    )
    runner = FakeRunner({token_call: "secret-token\n", inventory_call: "[]\n"})
    assert fleet.remote_inventory("acme", "planned", runner) == []
    invocation = runner.invocations[-1]
    assert invocation["env"]["GH_TOKEN"] == "secret-token"
    assert "secret-token" not in invocation["argv"]
    assert not any(call[:3] == ("gh", "auth", "switch") for call in runner.calls)


def test_remote_parser_requires_actual_github_host() -> None:
    assert fleet.parse_github_remote("https://github.com/acme/repo.git") == ("acme", "repo")
    assert fleet.parse_github_remote("ssh://git@github.com/acme/repo.git") == ("acme", "repo")
    assert fleet.parse_github_remote("git@github.com:acme/repo.git") == ("acme", "repo")
    assert fleet.parse_github_remote("https://mirror.example/github.com/acme/repo.git") is None
    assert fleet.parse_github_remote("https://github.com.evil.example/acme/repo.git") is None


def test_inventory_refuses_possible_limit_truncation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fleet, "INVENTORY_LIMIT", 2)
    token_call = ("gh", "auth", "token", "--user", "planned")
    inventory_call = (
        "gh",
        "repo",
        "list",
        "acme",
        "--limit",
        "2",
        "--json",
        "name,nameWithOwner,url,visibility,isArchived,isFork,parent,defaultBranchRef,diskUsage",
    )
    runner = FakeRunner({token_call: "secret-token\n", inventory_call: '[{"name":"a"},{"name":"b"}]\n'})
    with pytest.raises(fleet.CommandError, match="partial plan"):
        fleet.remote_inventory("acme", "planned", runner)


def test_valid_hash_cannot_authorize_path_escape(tmp_path: Path) -> None:
    action = {
        "kind": "clone_workspace",
        "name": "safe",
        "target": str(tmp_path.parent / "escaped"),
        "default_branch": "main",
        "expected_remote_sha": "a" * 40,
    }
    plan = minimal_plan(tmp_path, action)
    with pytest.raises(fleet.typer.BadParameter, match="direct child"):
        fleet.validate_plan(plan)
    assert not (tmp_path.parent / "escaped").exists()


def test_valid_hash_cannot_authorize_symlink_checkout(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    target = tmp_path / "safe"
    target.symlink_to(outside, target_is_directory=True)
    action = {
        "kind": "fast_forward_workspace",
        "name": "safe",
        "target": str(target),
        "default_branch": "main",
        "expected_local_sha": "a" * 40,
        "expected_remote_sha": "b" * 40,
        "relationship": "unknown_until_fetch",
    }
    plan = minimal_plan(tmp_path, action)
    with pytest.raises(fleet.typer.BadParameter, match="escapes"):
        fleet.validate_plan(plan)


def test_canonical_redirect_blocks_duplicate_clone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    old = tmp_path / "old-name"
    init_repo(old, "https://github.com/acme/old-name.git")
    monkeypatch.setattr(
        fleet,
        "remote_inventory",
        lambda *_: [{"name": "new-name", "isArchived": False, "defaultBranchRef": {"name": "main"}}],
    )
    monkeypatch.setattr(fleet, "canonical_remote", lambda *_: ("acme", "new-name"))
    monkeypatch.setattr(fleet, "exact_remote_sha", lambda *_: "a" * 40)
    plan = fleet.make_workspace_plan("acme", "planned", tmp_path, True, [], ["clone"], fleet.run_command)
    assert plan["actions"] == []
    assert any(item["reason"] == "name_mismatch" for item in plan["blocked"])


def test_merge_base_exit_one_is_stale(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    action = {
        "name": "repo",
        "target": str(tmp_path),
        "default_branch": "main",
        "expected_local_sha": "a",
        "expected_remote_sha": "b",
    }
    monkeypatch.setattr(fleet, "precondition_ff", lambda *_: (True, {}))
    monkeypatch.setattr(fleet, "gh_env", lambda *_: {})

    def runner(
        argv: list[str] | tuple[str, ...],
        cwd: Path | None = None,
        *,
        env: dict[str, str] | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        del cwd, env
        if "merge-base" in argv:
            assert check is False
            return subprocess.CompletedProcess(argv, 1, "", "")
        if "rev-parse" in argv:
            return subprocess.CompletedProcess(argv, 0, "b\n", "")
        return subprocess.CompletedProcess(argv, 0, "", "")

    status, evidence = fleet.apply_ff(action, "acme", "planned", runner)
    assert status == "stale"
    assert evidence["reason"] == "not_fast_forward"


def test_fast_forward_rechecks_origin_before_network_mutation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    init_repo(repo, "https://github.com/other/repo.git")
    monkeypatch.setattr(
        fleet,
        "repository_state",
        lambda *_: {
            "head": "a" * 40,
            "branch": "main",
            "clean": True,
            "tracking": "origin/main",
            "operation_in_progress": False,
            "eligible": True,
        },
    )
    action = {
        "kind": "fast_forward_workspace",
        "name": "repo",
        "target": str(repo),
        "default_branch": "main",
        "expected_local_sha": "a" * 40,
        "expected_remote_sha": "b" * 40,
        "relationship": "unknown_until_fetch",
    }
    status, evidence = fleet.apply_ff(action, "acme", "planned", fleet.run_command)
    assert status == "stale"
    assert evidence["origin"] == "https://github.com/other/repo.git"


def test_scope_and_policy_are_bound_by_plan_hash(tmp_path: Path) -> None:
    plan = minimal_plan(tmp_path)
    plan["scope"] = {"mode": "repos", "repos": ["repo"]}
    with pytest.raises(fleet.typer.BadParameter, match="hash"):
        fleet.validate_plan(plan)


def test_valid_hash_cannot_authorize_refspec_or_policy_mismatch(tmp_path: Path) -> None:
    target = tmp_path / "repo"
    target.mkdir()
    action = {
        "kind": "fast_forward_workspace",
        "name": "repo",
        "target": str(target),
        "default_branch": "main:refs/heads/injected",
        "expected_local_sha": "a" * 40,
        "expected_remote_sha": "b" * 40,
        "relationship": "unknown_until_fetch",
    }
    plan = fleet.base_plan(
        "workspace-sync",
        "acme",
        "planned",
        tmp_path,
        {"mode": "repos", "repos": ["repo"]},
        {"allowed_actions": ["clone"]},
        [action],
        [],
        [],
    )
    with pytest.raises(fleet.typer.BadParameter, match="branch|policy"):
        fleet.validate_plan(plan)


def test_materialize_uses_owned_lease_and_detaches_exact_head(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source"
    init_repo(source)
    expected = git(source, "rev-parse", "HEAD")
    lease = tmp_path / "leases" / f"repo-{expected[:12]}"
    lease.parent.mkdir()
    action = {
        "kind": "materialize_audit",
        "name": "repo",
        "target": str(lease),
        "default_branch": "main",
        "history": "full",
        "expected_remote_sha": expected,
    }
    monkeypatch.setattr(fleet, "gh_env", lambda *_: {"GH_TOKEN": "secret"})

    def runner(
        argv: list[str] | tuple[str, ...],
        cwd: Path | None = None,
        *,
        env: dict[str, str] | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        if list(argv[:3]) == ["gh", "repo", "clone"]:
            assert env == {"GH_TOKEN": "secret"}
            destination = Path(argv[4])
            subprocess.run(["git", "clone", str(source), str(destination)], check=True, capture_output=True)
            git(destination, "remote", "set-url", "origin", "https://github.com/acme/repo.git")
            return subprocess.CompletedProcess(argv, 0, "", "")
        return fleet.run_command(argv, cwd, env=env, check=check)

    status, evidence = fleet.apply_materialize(action, "acme", "planned", "a" * 64, runner)
    assert status == "materialized_verified"
    assert evidence == {
        "head": expected,
        "origin": "https://github.com/acme/repo.git",
        "detached": True,
    }
    assert fleet.marker_for(lease)["plan_sha256"] == "a" * 64
    detached = subprocess.run(
        ["git", "-C", str(lease / "repo"), "symbolic-ref", "--short", "-q", "HEAD"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert detached.returncode == 1


def test_workspace_clone_stages_verifies_and_cleans_failed_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    init_repo(source)
    expected = git(source, "rev-parse", "HEAD")
    monkeypatch.setattr(fleet, "gh_env", lambda *_: {})

    def runner(
        argv: list[str] | tuple[str, ...],
        cwd: Path | None = None,
        *,
        env: dict[str, str] | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        if list(argv[:3]) == ["gh", "repo", "clone"]:
            destination = Path(argv[4])
            subprocess.run(
                ["git", "clone", "--branch", "main", str(source), str(destination)], check=True, capture_output=True
            )
            git(destination, "remote", "set-url", "origin", "https://github.com/acme/repo.git")
            return subprocess.CompletedProcess(argv, 0, "", "")
        return fleet.run_command(argv, cwd, env=env, check=check)

    action = {
        "kind": "clone_workspace",
        "name": "repo",
        "target": str(tmp_path / "repo"),
        "default_branch": "main",
        "expected_remote_sha": expected,
    }
    status, evidence = fleet.apply_clone(action, "acme", "planned", runner)
    assert status == "cloned_verified"
    assert evidence["head"] == expected
    assert (tmp_path / "repo").is_dir()

    failed_action = {**action, "target": str(tmp_path / "wrong"), "expected_remote_sha": "f" * 40}
    status, _ = fleet.apply_clone(failed_action, "acme", "planned", runner)
    assert status == "stale"
    assert not (tmp_path / "wrong").exists()
    assert not list(tmp_path.glob(".wrong.repo-fleet-*"))


def test_apply_cli_reports_stale_and_unverified_exit_codes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lease = tmp_path / "lease"
    lease.mkdir()
    marker = {
        "schema_version": 1,
        "owner": "acme",
        "repo": "x",
        "resolved_path": str(lease.resolve()),
        "plan_sha256": "a" * 64,
    }
    fleet.write_atomic(lease / ".repo-fleet-lease.json", marker)
    plan = fleet.make_release_plan(lease)
    plan_path = tmp_path / "plan.json"
    plan_path.write_bytes(fleet.canonical_bytes(plan))
    (lease / ".repo-fleet-lease.json").write_text("{}")
    stale = CliRunner().invoke(
        fleet.app,
        [
            "apply",
            str(plan_path),
            "--confirm-owner",
            "acme",
            "--confirm-plan-sha256",
            plan["plan_sha256"],
            "--result",
            str(tmp_path / "stale-result.json"),
        ],
    )
    assert stale.exit_code == 4
    assert json.loads(stale.stdout)["outcome"] == "stale"

    lease.mkdir(exist_ok=True)
    fleet.write_atomic(lease / ".repo-fleet-lease.json", marker)
    fresh_plan = fleet.make_release_plan(lease)
    fresh_path = tmp_path / "fresh-plan.json"
    fresh_path.write_bytes(fleet.canonical_bytes(fresh_plan))
    monkeypatch.setattr(fleet, "apply_release", lambda *_: (_ for _ in ()).throw(fleet.CommandError("unknown")))
    partial = CliRunner().invoke(
        fleet.app,
        [
            "apply",
            str(fresh_path),
            "--confirm-owner",
            "acme",
            "--confirm-plan-sha256",
            fresh_plan["plan_sha256"],
            "--result",
            str(tmp_path / "partial-result.json"),
        ],
    )
    assert partial.exit_code == 5
    assert json.loads(partial.stdout)["outcome"] == "partial"


def test_plan_cli_rejects_output_inside_root_and_irrelevant_flags(tmp_path: Path) -> None:
    lease = tmp_path / "lease"
    lease.mkdir()
    marker = {
        "schema_version": 1,
        "owner": "acme",
        "repo": "x",
        "resolved_path": str(lease.resolve()),
        "plan_sha256": "a" * 64,
    }
    fleet.write_atomic(lease / ".repo-fleet-lease.json", marker)
    inside = CliRunner().invoke(
        fleet.app,
        [
            "plan",
            "--operation",
            "audit-release",
            "--lease",
            str(lease),
            "--out",
            str(lease / "plan.json"),
        ],
    )
    assert inside.exit_code == 2
    assert not (lease / "plan.json").exists()

    irrelevant = CliRunner().invoke(
        fleet.app,
        [
            "plan",
            "--operation",
            "audit-release",
            "--lease",
            str(lease),
            "--owner",
            "acme",
            "--out",
            str(tmp_path / "plan.json"),
        ],
    )
    assert irrelevant.exit_code == 2
    assert not (tmp_path / "plan.json").exists()


def test_apply_rejects_result_inside_managed_root(tmp_path: Path) -> None:
    managed = tmp_path / "managed"
    managed.mkdir()
    plan = minimal_plan(managed)
    plan_path = tmp_path / "plan.json"
    plan_path.write_bytes(fleet.canonical_bytes(plan))
    result = CliRunner().invoke(
        fleet.app,
        [
            "apply",
            str(plan_path),
            "--confirm-owner",
            "acme",
            "--confirm-plan-sha256",
            plan["plan_sha256"],
            "--result",
            str(managed / "result.json"),
        ],
    )
    assert result.exit_code == 2
    assert not (managed / "result.json").exists()


def test_resume_marks_changed_verified_state_stale(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    action = {"kind": "clone_workspace", "name": "x", "target": str(tmp_path / "x")}
    plan = minimal_plan(tmp_path, action)
    monkeypatch.setattr(fleet, "apply_clone", lambda *_: ("cloned_verified", {"head": "a"}))
    result_path = tmp_path.parent / f"{tmp_path.name}-result.json"
    fleet.execute(plan, result_path)
    monkeypatch.setattr(fleet, "verified_action_still_holds", lambda *_: False)
    result = fleet.execute(plan, result_path)
    assert result["outcome"] == "stale"
    assert result["items"]["0"]["after"] == {"reason": "verified_state_changed"}
