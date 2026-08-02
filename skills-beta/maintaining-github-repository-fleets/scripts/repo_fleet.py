#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = ["typer"]
# ///
"""Plan and apply narrowly constrained GitHub repository fleet maintenance."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Protocol
from urllib.parse import quote, urlparse

import typer

SCHEMA = 1
INVENTORY_LIMIT = 100_000
VERIFIED = {"updated_verified", "cloned_verified", "materialized_verified", "released_verified"}
MUTATING_GIT_WORDS = {"clone", "fetch", "merge", "pull", "reset", "rebase", "switch", "checkout", "push", "prune"}
app = typer.Typer(add_completion=False, no_args_is_help=True, pretty_exceptions_enable=False)


class CommandError(RuntimeError):
    pass


class Runner(Protocol):
    def __call__(
        self,
        argv: Sequence[str],
        cwd: Path | None = None,
        *,
        env: Mapping[str, str] | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]: ...


def run_command(
    argv: Sequence[str],
    cwd: Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(list(argv), cwd=cwd, text=True, capture_output=True, check=False, env=env)
    if check and result.returncode:
        raise CommandError(f"command failed ({result.returncode}): {' '.join(argv[:3])}: {result.stderr.strip()}")
    return result


def canonical_bytes(value: dict[str, Any], *, omit_hash: bool = False) -> bytes:
    data = dict(value)
    if omit_hash:
        data.pop("plan_sha256", None)
    return (json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()


def plan_hash(plan: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_bytes(plan, omit_hash=True)).hexdigest()


def object_hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def write_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(canonical_bytes(value))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise typer.BadParameter(f"invalid JSON file {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise typer.BadParameter(f"{path} must contain a JSON object")
    return value


def git(runner: Runner, child: Path, *args: str) -> str:
    return runner(["git", "--no-optional-locks", "-C", str(child), *args], None).stdout.strip()


def gh_env(gh_user: str, runner: Runner) -> dict[str, str]:
    token = runner(["gh", "auth", "token", "--user", gh_user], None).stdout.strip()
    if not token:
        raise CommandError("gh returned an empty token")
    env = os.environ.copy()
    env["GH_TOKEN"] = token
    return env


def parse_github_remote(url: str) -> tuple[str, str] | None:
    value = url.removesuffix(".git")
    scp_prefix = "git@github.com:"
    if value.lower().startswith(scp_prefix):
        parts = value[len(scp_prefix) :].split("/")
    else:
        parsed = urlparse(value)
        if parsed.hostname is None or parsed.hostname.lower() != "github.com":
            return None
        parts = parsed.path.removeprefix("/").split("/")
    return (parts[0], parts[1]) if len(parts) == 2 and all(parts) else None


def valid_branch_name(value: object) -> bool:
    if not isinstance(value, str) or not value or value.startswith("-") or value.endswith(("/", ".")):
        return False
    if value == "@" or ".." in value or "@{" in value or "//" in value:
        return False
    if any(character in " ~^:?*[\\" or ord(character) < 32 or ord(character) == 127 for character in value):
        return False
    return all(component not in {"", ".", ".."} and not component.endswith(".lock") for component in value.split("/"))


def safe_git(child: Path, runner: Runner, *args: str) -> str | None:
    try:
        return git(runner, child, *args)
    except CommandError:
        return None


def discover_children(root: Path, runner: Runner = run_command) -> list[dict[str, Any]]:
    """Inspect only direct children and classify unsafe git indirection."""
    found: list[dict[str, Any]] = []
    for child in sorted(root.iterdir(), key=lambda item: item.name):
        item: dict[str, Any] = {"name": child.name, "path": str(child)}
        if not child.is_dir() or child.is_symlink():
            item["kind"] = "non_repo"
            found.append(item)
            continue
        dotgit = child / ".git"
        if not dotgit.exists():
            item["kind"] = "non_repo"
            found.append(item)
            continue
        common = safe_git(child, runner, "rev-parse", "--path-format=absolute", "--git-common-dir")
        if dotgit.is_file() or common is None or not Path(common).is_relative_to(child.resolve()):
            item.update(kind="external_gitdir", common_dir=common)
            found.append(item)
            continue
        item["kind"] = "repository"
        remotes: dict[str, str] = {}
        for remote in ("origin", "upstream"):
            value = safe_git(child, runner, "remote", "get-url", remote)
            if value:
                remotes[remote] = value
        item["remotes"] = remotes
        item["origin_repo"] = parse_github_remote(remotes["origin"]) if "origin" in remotes else None
        item["upstream_repo"] = parse_github_remote(remotes["upstream"]) if "upstream" in remotes else None
        found.append(item)
    return found


def remote_inventory(owner: str, gh_user: str, runner: Runner = run_command) -> list[dict[str, Any]]:
    fields = "name,nameWithOwner,url,visibility,isArchived,isFork,parent,defaultBranchRef,diskUsage"
    result = runner(
        ["gh", "repo", "list", owner, "--limit", str(INVENTORY_LIMIT), "--json", fields],
        None,
        env=gh_env(gh_user, runner),
    )
    if result.returncode:
        raise CommandError(f"gh repo list failed: {result.stderr.strip()}")
    value = json.loads(result.stdout)
    if not isinstance(value, list):
        raise CommandError("unexpected gh inventory response")
    if len(value) >= INVENTORY_LIMIT:
        raise CommandError(
            f"repository inventory reached the safety limit ({INVENTORY_LIMIT}); refusing a partial plan"
        )
    return value


def exact_remote_sha(owner: str, name: str, branch: str, gh_user: str, runner: Runner = run_command) -> str:
    # gh supplies authenticated git credentials without changing the active account.
    result = runner(
        ["gh", "api", f"repos/{owner}/{name}/git/ref/heads/{quote(branch, safe='')}", "--jq", ".object.sha"],
        None,
        env=gh_env(gh_user, runner),
    )
    if result.returncode:
        raise CommandError(f"GitHub ref lookup failed: {result.stderr.strip()}")
    sha = result.stdout.strip()
    if len(sha) != 40:
        raise CommandError(f"invalid remote SHA for {owner}/{name}")
    return sha


def canonical_remote(url: str, gh_user: str, runner: Runner) -> tuple[str, str] | None:
    result = runner(
        ["gh", "repo", "view", url, "--json", "nameWithOwner", "--jq", ".nameWithOwner"],
        None,
        env=gh_env(gh_user, runner),
        check=False,
    )
    if result.returncode:
        return None
    parts = result.stdout.strip().split("/", 1)
    return (parts[0], parts[1]) if len(parts) == 2 and all(parts) else None


def repository_state(child: Path, default_branch: str, runner: Runner = run_command) -> dict[str, Any]:
    head = safe_git(child, runner, "rev-parse", "HEAD")
    branch = safe_git(child, runner, "symbolic-ref", "--short", "HEAD")
    status = safe_git(child, runner, "status", "--porcelain=v1", "--untracked-files=all")
    tracking = safe_git(child, runner, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
    git_dir_text = safe_git(child, runner, "rev-parse", "--path-format=absolute", "--git-dir")
    git_dir = Path(git_dir_text) if git_dir_text else None
    markers = ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "BISECT_LOG", "rebase-merge", "rebase-apply")
    operations = git_dir is None or any((git_dir / marker).exists() for marker in markers)
    expected_tracking = f"origin/{default_branch}"
    return {
        "head": head,
        "branch": branch,
        "clean": status == "",
        "tracking": tracking,
        "operation_in_progress": operations,
        "eligible": bool(
            head and branch == default_branch and status == "" and tracking == expected_tracking and not operations
        ),
    }


def validate_scope(all_repos: bool, repos: list[str]) -> None:
    if all_repos == bool(repos):
        raise typer.BadParameter("choose exactly one scope: --all or one or more --repo")
    if len(repos) != len(set(repos)):
        raise typer.BadParameter("duplicate --repo values are not allowed")


def cached_relation(child: Path, local_sha: str, remote_sha: str, runner: Runner) -> str:
    available = runner(
        ["git", "-C", str(child), "cat-file", "-e", f"{remote_sha}^{{commit}}"],
        None,
        check=False,
    )
    if available.returncode != 0:
        return "unknown_until_fetch"
    local_ancestor = runner(
        ["git", "-C", str(child), "merge-base", "--is-ancestor", local_sha, remote_sha],
        None,
        check=False,
    )
    if local_ancestor.returncode == 0:
        return "fast_forward"
    if local_ancestor.returncode > 1:
        return "ancestry_unknown"
    remote_ancestor = runner(
        ["git", "-C", str(child), "merge-base", "--is-ancestor", remote_sha, local_sha],
        None,
        check=False,
    )
    if remote_ancestor.returncode == 0:
        return "ahead"
    if remote_ancestor.returncode > 1:
        return "ancestry_unknown"
    common = runner(
        ["git", "-C", str(child), "merge-base", local_sha, remote_sha],
        None,
        check=False,
    )
    return "diverged" if common.returncode == 0 else "unrelated"


def make_workspace_plan(
    owner: str,
    gh_user: str,
    root: Path,
    all_repos: bool,
    repos: list[str],
    allow: list[str],
    runner: Runner = run_command,
) -> dict[str, Any]:
    validate_scope(all_repos, repos)
    allowed = set(allow)
    if not allowed or not allowed <= {"clone", "fast-forward"}:
        raise typer.BadParameter("workspace-sync requires explicit --allow clone and/or --allow fast-forward")
    root = root.resolve(strict=True)
    children = discover_children(root, runner)
    inventory = remote_inventory(owner, gh_user, runner)
    selected = inventory if all_repos else [item for item in inventory if item.get("name") in repos]
    actions: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    by_name = {item["name"]: item for item in children}
    # Exact canonical names remain local-only and cheap. Resolve only origins whose
    # directory/name does not directly match inventory, catching GitHub redirects.
    canonical_locals: dict[tuple[str, str], dict[str, Any]] = {}
    inventory_keys = {(owner, item["name"]) for item in inventory if isinstance(item.get("name"), str)}
    for child in children:
        origin = child.get("origin_repo")
        if child.get("kind") != "repository" or not origin:
            continue
        parsed = tuple(origin)
        if parsed not in inventory_keys or child["name"] != parsed[1]:
            url = child.get("remotes", {}).get("origin")
            resolved = canonical_remote(url, gh_user, runner) if url else None
            if resolved:
                canonical_locals[resolved] = child
    inventory_names = {item.get("name") for item in inventory}
    for requested in repos:
        if requested not in inventory_names:
            blocked.append({"name": requested, "reason": "not_found_case_sensitive"})
    for remote in selected:
        name = remote.get("name")
        branch_ref = remote.get("defaultBranchRef")
        if not isinstance(name, str):
            continue
        if remote.get("isArchived"):
            blocked.append({"name": name, "reason": "archived"})
            continue
        if not isinstance(branch_ref, dict) or not isinstance(branch_ref.get("name"), str):
            blocked.append({"name": name, "reason": "empty_repository"})
            continue
        branch = branch_ref["name"]
        sha = exact_remote_sha(owner, name, branch, gh_user, runner)
        local = by_name.get(name)
        redirected = canonical_locals.get((owner, name))
        if redirected is not None and redirected is not local:
            blocked.append({
                "name": name,
                "reason": "name_mismatch",
                "local_name": redirected["name"],
                "path": redirected["path"],
            })
            continue
        if local is None:
            if "clone" in allowed:
                actions.append({
                    "kind": "clone_workspace",
                    "name": name,
                    "target": str(root / name),
                    "default_branch": branch,
                    "expected_remote_sha": sha,
                })
            else:
                blocked.append({"name": name, "reason": "clone_not_allowed"})
            continue
        if local["kind"] != "repository":
            blocked.append({"name": name, "reason": local["kind"]})
            continue
        if local.get("origin_repo") is None:
            blocked.append({"name": name, "reason": "local_only", "upstream_repo": local.get("upstream_repo")})
            continue
        if tuple(local["origin_repo"]) != (owner, name):
            blocked.append({"name": name, "reason": "origin_or_name_mismatch", "origin_repo": local["origin_repo"]})
            continue
        state = repository_state(Path(local["path"]), branch, runner)
        if not state["eligible"]:
            blocked.append({"name": name, "reason": "checkout_ineligible", "state": state})
        elif state["head"] == sha:
            blocked.append({"name": name, "reason": "already_current"})
        elif "fast-forward" not in allowed:
            blocked.append({"name": name, "reason": "fast_forward_not_allowed"})
        else:
            relation = cached_relation(Path(local["path"]), state["head"], sha, runner)
            if relation in {"ahead", "diverged", "unrelated", "ancestry_unknown"}:
                blocked.append({"name": name, "reason": relation, "state": state})
                continue
            actions.append({
                "kind": "fast_forward_workspace",
                "name": name,
                "target": local["path"],
                "default_branch": branch,
                "expected_local_sha": state["head"],
                "expected_remote_sha": sha,
                "relationship": relation,
            })
    remote_findings = [{"kind": "remote_repository", **item} for item in inventory]
    scope = {"mode": "all"} if all_repos else {"mode": "repos", "repos": sorted(repos)}
    return base_plan(
        "workspace-sync",
        owner,
        gh_user,
        root,
        scope,
        {"allowed_actions": sorted(allowed)},
        actions,
        blocked,
        [*children, *remote_findings],
    )


def marker_for(lease: Path) -> dict[str, Any] | None:
    if lease.is_symlink() or not lease.is_dir():
        return None
    marker_path = lease / ".repo-fleet-lease.json"
    try:
        marker = json.loads(marker_path.read_text())
    except OSError, json.JSONDecodeError:
        return None
    if (
        not isinstance(marker, dict)
        or set(marker) != {"schema_version", "owner", "repo", "resolved_path", "plan_sha256"}
        or marker.get("schema_version") != SCHEMA
        or not isinstance(marker.get("owner"), str)
        or not isinstance(marker.get("repo"), str)
        or not isinstance(marker.get("plan_sha256"), str)
        or len(marker["plan_sha256"]) != 64
        or any(character not in "0123456789abcdef" for character in marker["plan_sha256"])
    ):
        return None
    if marker.get("resolved_path") != str(lease.resolve()):
        return None
    return marker


def base_plan(
    operation: str,
    owner: str,
    gh_user: str | None,
    path: Path,
    scope: dict[str, Any],
    policy: dict[str, Any],
    actions: list[dict[str, Any]],
    blocked: list[dict[str, Any]],
    findings: list[dict[str, Any]],
) -> dict[str, Any]:
    plan: dict[str, Any] = {
        "schema_version": SCHEMA,
        "operation": operation,
        "owner": owner,
        "gh_user": gh_user,
        "root": str(path),
        "scope": scope,
        "policy": policy,
        "generated_at": datetime.now(UTC).isoformat(),
        "actions": actions,
        "blocked": blocked,
        "findings": findings,
    }
    plan["plan_sha256"] = plan_hash(plan)
    return plan


def make_audit_plan(
    owner: str,
    gh_user: str,
    lease_root: Path,
    all_repos: bool,
    repos: list[str],
    history: str,
    runner: Runner = run_command,
) -> dict[str, Any]:
    validate_scope(all_repos, repos)
    if history not in {"shallow", "full"}:
        raise typer.BadParameter("--history must be shallow or full")
    lease_root = lease_root.resolve(strict=True)
    inventory = remote_inventory(owner, gh_user, runner)
    selected = inventory if all_repos else [item for item in inventory if item.get("name") in repos]
    actions: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    inventory_names = {item.get("name") for item in inventory}
    for requested in repos:
        if requested not in inventory_names:
            blocked.append({"name": requested, "reason": "not_found_case_sensitive"})
    for remote in selected:
        name, branch_ref = remote.get("name"), remote.get("defaultBranchRef")
        if not isinstance(name, str) or remote.get("isArchived") or not isinstance(branch_ref, dict):
            blocked.append({"name": name, "reason": "archived_or_empty"})
            continue
        branch = branch_ref.get("name")
        if not isinstance(branch, str):
            blocked.append({"name": name, "reason": "empty_repository"})
            continue
        sha = exact_remote_sha(owner, name, branch, gh_user, runner)
        lease = lease_root / f"{name}-{sha[:12]}"
        actions.append({
            "kind": "materialize_audit",
            "name": name,
            "target": str(lease),
            "default_branch": branch,
            "history": history,
            "expected_remote_sha": sha,
        })
    return base_plan(
        "audit-materialize",
        owner,
        gh_user,
        lease_root,
        {"mode": "all"} if all_repos else {"mode": "repos", "repos": sorted(repos)},
        {"history": history},
        actions,
        blocked,
        [{"kind": "remote_repository", **item} for item in inventory],
    )


def make_release_plan(lease: Path) -> dict[str, Any]:
    marker = marker_for(lease)
    if marker is None or not isinstance(marker.get("owner"), str):
        raise typer.BadParameter("lease is not an owned repo-fleet lease")
    lease = lease.resolve()
    action = {"kind": "release_audit", "name": marker.get("repo"), "target": str(lease), "marker": marker}
    return base_plan(
        "audit-release",
        marker["owner"],
        None,
        lease,
        {"mode": "lease", "lease": str(lease)},
        {},
        [action],
        [],
        [],
    )


def validate_plan(plan: dict[str, Any]) -> None:
    required = {"schema_version", "operation", "owner", "root", "scope", "policy", "actions", "plan_sha256"}
    if plan.get("schema_version") != SCHEMA or not required <= plan.keys():
        raise typer.BadParameter("unsupported or incomplete plan schema")
    if plan.get("operation") not in {"workspace-sync", "audit-materialize", "audit-release"}:
        raise typer.BadParameter("unsupported operation")
    if not isinstance(plan.get("actions"), list) or plan_hash(plan) != plan.get("plan_sha256"):
        raise typer.BadParameter("plan hash mismatch")
    root_value = plan.get("root")
    if not isinstance(root_value, str):
        raise typer.BadParameter("invalid plan root")
    root = Path(root_value)
    owner = plan.get("owner")
    try:
        invalid_root_or_owner = (
            not root.is_absolute()
            or root.is_symlink()
            or not root.is_dir()
            or root.resolve() != root
            or not isinstance(owner, str)
            or not owner
            or owner in {".", ".."}
            or Path(owner).name != owner
        )
    except (OSError, RuntimeError) as exc:
        raise typer.BadParameter("invalid plan root or owner") from exc
    if invalid_root_or_owner:
        raise typer.BadParameter("invalid plan root or owner")
    operation = plan["operation"]
    scope = plan.get("scope")
    policy = plan.get("policy")
    if not isinstance(scope, dict) or not isinstance(policy, dict):
        raise typer.BadParameter("invalid plan scope or policy")
    if operation == "audit-release":
        if scope != {"mode": "lease", "lease": str(root)}:
            raise typer.BadParameter("invalid lease scope")
    elif scope.get("mode") == "all":
        if set(scope) != {"mode"}:
            raise typer.BadParameter("invalid all-repository scope")
    elif scope.get("mode") == "repos":
        scoped_repos = scope.get("repos")
        scoped_strings = (
            [item for item in scoped_repos if isinstance(item, str)] if isinstance(scoped_repos, list) else []
        )
        if (
            set(scope) != {"mode", "repos"}
            or not isinstance(scoped_repos, list)
            or not scoped_repos
            or len(scoped_strings) != len(scoped_repos)
            or scoped_strings != sorted(set(scoped_strings))
            or any(not item or Path(item).name != item for item in scoped_strings)
        ):
            raise typer.BadParameter("invalid repository scope")
    else:
        raise typer.BadParameter("invalid repository scope")
    if operation == "workspace-sync":
        allowed_actions = policy.get("allowed_actions")
        allowed_strings = (
            [item for item in allowed_actions if isinstance(item, str)] if isinstance(allowed_actions, list) else []
        )
        if (
            set(policy) != {"allowed_actions"}
            or not isinstance(allowed_actions, list)
            or not allowed_actions
            or len(allowed_strings) != len(allowed_actions)
            or allowed_strings != sorted(set(allowed_strings))
            or not set(allowed_strings) <= {"clone", "fast-forward"}
        ):
            raise typer.BadParameter("invalid workspace policy")
    elif operation == "audit-materialize":
        if set(policy) != {"history"} or policy.get("history") not in {"shallow", "full"}:
            raise typer.BadParameter("invalid audit policy")
    elif policy:
        raise typer.BadParameter("release policy must be empty")
    expected_kinds = {
        "workspace-sync": {"clone_workspace", "fast_forward_workspace"},
        "audit-materialize": {"materialize_audit"},
        "audit-release": {"release_audit"},
    }[operation]
    gh_user = plan.get("gh_user")
    if operation != "audit-release" and (
        not isinstance(gh_user, str) or not gh_user or gh_user in {".", ".."} or Path(gh_user).name != gh_user
    ):
        raise typer.BadParameter("authenticated operation requires gh_user")
    required_by_kind = {
        "clone_workspace": {"kind", "name", "target", "default_branch", "expected_remote_sha"},
        "fast_forward_workspace": {
            "kind",
            "name",
            "target",
            "default_branch",
            "expected_local_sha",
            "expected_remote_sha",
            "relationship",
        },
        "materialize_audit": {"kind", "name", "target", "default_branch", "history", "expected_remote_sha"},
        "release_audit": {"kind", "name", "target", "marker"},
    }
    for action in plan["actions"]:
        if not isinstance(action, dict) or action.get("kind") not in expected_kinds:
            raise typer.BadParameter("invalid action kind")
        if set(action) != required_by_kind[action["kind"]]:
            raise typer.BadParameter("invalid action fields")
        name = action["name"]
        target_value = action["target"]
        if not isinstance(target_value, str):
            raise typer.BadParameter("invalid action target")
        target = Path(target_value)
        if (
            not isinstance(name, str)
            or not name
            or name in {".", ".."}
            or Path(name).name != name
            or not target.is_absolute()
        ):
            raise typer.BadParameter("invalid action name or target")
        if scope.get("mode") == "repos" and name not in scope["repos"]:
            raise typer.BadParameter("action is outside the planned repository scope")
        try:
            if operation == "workspace-sync" and (target.parent != root or target.name != name):
                raise typer.BadParameter("workspace target must be its named direct child")
            if operation == "audit-materialize" and (target.parent != root or not target.name.startswith(f"{name}-")):
                raise typer.BadParameter("audit target must be a named direct child")
            if operation == "audit-release" and target != root:
                raise typer.BadParameter("release target must equal root")
            if target.is_symlink():
                raise typer.BadParameter("action target escapes its resolved root")
            if operation != "audit-release" and target.parent.resolve(strict=True) != root:
                raise typer.BadParameter("action target escapes its resolved root")
            if operation != "audit-release" and target.exists() and target.resolve().parent != root:
                raise typer.BadParameter("existing action target escapes its resolved root")
        except (OSError, RuntimeError) as exc:
            raise typer.BadParameter("action target cannot be resolved safely") from exc
        kind = action["kind"]
        if kind == "release_audit":
            marker = action["marker"]
            if (
                not isinstance(marker, dict)
                or set(marker) != {"schema_version", "owner", "repo", "resolved_path", "plan_sha256"}
                or marker.get("schema_version") != SCHEMA
                or marker.get("owner") != owner
                or marker.get("repo") != name
                or marker.get("resolved_path") != str(target)
                or not isinstance(marker.get("plan_sha256"), str)
                or len(marker["plan_sha256"]) != 64
                or any(character not in "0123456789abcdef" for character in marker["plan_sha256"])
            ):
                raise typer.BadParameter("invalid release ownership marker")
            continue
        branch = action["default_branch"]
        sha = action["expected_remote_sha"]
        if (
            not valid_branch_name(branch)
            or not isinstance(sha, str)
            or len(sha) != 40
            or any(character not in "0123456789abcdef" for character in sha)
        ):
            raise typer.BadParameter("invalid planned branch or commit SHA")
        if kind == "fast_forward_workspace":
            local_sha = action["expected_local_sha"]
            if (
                action["relationship"] not in {"fast_forward", "unknown_until_fetch"}
                or not isinstance(local_sha, str)
                or len(local_sha) != 40
                or any(character not in "0123456789abcdef" for character in local_sha)
            ):
                raise typer.BadParameter("invalid planned fast-forward state")
        if kind == "clone_workspace" and "clone" not in policy["allowed_actions"]:
            raise typer.BadParameter("clone action is outside the workspace policy")
        if kind == "fast_forward_workspace" and "fast-forward" not in policy["allowed_actions"]:
            raise typer.BadParameter("fast-forward action is outside the workspace policy")
        if kind == "materialize_audit" and (
            action["history"] != policy["history"] or target.name != f"{name}-{sha[:12]}"
        ):
            raise typer.BadParameter("invalid audit materialization action")


def action_target_is_safe(plan: dict[str, Any], action: dict[str, Any]) -> bool:
    root = Path(plan["root"])
    target = Path(action["target"])
    try:
        if root.is_symlink() or root.resolve(strict=True) != root or target.is_symlink():
            return False
        if action["kind"] == "release_audit":
            return target == root
        return target.parent.resolve(strict=True) == root and (not target.exists() or target.resolve().parent == root)
    except OSError:
        return False


def precondition_ff(action: dict[str, Any], owner: str, gh_user: str, runner: Runner) -> tuple[bool, dict[str, Any]]:
    target = Path(action["target"])
    state = repository_state(target, action["default_branch"], runner)
    origin = safe_git(target, runner, "remote", "get-url", "origin")
    state["origin"] = origin
    if origin is None or parse_github_remote(origin) != (owner, action["name"]):
        return False, state
    result = runner(
        [
            "git",
            "-c",
            "credential.helper=",
            "-c",
            "credential.helper=!gh auth git-credential",
            "-C",
            str(target),
            "ls-remote",
            "--exit-code",
            "origin",
            f"refs/heads/{action['default_branch']}",
        ],
        None,
        env=gh_env(gh_user, runner),
        check=False,
    )
    remote = result.stdout.strip() if result.returncode == 0 else None
    remote_sha = remote.split()[0] if remote else None
    state["remote_sha"] = remote_sha
    return state["eligible"] and state["head"] == action["expected_local_sha"] and remote_sha == action[
        "expected_remote_sha"
    ], state


def apply_clone(action: dict[str, Any], owner: str, gh_user: str, runner: Runner) -> tuple[str, dict[str, Any]]:
    target = Path(action["target"])
    before = {"target_exists": target.exists()}
    if target.exists():
        return "stale", before
    staging = target.with_name(f".{target.name}.repo-fleet-{os.getpid()}")
    if staging.exists():
        return "stale", {"staging_exists": True}
    try:
        runner(
            [
                "gh",
                "repo",
                "clone",
                f"{owner}/{action['name']}",
                str(staging),
                "--",
                "--branch",
                action["default_branch"],
                "--single-branch",
                "--no-tags",
            ],
            None,
            env=gh_env(gh_user, runner),
        )
        origin = git(runner, staging, "remote", "get-url", "origin")
        branch = git(runner, staging, "symbolic-ref", "--short", "HEAD")
        head = git(runner, staging, "rev-parse", "HEAD")
        if (
            parse_github_remote(origin) != (owner, action["name"])
            or branch != action["default_branch"]
            or head != action["expected_remote_sha"]
        ):
            shutil.rmtree(staging)
            return "stale", {"origin": origin, "branch": branch, "head": head}
        staging.rename(target)
        return "cloned_verified", {"head": head}
    except CommandError:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def apply_ff(action: dict[str, Any], owner: str, gh_user: str, runner: Runner) -> tuple[str, dict[str, Any]]:
    ok, before = precondition_ff(action, owner, gh_user, runner)
    if not ok:
        return "stale", before
    target, branch, pinned = Path(action["target"]), action["default_branch"], action["expected_remote_sha"]
    runner(
        [
            "git",
            "-c",
            "credential.helper=",
            "-c",
            "credential.helper=!gh auth git-credential",
            "-C",
            str(target),
            "fetch",
            "--no-tags",
            "origin",
            f"refs/heads/{branch}:refs/remotes/origin/{branch}",
        ],
        None,
        env=gh_env(gh_user, runner),
    )
    remote_ref = git(runner, target, "rev-parse", f"refs/remotes/origin/{branch}")
    if remote_ref != pinned:
        return "stale", {"remote_ref": remote_ref}
    ancestor = runner(
        ["git", "-C", str(target), "merge-base", "--is-ancestor", action["expected_local_sha"], pinned],
        None,
        check=False,
    )
    if ancestor.returncode == 1:
        return "stale", {"reason": "not_fast_forward"}
    if ancestor.returncode > 1:
        raise CommandError(f"merge-base could not verify ancestry (exit {ancestor.returncode})")
    state = repository_state(target, branch, runner)
    if not state["eligible"] or state["head"] != action["expected_local_sha"]:
        return "stale", state
    runner(["git", "-C", str(target), "merge", "--ff-only", "--no-edit", pinned], None)
    after = repository_state(target, branch, runner)
    origin = safe_git(target, runner, "remote", "get-url", "origin")
    after["origin"] = origin
    verified = bool(
        after["eligible"]
        and after["head"] == pinned
        and origin
        and parse_github_remote(origin) == (owner, action["name"])
    )
    return ("updated_verified" if verified else "unverified"), after


def apply_materialize(
    action: dict[str, Any], owner: str, gh_user: str, plan_sha: str, runner: Runner
) -> tuple[str, dict[str, Any]]:
    target = Path(action["target"])
    if target.exists() or target.is_symlink():
        return "stale", {"target_exists": True}
    target.mkdir()
    marker = {
        "schema_version": SCHEMA,
        "owner": owner,
        "repo": action["name"],
        "resolved_path": str(target.resolve()),
        "plan_sha256": plan_sha,
    }
    write_atomic(target / ".repo-fleet-lease.json", marker)
    argv = [
        "gh",
        "repo",
        "clone",
        f"{owner}/{action['name']}",
        str(target / "repo"),
        "--",
        "--single-branch",
        "--no-tags",
        "--branch",
        action["default_branch"],
    ]
    argv += ["--depth", "1"] if action["history"] == "shallow" else ["--filter=blob:none"]
    try:
        runner(argv, None, env=gh_env(gh_user, runner))
        repo = target / "repo"
        head = git(runner, repo, "rev-parse", "HEAD")
        origin = git(runner, repo, "remote", "get-url", "origin")
        if head != action["expected_remote_sha"] or parse_github_remote(origin) != (owner, action["name"]):
            shutil.rmtree(target)
            return "stale", {"head": head, "origin": origin}
        runner(["git", "-C", str(repo), "checkout", "--detach", action["expected_remote_sha"]], None)
        detached = safe_git(repo, runner, "symbolic-ref", "--short", "HEAD") is None
        final_head = git(runner, repo, "rev-parse", "HEAD")
        if not detached or final_head != action["expected_remote_sha"]:
            shutil.rmtree(target)
            return "stale", {"head": final_head, "detached": detached}
        return "materialized_verified", {"head": final_head, "origin": origin, "detached": True}
    except CommandError:
        if marker_for(target) is not None:
            shutil.rmtree(target)
        raise


def apply_release(action: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    target = Path(action["target"])
    marker = marker_for(target)
    if marker is None or marker != action["marker"]:
        return "stale", {"owned": False}
    shutil.rmtree(target)
    return "released_verified", {"target_exists": target.exists()}


def verified_action_still_holds(
    action: dict[str, Any], owner: str, plan_sha: str, runner: Runner = run_command
) -> bool:
    target = Path(action["target"])
    kind = action["kind"]
    if kind == "release_audit":
        return not target.exists() and not target.is_symlink()
    if target.is_symlink() or not target.is_dir():
        return False
    if kind in {"clone_workspace", "fast_forward_workspace"}:
        state = repository_state(target, action["default_branch"], runner)
        origin = safe_git(target, runner, "remote", "get-url", "origin")
        return bool(
            state["eligible"]
            and state["head"] == action["expected_remote_sha"]
            and origin
            and parse_github_remote(origin) == (owner, action["name"])
        )
    if kind == "materialize_audit":
        repo = target / "repo"
        marker = marker_for(target)
        origin = safe_git(repo, runner, "remote", "get-url", "origin")
        head = safe_git(repo, runner, "rev-parse", "HEAD")
        branch = safe_git(repo, runner, "symbolic-ref", "--short", "HEAD")
        status = safe_git(repo, runner, "status", "--porcelain=v1", "--untracked-files=all")
        return bool(
            marker
            and marker["owner"] == owner
            and marker["repo"] == action["name"]
            and marker["plan_sha256"] == plan_sha
            and origin
            and parse_github_remote(origin) == (owner, action["name"])
            and head == action["expected_remote_sha"]
            and branch is None
            and status == ""
        )
    return False


def execute(plan: dict[str, Any], result_path: Path, runner: Runner = run_command) -> dict[str, Any]:
    plan_sha = plan["plan_sha256"]
    result: dict[str, Any]
    if result_path.exists():
        result = load_object(result_path)
        if (
            result.get("plan_sha256") != plan_sha
            or result.get("owner") != plan["owner"]
            or result.get("operation") != plan["operation"]
            or not isinstance(result.get("items"), dict)
        ):
            raise typer.BadParameter("result belongs to another plan")
    else:
        result = {
            "schema_version": SCHEMA,
            "plan_sha256": plan_sha,
            "owner": plan["owner"],
            "operation": plan["operation"],
            "started_at": datetime.now(UTC).isoformat(),
            "completed_at": None,
            "outcome": "partial",
            "counts": {},
            "items": {},
        }
    items = result["items"]
    for key, item in items.items():
        if (
            not isinstance(key, str)
            or not key.isdigit()
            or int(key) >= len(plan["actions"])
            or not isinstance(item, dict)
            or item.get("kind") != plan["actions"][int(key)].get("kind")
            or item.get("name") != plan["actions"][int(key)].get("name")
            or item.get("action_sha256") != object_hash(plan["actions"][int(key)])
            or item.get("status") not in VERIFIED | {"stale", "unverified"}
        ):
            raise typer.BadParameter("invalid existing result item")
    for index, action in enumerate(plan["actions"]):
        key = str(index)
        previous = items.get(key)
        if isinstance(previous, dict) and previous.get("status") in VERIFIED:
            if verified_action_still_holds(action, plan["owner"], plan_sha, runner):
                continue
            previous.update(status="stale", after={"reason": "verified_state_changed"})
            write_atomic(result_path, result)
            continue
        record: dict[str, Any] = {
            "kind": action.get("kind"),
            "name": action.get("name"),
            "action_sha256": object_hash(action),
        }
        if not action_target_is_safe(plan, action):
            record.update(status="stale", after={"reason": "target_path_changed"})
            items[key] = record
            write_atomic(result_path, result)
            continue
        try:
            match action.get("kind"):
                case "clone_workspace":
                    status, evidence = apply_clone(action, plan["owner"], plan["gh_user"], runner)
                case "fast_forward_workspace":
                    status, evidence = apply_ff(action, plan["owner"], plan["gh_user"], runner)
                case "materialize_audit":
                    status, evidence = apply_materialize(action, plan["owner"], plan["gh_user"], plan_sha, runner)
                case "release_audit":
                    status, evidence = apply_release(action)
                case _:
                    raise typer.BadParameter("unknown action kind")
            record.update(status=status, after=evidence)
        except (CommandError, OSError) as exc:
            record.update(status="unverified", error=str(exc))
        items[key] = record
        write_atomic(result_path, result)
        if record["status"] == "unverified":
            break
    counts: dict[str, int] = {}
    for item in items.values():
        status = item["status"]
        counts[status] = counts.get(status, 0) + 1
    if any(status == "unverified" for status in counts) or len(items) < len(plan["actions"]):
        outcome = "partial"
    elif "stale" in counts:
        outcome = "stale"
    else:
        outcome = "converged"
    result.update(counts=counts, outcome=outcome, completed_at=datetime.now(UTC).isoformat())
    write_atomic(result_path, result)
    return result


@app.command("plan")
def plan_command(
    operation: Annotated[str, typer.Option("--operation")],
    out: Annotated[Path, typer.Option("--out")],
    owner: Annotated[str | None, typer.Option("--owner")] = None,
    gh_user: Annotated[str | None, typer.Option("--gh-user")] = None,
    root: Annotated[Path | None, typer.Option("--root")] = None,
    all_repos: Annotated[bool, typer.Option("--all")] = False,
    repo: Annotated[list[str] | None, typer.Option("--repo")] = None,
    allow: Annotated[list[str] | None, typer.Option("--allow")] = None,
    history: Annotated[str | None, typer.Option("--history")] = None,
    lease: Annotated[Path | None, typer.Option("--lease")] = None,
) -> None:
    """Create a plan without mutating repositories or GitHub state."""
    repos = repo or []
    if operation == "audit-release":
        if any((owner, gh_user, root, repos, allow, history)) or all_repos:
            raise typer.BadParameter("audit-release accepts only --operation, --lease, and --out")
        if lease is None:
            raise typer.BadParameter("audit-release requires --lease")
        value = make_release_plan(lease)
    else:
        if lease is not None:
            raise typer.BadParameter("--lease is only valid for audit-release")
        if owner is None or gh_user is None or root is None:
            raise typer.BadParameter("remote operations require explicit --owner, --gh-user, and --root")
        if operation == "workspace-sync":
            if history is not None:
                raise typer.BadParameter("--history is only valid for audit-materialize")
            value = make_workspace_plan(owner, gh_user, root, all_repos, repos, allow or [])
        elif operation == "audit-materialize":
            if allow:
                raise typer.BadParameter("--allow is only valid for workspace-sync")
            if history is None:
                raise typer.BadParameter("audit-materialize requires --history")
            value = make_audit_plan(owner, gh_user, root, all_repos, repos, history)
        else:
            raise typer.BadParameter("unknown operation")
    out = out.resolve()
    plan_root = Path(value["root"])
    if out == plan_root or out.is_relative_to(plan_root):
        raise typer.BadParameter("--out must be outside the managed root")
    if out.exists():
        raise typer.BadParameter("--out must not already exist")
    write_atomic(out, value)
    print(
        json.dumps(
            {
                "ok": True,
                "plan": str(out),
                "plan_sha256": value["plan_sha256"],
                "counts": {
                    "actions": len(value["actions"]),
                    "blocked": len(value["blocked"]),
                    "findings": len(value["findings"]),
                    "by_action": {
                        kind: sum(action["kind"] == kind for action in value["actions"])
                        for kind in sorted({action["kind"] for action in value["actions"]})
                    },
                    "already_current": sum(item.get("reason") == "already_current" for item in value["blocked"]),
                },
            },
            separators=(",", ":"),
        )
    )


@app.command("apply")
def apply_command(
    plan: Path,
    confirm_owner: Annotated[str, typer.Option("--confirm-owner")],
    confirm_plan_sha256: Annotated[str, typer.Option("--confirm-plan-sha256")],
    result: Annotated[Path, typer.Option("--result")],
) -> None:
    """Apply an approved plan serially, checkpointing each action."""
    plan = plan.resolve()
    result = result.resolve()
    value = load_object(plan)
    validate_plan(value)
    if value["owner"] != confirm_owner or value["plan_sha256"] != confirm_plan_sha256:
        raise typer.BadParameter("owner or plan hash confirmation mismatch")
    root = Path(value["root"])
    if result == plan or result == root or result.is_relative_to(root) or result.is_symlink():
        raise typer.BadParameter("--result must be a separate file outside the managed root")
    output = execute(value, result)
    print(json.dumps(output, separators=(",", ":")))
    if output["outcome"] == "stale":
        raise typer.Exit(4)
    if output["outcome"] == "partial":
        raise typer.Exit(5)


if __name__ == "__main__":
    app()
