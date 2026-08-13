#!/usr/bin/env python3
"""Generate and optionally publish EasyMANET public product repositories."""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
from pathlib import Path
import sys
import tarfile
import tempfile


ROOT = Path(__file__).resolve().parents[2]
PUBLISH_SRC = ROOT / "tools" / "publish" / "src"
if str(PUBLISH_SRC) not in sys.path:
    sys.path.insert(0, str(PUBLISH_SRC))

from easymanet_publish.surfaces import (  # noqa: E402
    SURFACES,
    SurfaceSpec,
    project_version,
    render_surface_pyproject,
    selected_surface_specs,
    tracked_files,
)

DEFAULT_OWNER = "the-Drunken-coder"
DEFAULT_OUTPUT_DIR = ROOT / "build" / "product-repos"
GITHUB_HOST = "github.com"


def existing_path(*candidates: str) -> str:
    for rel_path in candidates:
        if (ROOT / rel_path).exists():
            return rel_path
    raise FileNotFoundError(f"None of these source paths exist: {', '.join(candidates)}")


def optional_existing_paths(*candidates: str) -> tuple[str, ...]:
    return tuple(rel_path for rel_path in candidates if (ROOT / rel_path).exists())


RepoSpec = SurfaceSpec
REPO_SPECS = SURFACES


def run(
    args: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        env=env,
        input=input_text,
        text=True,
        check=check,
        capture_output=True,
    )


def git_output(args: list[str], *, cwd: Path = ROOT) -> str:
    return run(["git", *args], cwd=cwd).stdout.strip()


def selected_specs(product: str) -> list[RepoSpec]:
    return selected_surface_specs(product)


def tracked_files_for(rel_path: str) -> tuple[str, ...]:
    return tracked_files(ROOT, rel_path)


def source_files(source_root: Path, rel_path: str) -> tuple[str, ...]:
    if source_root.resolve() == ROOT.resolve():
        return tracked_files_for(rel_path)

    source = source_root / rel_path
    if source.is_file():
        return (rel_path,)
    if not source.is_dir():
        raise FileNotFoundError(f"Source path does not exist: {rel_path}")
    files = tuple(
        path.relative_to(source_root).as_posix()
        for path in sorted(source.rglob("*"))
        if path.is_file()
    )
    if not files:
        raise FileNotFoundError(f"Source path has no files: {rel_path}")
    return files


def copy_source_path(rel_path: str, target_root: Path, source_root: Path) -> None:
    for tracked_file in source_files(source_root, rel_path):
        src = source_root / tracked_file
        if src.is_symlink():
            raise ValueError(f"Tracked surface files cannot be symbolic links: {tracked_file}")
        dest = target_root / tracked_file
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)


def copy_template_tree(spec: RepoSpec, target_root: Path, source_root: Path) -> None:
    template_dir = spec.template_dir(source_root)
    if not template_dir.is_dir():
        raise FileNotFoundError(f"Template directory does not exist: {template_dir}")

    template_path = template_dir.relative_to(source_root).as_posix()
    for tracked_file in source_files(source_root, template_path):
        src = source_root / tracked_file
        if src.is_symlink():
            raise ValueError(f"Tracked surface files cannot be symbolic links: {tracked_file}")
        dest = target_root / src.relative_to(template_dir)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)


def write_text_file(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents.rstrip() + "\n")


def generation_metadata(spec: RepoSpec, source_ref: str, source_sha: str) -> str:
    return f"""# Generated Repository

This repository is a generated EasyMANET public product surface.

- Product key: `{spec.key}`
- Public repo: `{spec.repo_name}`
- Authoring repo: `the-Drunken-coder/easymanet`
- Source ref: `{source_ref}`
- Source commit: `{source_sha}`

Normal development should happen in the authoring repo. Changes are published
here by the authoring repo publish process so the public product surfaces do
not drift from the shared EasyMANET model.
"""


def generate_repo(
    spec: RepoSpec,
    output_dir: Path,
    source_ref: str,
    source_sha: str,
    source_root: Path | None = None,
) -> Path:
    source_root = source_root or ROOT
    repo_dir = output_dir / spec.repo_name
    if repo_dir.exists():
        shutil.rmtree(repo_dir)
    repo_dir.mkdir(parents=True)

    for rel_path in spec.source_paths:
        copy_source_path(rel_path, repo_dir, source_root)

    copy_template_tree(spec, repo_dir, source_root)
    write_text_file(
        repo_dir / "pyproject.toml",
        render_surface_pyproject(spec, project_version(source_root / "pyproject.toml")),
    )
    write_text_file(repo_dir / "REPO_GENERATION.md", generation_metadata(spec, source_ref, source_sha))
    return repo_dir


def validate_source_commit(source_sha: str) -> str:
    resolved_sha = git_output(["rev-parse", f"{source_sha}^{{commit}}"], cwd=ROOT)
    head_sha = git_output(["rev-parse", "HEAD"], cwd=ROOT)
    if resolved_sha != head_sha:
        raise SystemExit(
            f"Source commit {resolved_sha} does not match checked-out HEAD {head_sha}"
        )

    for diff_args in (["diff", "--quiet"], ["diff", "--cached", "--quiet"]):
        result = run(["git", *diff_args], cwd=ROOT, check=False)
        if result.returncode != 0:
            raise SystemExit(
                "Tracked source changes must be committed before generating public repositories"
            )
    return resolved_sha


def materialize_source_commit(source_sha: str, destination: Path) -> Path:
    archive_path = destination / "source.tar"
    source_root = destination / "source"
    source_root.mkdir(parents=True)
    run(
        ["git", "archive", "--format=tar", "--output", str(archive_path), source_sha],
        cwd=ROOT,
    )

    with tarfile.open(archive_path, "r") as archive:
        for member in archive.getmembers():
            relative = Path(member.name)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError(f"Git archive contained an unsafe path: {member.name}")
            target = source_root / relative
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                raise ValueError(f"Git archive contained a non-file entry: {member.name}")
            source = archive.extractfile(member)
            if source is None:
                raise ValueError(f"Git archive file could not be read: {member.name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("wb") as output:
                shutil.copyfileobj(source, output)
            target.chmod(member.mode & 0o777)
    archive_path.unlink()
    return source_root


def github_repo_exists(owner: str, spec: RepoSpec) -> bool:
    result = run(
        ["gh", "repo", "view", f"{owner}/{spec.repo_name}", "--json", "name"],
        env=github_cli_env(),
        check=False,
    )
    return result.returncode == 0


def create_github_repo(owner: str, spec: RepoSpec) -> None:
    run(
        [
            "gh",
            "repo",
            "create",
            f"{owner}/{spec.repo_name}",
            "--public",
            "--description",
            spec.description,
            "--disable-wiki",
            "--clone=false",
        ],
        env=github_cli_env(),
    )


def publish_token() -> str | None:
    return os.environ.get("EASYMANET_PUBLIC_REPO_TOKEN") or os.environ.get("GH_TOKEN")


def github_cli_env() -> dict[str, str] | None:
    token = publish_token()
    if not token:
        return None

    env = os.environ.copy()
    env["GH_TOKEN"] = token
    return env


def remote_url(owner: str, spec: RepoSpec) -> str:
    return f"https://{GITHUB_HOST}/{owner}/{spec.repo_name}.git"


def git_auth_env() -> dict[str, str] | None:
    token = publish_token()
    if not token:
        return None

    env = os.environ.copy()
    try:
        index = int(env.get("GIT_CONFIG_COUNT", "0"))
    except ValueError:
        index = 0
    encoded = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    env["GIT_CONFIG_COUNT"] = str(index + 1)
    env[f"GIT_CONFIG_KEY_{index}"] = f"http.https://{GITHUB_HOST}/.extraheader"
    env[f"GIT_CONFIG_VALUE_{index}"] = f"AUTHORIZATION: basic {encoded}"
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def remote_default_branch(owner: str, spec: RepoSpec) -> str:
    result = run(
        ["git", "ls-remote", "--symref", remote_url(owner, spec), "HEAD"],
        env=git_auth_env(),
        check=False,
    )
    if result.returncode != 0:
        return "main"

    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0] == "ref:" and parts[2] == "HEAD":
            ref = parts[1]
            if ref.startswith("refs/heads/"):
                return ref.removeprefix("refs/heads/")
    return "main"


def clear_worktree(path: Path) -> None:
    for child in path.iterdir():
        if child.name == ".git":
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def checkout_branch(worktree_dir: Path, branch: str) -> None:
    remote_branch = f"origin/{branch}"
    result = run(["git", "rev-parse", "--verify", remote_branch], cwd=worktree_dir, check=False)
    if result.returncode == 0:
        run(["git", "checkout", "-B", branch, remote_branch], cwd=worktree_dir)
    else:
        run(["git", "checkout", "-B", branch], cwd=worktree_dir)


def ensure_worktree(owner: str, spec: RepoSpec, worktree_dir: Path) -> str:
    url = remote_url(owner, spec)
    branch = remote_default_branch(owner, spec)
    auth_env = git_auth_env()
    if (worktree_dir / ".git").exists():
        run(["git", "remote", "set-url", "origin", url], cwd=worktree_dir)
        run(["git", "fetch", "origin"], cwd=worktree_dir, env=auth_env)
        checkout_branch(worktree_dir, branch)
        return branch

    worktree_dir.parent.mkdir(parents=True, exist_ok=True)
    run(["git", "clone", url, str(worktree_dir)], env=auth_env)
    checkout_branch(worktree_dir, branch)
    return branch


def sync_to_remote(owner: str, spec: RepoSpec, generated_dir: Path, output_dir: Path, source_sha: str) -> str | None:
    worktree_dir = output_dir.parent / "product-repo-worktrees" / spec.repo_name
    branch = ensure_worktree(owner, spec, worktree_dir)
    clear_worktree(worktree_dir)
    shutil.copytree(generated_dir, worktree_dir, dirs_exist_ok=True)

    run(["git", "config", "user.name", "EasyMANET Publisher"], cwd=worktree_dir)
    run(["git", "config", "user.email", "easymanet-publisher@users.noreply.github.com"], cwd=worktree_dir)
    run(["git", "add", "-A"], cwd=worktree_dir)

    diff = run(["git", "diff", "--cached", "--quiet"], cwd=worktree_dir, check=False)
    if diff.returncode == 0:
        return None

    run(
        [
            "git",
            "commit",
            "-m",
            f"Publish generated {spec.key} surface",
            "-m",
            f"Source commit: {source_sha}",
        ],
        cwd=worktree_dir,
    )
    run(["git", "push", "origin", branch], cwd=worktree_dir, env=git_auth_env())
    return git_output(["rev-parse", "HEAD"], cwd=worktree_dir)


def dispatch_release(owner: str, spec: RepoSpec, payload: dict[str, str]) -> None:
    run(
        [
            "gh",
            "api",
            "--method",
            "POST",
            f"repos/{owner}/{spec.repo_name}/dispatches",
            "--input",
            "-",
        ],
        env=github_cli_env(),
        input_text=json.dumps({"event_type": spec.dispatch_event, "client_payload": payload}),
    )


def build_payload(args: argparse.Namespace, source_ref: str, source_sha: str) -> dict[str, str]:
    payload = {
        "source_repo": args.source_repo,
        "source_ref": source_ref,
        "source_sha": source_sha,
    }
    if args.release_tag:
        payload["release_tag"] = args.release_tag
    if args.publish_pypi:
        payload["publish_pypi"] = "true"
    if args.openmanet_version:
        payload["openmanet_version"] = args.openmanet_version
    if args.board:
        payload["board"] = args.board
    if args.target:
        payload["target"] = args.target
    if args.jobs:
        payload["jobs"] = str(args.jobs)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--product", choices=["all", *REPO_SPECS.keys()], default="all")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--remote-owner", default=DEFAULT_OWNER)
    parser.add_argument("--source-repo", default="the-Drunken-coder/easymanet")
    parser.add_argument("--source-ref", default=os.environ.get("GITHUB_REF_NAME", ""))
    parser.add_argument("--source-sha", default=os.environ.get("GITHUB_SHA", ""))
    parser.add_argument("--create-missing", action="store_true")
    parser.add_argument("--push", action="store_true")
    parser.add_argument("--dispatch", action="store_true")
    parser.add_argument("--release-tag", default="")
    parser.add_argument("--publish-pypi", action="store_true")
    parser.add_argument("--openmanet-version", default="1.6.5")
    parser.add_argument("--board", default="ekh-bcm2711")
    parser.add_argument("--target", default="rpi4-mm6108-spi")
    parser.add_argument("--jobs", default="2")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.dispatch and not args.push:
        raise SystemExit("--dispatch requires --push so release provenance matches published repo contents")

    source_ref = args.source_ref or git_output(["branch", "--show-current"]) or "unknown"
    requested_source_sha = args.source_sha or git_output(["rev-parse", "HEAD"])
    source_sha = validate_source_commit(requested_source_sha)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    payload = build_payload(args, source_ref, source_sha)
    with tempfile.TemporaryDirectory(prefix="easymanet-publish-source-") as temp_dir:
        source_root = materialize_source_commit(source_sha, Path(temp_dir))
        for spec in selected_specs(args.product):
            generated_dir = generate_repo(
                spec,
                args.output_dir,
                source_ref,
                source_sha,
                source_root,
            )
            print(f"generated {spec.repo_name}: {generated_dir}")

            if args.create_missing and not github_repo_exists(args.remote_owner, spec):
                create_github_repo(args.remote_owner, spec)
                print(f"created {args.remote_owner}/{spec.repo_name}")

            commit_sha = None
            publish_synced = False
            if args.push:
                commit_sha = sync_to_remote(
                    args.remote_owner,
                    spec,
                    generated_dir,
                    args.output_dir,
                    source_sha,
                )
                publish_synced = True
                if commit_sha:
                    print(f"pushed {args.remote_owner}/{spec.repo_name}@{commit_sha}")
                else:
                    print(f"no changes for {args.remote_owner}/{spec.repo_name}")

            if args.dispatch and publish_synced:
                dispatch_release(args.remote_owner, spec, payload)
                print(f"dispatched {spec.dispatch_event} to {args.remote_owner}/{spec.repo_name}")
            elif args.dispatch:
                print(
                    f"skipped dispatch for {args.remote_owner}/{spec.repo_name}: "
                    "publish sync did not run"
                )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
