#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["typer>=0.25.0", "jinja2>=3.1.0"]
# ///
"""Build a compact Git repository zip for Oracle/ChatGPT review."""

from __future__ import annotations

import os
import shlex
import shutil
import stat
import subprocess
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

import typer
from jinja2 import Environment, FileSystemLoader, StrictUndefined

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
TEMPLATE_DIR = SKILL_DIR / "templates"

RESERVED_CONTEXT_NAMES = {"MANIFEST.md", "PROMPT.md"}
IGNORED_CONTEXT_DIR_NAMES = {".git", "node_modules", ".venv", "__pycache__"}


def fail(message: str) -> None:
    typer.echo(f"repo-zip: {message}", err=True)
    raise typer.Exit(1)


def run_command(args: list[str], cwd: Path | None = None, *, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    proc = subprocess.run(
        args,
        cwd=cwd,
        check=False,
        capture_output=True,
    )
    if check and proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).decode(errors="replace").strip()
        suffix = f"\n{detail}" if detail else ""
        fail(f"command failed ({proc.returncode}): {shlex.join(args)}{suffix}")
    return proc


def run_git(args: list[str], cwd: Path, *, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    return run_command(["git", *args], cwd=cwd, check=check)


def git_text(args: list[str], cwd: Path) -> str:
    return run_git(args, cwd).stdout.decode().strip()


def git_nul_paths(args: list[str], cwd: Path) -> list[str]:
    output = run_git(args, cwd).stdout
    return [os.fsdecode(part) for part in output.split(b"\0") if part]


def template_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=False,
        keep_trailing_newline=True,
        lstrip_blocks=True,
        trim_blocks=True,
        undefined=StrictUndefined,
    )


def render_template(name: str, **context: Any) -> str:
    return template_env().get_template(name).render(**context)


def non_empty(value: str, label: str) -> str:
    if value == "":
        fail(f"{label} requires a non-empty path")
    return value


def validate_single(values: list[str], label: str) -> str | None:
    if len(values) > 1:
        fail(f"{label} may only be provided once")
    if not values:
        return None
    return non_empty(values[0], label)


def validate_output_dir(output_dir: str | None, output_dir_option: list[str]) -> Path | None:
    selected_option = validate_single(output_dir_option, "--output-dir")
    if output_dir == "":
        fail("output directory must not be empty")
    if output_dir and selected_option:
        fail("expected at most one output directory")
    selected = selected_option or output_dir
    return Path(selected).expanduser() if selected else None


def validate_context_paths(context: list[str]) -> list[Path]:
    return [Path(non_empty(value, "--context")).expanduser() for value in context]


def safe_branch_name(branch: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in branch)


def remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def copy_file_or_symlink(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() or dest.is_symlink():
        remove_path(dest)
    if src.is_symlink():
        os.symlink(os.readlink(src), dest)
    else:
        shutil.copy2(src, dest)


def overlay_worktree_files(repo_root: Path, clone_path: Path) -> None:
    for rel in git_nul_paths(["ls-files", "-z", "--deleted"], repo_root):
        dest = clone_path / rel
        if dest.exists() or dest.is_symlink():
            remove_path(dest)

    paths = git_nul_paths(["ls-files", "-z", "--cached", "--modified", "--others", "--exclude-standard"], repo_root)
    for rel in paths:
        src = repo_root / rel
        # Gitlink entries for submodules are paths in git output, but
        # directories in the source checkout. Copy only files and symlinks so
        # checked-out submodule working trees do not get bundled.
        if src.is_file() or src.is_symlink():
            copy_file_or_symlink(src, clone_path / rel)


def context_basename(src: Path) -> str:
    base = src.name
    if base in RESERVED_CONTEXT_NAMES:
        fail(f"context basename is reserved: {base}")
    return base


def copy_context_dir(src: Path, dest: Path) -> None:
    def ignore(_dir: str, names: list[str]) -> set[str]:
        return {name for name in names if name in IGNORED_CONTEXT_DIR_NAMES}

    shutil.copytree(src, dest, symlinks=True, ignore=ignore)


def write_context_manifest(context_root: Path, entries: list[dict[str, str]]) -> None:
    context_root.mkdir(parents=True, exist_ok=True)
    text = render_template("CONTEXT_MANIFEST.md.j2", entries=entries)
    (context_root / "MANIFEST.md").write_text(text, encoding="utf-8")


def add_context(clone_path: Path, prompt_md: Path | None, context_paths: list[Path]) -> None:
    if not prompt_md and not context_paths:
        return

    context_root = clone_path / "_repo_zip_context"
    context_root.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, str]] = []

    if prompt_md:
        if not prompt_md.is_file():
            fail(f"prompt Markdown not found: {prompt_md}")
        copy_file_or_symlink(prompt_md, context_root / "PROMPT.md")
        entries.append({"src": str(prompt_md), "dest": "_repo_zip_context/PROMPT.md"})

    used_names = set(RESERVED_CONTEXT_NAMES)
    for src in context_paths:
        if not src.exists() and not src.is_symlink():
            fail(f"context path not found: {src}")
        base = context_basename(src)
        if base in used_names:
            fail(f"duplicate context basename: {base}")
        used_names.add(base)

        dest = context_root / base
        if src.is_file() or src.is_symlink():
            copy_file_or_symlink(src, dest)
            entries.append({"src": str(src), "dest": f"_repo_zip_context/{base}"})
        elif src.is_dir():
            copy_context_dir(src, dest)
            entries.append({"src": f"{src}/", "dest": f"_repo_zip_context/{base}/"})
        else:
            fail(f"unsupported context path type: {src}")

    write_context_manifest(context_root, entries)


def zipinfo_for_path(path: Path, arcname: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(arcname)
    st = path.lstat()
    info.date_time = datetime.fromtimestamp(st.st_mtime).timetuple()[:6]
    info.external_attr = (st.st_mode & 0xFFFF) << 16
    if path.is_symlink():
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
    return info


def write_zip_entry(zf: zipfile.ZipFile, path: Path, arcname: str) -> None:
    if path.is_symlink():
        zf.writestr(zipinfo_for_path(path, arcname), os.readlink(path).encode())
    elif path.is_file():
        zf.write(path, arcname)
    elif path.is_dir():
        dir_arcname = arcname if arcname.endswith("/") else f"{arcname}/"
        zf.writestr(zipinfo_for_path(path, dir_arcname), b"")


def create_zip(source_root: Path, output_path: Path) -> None:
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        write_zip_entry(zf, source_root, source_root.name)
        for root, dirs, files in os.walk(source_root, followlinks=False):
            root_path = Path(root)
            dirs.sort()
            files.sort()
            for dirname in dirs:
                path = root_path / dirname
                arcname = path.relative_to(source_root.parent).as_posix()
                write_zip_entry(zf, path, arcname)
            for filename in files:
                path = root_path / filename
                arcname = path.relative_to(source_root.parent).as_posix()
                write_zip_entry(zf, path, arcname)


def resolve_repo_root() -> Path:
    proc = run_git(["rev-parse", "--show-toplevel"], Path.cwd(), check=False)
    if proc.returncode != 0:
        fail("not inside a Git repository")
    return Path(proc.stdout.decode().strip())


def build_zip(output_dir: Path | None, prompt_md: Path | None, context_paths: list[Path]) -> Path:
    repo_root = resolve_repo_root()
    repo_name = repo_root.name
    repo_parent = repo_root.parent
    resolved_output_dir = output_dir or repo_parent
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    resolved_output_dir = resolved_output_dir.resolve()

    current_branch = git_text(["branch", "--show-current"], repo_root)
    head_sha = git_text(["rev-parse", "HEAD"], repo_root)
    branch_label = current_branch or f"detached-{git_text(['rev-parse', '--short', 'HEAD'], repo_root)}"
    safe_branch = safe_branch_name(branch_label)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_path = resolved_output_dir / f"{repo_name}-repo-{safe_branch}-{stamp}.zip"

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        bundle_path = tmpdir / f"{repo_name}.bundle"
        clone_path = tmpdir / repo_name

        run_git(["bundle", "create", str(bundle_path), "--all"], repo_root)
        run_command(["git", "clone", "--quiet", str(bundle_path), str(clone_path)])

        if current_branch:
            probe = run_git(
                ["rev-parse", "--verify", "--quiet", f"refs/heads/{current_branch}"], clone_path, check=False
            )
            if probe.returncode == 0:
                run_git(["checkout", "--quiet", current_branch], clone_path)
            else:
                run_git(["checkout", "--quiet", head_sha], clone_path)
        else:
            run_git(["checkout", "--quiet", head_sha], clone_path)

        overlay_worktree_files(repo_root, clone_path)
        add_context(clone_path, prompt_md, context_paths)
        create_zip(clone_path, output_path)

    return output_path


def main(
    output_dir: Annotated[
        str | None,
        typer.Argument(help="Directory where the zip will be written."),
    ] = None,
    output_dir_option: Annotated[
        list[str] | None,
        typer.Option("--output-dir", "-o", help="Directory where the zip will be written."),
    ] = None,
    context: Annotated[
        list[str] | None,
        typer.Option("--context", help="Extra file or directory copied into _repo_zip_context/."),
    ] = None,
    prompt_md: Annotated[
        list[str] | None,
        typer.Option("--prompt-md", help="Markdown prompt copied to _repo_zip_context/PROMPT.md."),
    ] = None,
) -> None:
    selected_output_dir = validate_output_dir(output_dir, output_dir_option or [])
    selected_prompt = validate_single(prompt_md or [], "--prompt-md")
    selected_prompt_path = Path(selected_prompt).expanduser() if selected_prompt else None
    selected_context_paths = validate_context_paths(context or [])

    output_path = build_zip(selected_output_dir, selected_prompt_path, selected_context_paths)
    typer.echo(output_path)


if __name__ == "__main__":
    typer.run(main)
