#!/usr/bin/env python3
"""Generate and optionally publish EasyMANET public product repositories."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OWNER = "the-Drunken-coder"
DEFAULT_OUTPUT_DIR = ROOT / "build" / "product-repos"
GITHUB_HOST = "github.com"
TEMPLATE_ROOT = ROOT / "product_repos" / "templates"


def existing_path(*candidates: str) -> str:
    for rel_path in candidates:
        if (ROOT / rel_path).exists():
            return rel_path
    raise FileNotFoundError(f"None of these source paths exist: {', '.join(candidates)}")


def optional_existing_paths(*candidates: str) -> tuple[str, ...]:
    return tuple(rel_path for rel_path in candidates if (ROOT / rel_path).exists())


PRODUCT_DOC_PATHS = (
    "docs/README.md",
    "docs/architecture.md",
    "docs/flashing.md",
    "docs/lessons-learned.md",
    "docs/manifest.md",
    "docs/openmanet-config-investigation.md",
)

PRODUCT_TEST_PATHS = (
    "tests/shell_harness",
    "tests/test_build.py",
    "tests/test_cli.py",
    "tests/test_cli_common.py",
    "tests/test_disks.py",
    "tests/test_download.py",
    "tests/test_extra_packages.py",
    "tests/test_firstboot.py",
    "tests/test_image.py",
    "tests/test_inject.py",
    "tests/test_manifest.py",
    "tests/test_packaging.py",
    "tests/test_privileges.py",
    "tests/test_provision_behavior.py",
    "tests/test_render.py",
    "tests/test_sysctl.py",
    "tests/test_validate.py",
)

COMMON_PRODUCT_SOURCE_PATHS = (
    ".gitignore",
    "pyproject.toml",
    *PRODUCT_DOC_PATHS,
    existing_path("packages/core/src/easymanet", "easymanet"),
    "examples/three-node-field-mesh.yml",
    existing_path("images/openmanet/provisioning", "provisioning"),
    existing_path("tools/packaging/verify_overlay_packaging.py", "scripts/verify_overlay_packaging.py"),
    *optional_existing_paths("tools/release_smoke.py"),
    *PRODUCT_TEST_PATHS,
)

CLI_RUNTIME_SOURCE_PATHS = optional_existing_paths("apps/cli", "packages/image")

CLI_PRODUCT_SOURCE_PATHS = COMMON_PRODUCT_SOURCE_PATHS + CLI_RUNTIME_SOURCE_PATHS

IMAGE_PRODUCT_SOURCE_PATHS = COMMON_PRODUCT_SOURCE_PATHS + CLI_RUNTIME_SOURCE_PATHS + (
    "tests/test_image_workflows.py",
)

DESKTOP_CORE_PACKAGE_PATH = existing_path("packages/core/src/easymanet", "easymanet")
DESKTOP_PRODUCT_SOURCE_PATHS = (
    ".gitignore",
    "docs/manifest.md",
    "examples/three-node-field-mesh.yml",
    DESKTOP_CORE_PACKAGE_PATH,
    "apps/desktop",
    "tests/test_desktop.py",
)


@dataclass(frozen=True)
class RepoSpec:
    key: str
    name: str
    description: str
    source_paths: tuple[str, ...]
    template_dir: Path
    dispatch_event: str
    release_workflow: str


REPO_SPECS = {
    "images": RepoSpec(
        key="images",
        name="easymanet-images",
        description="Public firmware image factory for EasyMANET/OpenMANET releases.",
        source_paths=IMAGE_PRODUCT_SOURCE_PATHS,
        template_dir=TEMPLATE_ROOT / "images",
        dispatch_event="easymanet-image-release",
        release_workflow="image-release.yml",
    ),
    "cli": RepoSpec(
        key="cli",
        name="easymanet-cli",
        description="Public CLI and automation surface for EasyMANET.",
        source_paths=CLI_PRODUCT_SOURCE_PATHS,
        template_dir=TEMPLATE_ROOT / "cli",
        dispatch_event="easymanet-cli-release",
        release_workflow="cli-release.yml",
    ),
    "desktop": RepoSpec(
        key="desktop",
        name="easymanet-desktop",
        description="Public local-first desktop operator console for EasyMANET.",
        source_paths=DESKTOP_PRODUCT_SOURCE_PATHS,
        template_dir=TEMPLATE_ROOT / "desktop",
        dispatch_event="easymanet-desktop-release",
        release_workflow="desktop-release.yml",
    ),
}


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
    if product == "all":
        return [REPO_SPECS["images"], REPO_SPECS["cli"], REPO_SPECS["desktop"]]
    return [REPO_SPECS[product]]


def tracked_files_for(rel_path: str) -> tuple[str, ...]:
    source = ROOT / rel_path
    if not source.exists():
        raise FileNotFoundError(f"Source path does not exist: {rel_path}")

    files = tuple(
        line
        for line in git_output(["ls-files", "--", rel_path]).splitlines()
        if line
    )
    if files:
        return files

    raise FileNotFoundError(f"Source path has no tracked files: {rel_path}")


def copy_source_path(rel_path: str, target_root: Path) -> None:
    for tracked_file in tracked_files_for(rel_path):
        src = ROOT / tracked_file
        dest = target_root / tracked_file
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)


def copy_template_tree(spec: RepoSpec, target_root: Path) -> None:
    if not spec.template_dir.is_dir():
        raise FileNotFoundError(f"Template directory does not exist: {spec.template_dir}")

    for src in sorted(spec.template_dir.rglob("*")):
        if src.is_file():
            dest = target_root / src.relative_to(spec.template_dir)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)


def write_text_file(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents.rstrip() + "\n")


def generation_metadata(spec: RepoSpec, source_ref: str, source_sha: str) -> str:
    return f"""# Generated Repository

This repository is a generated EasyMANET public product surface.

- Product key: `{spec.key}`
- Public repo: `{spec.name}`
- Authoring repo: `the-Drunken-coder/easymanet`
- Source ref: `{source_ref}`
- Source commit: `{source_sha}`

Normal development should happen in the authoring repo. Changes are published
here by the authoring repo publish process so the public product surfaces do
not drift from the shared EasyMANET model.
"""


def generate_repo(spec: RepoSpec, output_dir: Path, source_ref: str, source_sha: str) -> Path:
    repo_dir = output_dir / spec.name
    if repo_dir.exists():
        shutil.rmtree(repo_dir)
    repo_dir.mkdir(parents=True)

    for rel_path in spec.source_paths:
        copy_source_path(rel_path, repo_dir)

    copy_template_tree(spec, repo_dir)
    if spec.key == "cli":
        write_text_file(repo_dir / "pyproject.toml", cli_surface_pyproject())
    if spec.key == "desktop":
        write_text_file(repo_dir / "pyproject.toml", desktop_surface_pyproject())
    write_text_file(repo_dir / "REPO_GENERATION.md", generation_metadata(spec, source_ref, source_sha))
    return repo_dir


def cli_surface_pyproject() -> str:
    return with_project_version(
        (TEMPLATE_ROOT / "cli" / "pyproject.toml").read_text(),
        project_version(ROOT / "pyproject.toml"),
    )


def desktop_surface_pyproject() -> str:
    version = project_version(ROOT / "pyproject.toml")
    core_package_root = package_find_root(DESKTOP_CORE_PACKAGE_PATH)
    return f"""[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "easymanet-desktop"
version = "{version}"
description = "Local-first EasyMANET desktop operator console"
readme = "README.md"
requires-python = ">=3.9"
license = "MIT"
authors = [
    {{name = "EasyMANET Contributors"}}
]
keywords = ["openmanet", "mesh", "provisioning", "desktop"]
classifiers = [
    "Development Status :: 3 - Alpha",
    "Intended Audience :: System Administrators",
    "Operating System :: MacOS",
    "Operating System :: POSIX :: Linux",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.9",
    "Topic :: System :: Installation/Setup",
    "Topic :: System :: Systems Administration",
]
dependencies = [
    "typer>=0.9",
    "pyyaml>=6",
]

[project.optional-dependencies]
dev = [
    "pytest>=7",
    "pytest-cov",
    "setuptools>=68",
    "tomli>=2; python_version < '3.11'",
    "wheel",
]

[project.scripts]
easymanet-desktop = "easymanet_desktop.server:main"

[tool.setuptools.packages.find]
where = [
    "{core_package_root}",
    "apps/desktop/src",
]
include = [
    "easymanet*",
    "easymanet_desktop*",
]

[tool.setuptools.package-data]
"easymanet_desktop" = ["static/*"]

[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
pythonpath = [
    "{core_package_root}",
    "apps/desktop/src",
    ".",
]
"""


def package_find_root(package_path: str) -> str:
    parent = Path(package_path).parent.as_posix()
    return "." if parent in {"", "."} else parent


def project_version(pyproject_path: Path) -> str:
    match = re.search(r'^version = "([^"]+)"$', pyproject_path.read_text(), re.MULTILINE)
    if not match:
        raise ValueError(f"Could not find project version in {pyproject_path}")
    return match.group(1)


def with_project_version(pyproject_text: str, version: str) -> str:
    updated, count = re.subn(
        r'^version = "[^"]+"$',
        f'version = "{version}"',
        pyproject_text,
        count=1,
        flags=re.MULTILINE,
    )
    if count != 1:
        raise ValueError("Could not replace project version in pyproject template")
    return updated


def github_repo_exists(owner: str, spec: RepoSpec) -> bool:
    result = run(
        ["gh", "repo", "view", f"{owner}/{spec.name}", "--json", "name"],
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
            f"{owner}/{spec.name}",
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
    return f"https://{GITHUB_HOST}/{owner}/{spec.name}.git"


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
    worktree_dir = output_dir.parent / "product-repo-worktrees" / spec.name
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
            f"repos/{owner}/{spec.name}/dispatches",
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
    source_sha = args.source_sha or git_output(["rev-parse", "HEAD"])
    args.output_dir.mkdir(parents=True, exist_ok=True)

    payload = build_payload(args, source_ref, source_sha)
    for spec in selected_specs(args.product):
        generated_dir = generate_repo(spec, args.output_dir, source_ref, source_sha)
        print(f"generated {spec.name}: {generated_dir}")

        if args.create_missing and not github_repo_exists(args.remote_owner, spec):
            create_github_repo(args.remote_owner, spec)
            print(f"created {args.remote_owner}/{spec.name}")

        commit_sha = None
        publish_synced = False
        if args.push:
            commit_sha = sync_to_remote(args.remote_owner, spec, generated_dir, args.output_dir, source_sha)
            publish_synced = True
            if commit_sha:
                print(f"pushed {args.remote_owner}/{spec.name}@{commit_sha}")
            else:
                print(f"no changes for {args.remote_owner}/{spec.name}")

        if args.dispatch and publish_synced:
            dispatch_release(args.remote_owner, spec, payload)
            print(f"dispatched {spec.dispatch_event} to {args.remote_owner}/{spec.name}")
        elif args.dispatch:
            print(f"skipped dispatch for {args.remote_owner}/{spec.name}: publish sync did not run")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
