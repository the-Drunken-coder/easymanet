import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "tools" / "packaging" / "publish_product_repos.py"


def load_publish_module():
    spec = importlib.util.spec_from_file_location("publish_product_repos", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_cli_repo_spec_does_not_copy_image_workflow():
    publish = load_publish_module()

    assert ".github/workflows/build-openmanet-image.yml" not in publish.REPO_SPECS["cli"].source_paths
    assert "tests/test_publish_product_repos.py" not in publish.REPO_SPECS["cli"].source_paths
    assert "apps/cli" not in publish.COMMON_PRODUCT_SOURCE_PATHS
    assert "packages/image" not in publish.COMMON_PRODUCT_SOURCE_PATHS
    for rel_path in publish.CLI_RUNTIME_SOURCE_PATHS:
        assert rel_path in publish.REPO_SPECS["cli"].source_paths
        assert rel_path in publish.REPO_SPECS["images"].source_paths


def test_publish_script_stays_decomposed():
    assert len(SCRIPT_PATH.read_text().splitlines()) < 1000


def test_repo_spec_source_paths_exist_in_current_layout():
    publish = load_publish_module()

    for spec in publish.selected_specs("all"):
        for rel_path in spec.source_paths:
            assert (ROOT / rel_path).exists(), f"{spec.key} source path is missing: {rel_path}"


def test_generated_product_repos_exclude_authoring_only_files(tmp_path):
    publish = load_publish_module()

    generated = {
        spec.key: publish.generate_repo(spec, tmp_path, "review-branch", "source-sha")
        for spec in publish.selected_specs("all")
    }

    for key in ("images", "cli"):
        repo = generated[key]
        assert not (repo / "tests" / "test_publish_product_repos.py").exists()
        assert not (repo / ".github" / "workflows" / "publish-product-repos.yml").exists()
        assert not (repo / "docs" / "public-repos.md").exists()
        assert not (repo / "docs" / "problems").exists()
        assert not (repo / "docs" / "design-decisions").exists()
        assert not list(repo.rglob("__pycache__"))
        metadata = (repo / "REPO_GENERATION.md").read_text(encoding="utf-8")
        assert "Generated at:" not in metadata

        ci_workflow = (repo / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        assert "easymanet --help" in ci_workflow
        assert "easymanet.cli" not in ci_workflow
        assert "images/openmanet/provisioning/openwrt-overlay" in ci_workflow
        assert "tools/packaging/verify_overlay_packaging.py" in ci_workflow
        assert "scripts/verify_overlay_packaging.py" in ci_workflow

        packaging_test = (ROOT / "tests" / "test_packaging.py").read_text(encoding="utf-8")
        if "tools/release_smoke.py" in packaging_test:
            assert (repo / "tools" / "release_smoke.py").exists()

    assert (generated["images"] / "tests" / "test_image_workflows.py").exists()
    assert not (generated["cli"] / "tests" / "test_image_workflows.py").exists()

    image_workflows = generated["images"] / ".github" / "workflows"
    assert (image_workflows / "image-release.yml").exists()
    assert not (image_workflows / "build-openmanet-image.yml").exists()
    assert not (image_workflows / "prove-overlay-weekly.yml").exists()
    image_release = (image_workflows / "image-release.yml").read_text(encoding="utf-8")
    assert "packages/image/src/easymanet_image/build.py" in image_release
    assert "images/openmanet/provisioning/openwrt-overlay/**" in image_release
    assert 'raise SystemExit("No firmware artifacts (*.img.gz) were produced")' in image_release


def test_generated_desktop_repo_contains_packaging_sources_and_surface_pyproject(tmp_path):
    publish = load_publish_module()

    repo = publish.generate_repo(
        publish.REPO_SPECS["desktop"],
        tmp_path,
        "review-branch",
        "source-sha",
    )

    assert (repo / "pyproject.toml").exists()
    assert (repo / "apps" / "desktop" / "electron" / "package.json").exists()
    assert (repo / "apps" / "desktop" / "electron" / "electron-builder.yml").exists()
    assert (repo / "tests" / "test_desktop.py").exists()
    assert not (repo / "tools" / "packaging" / "publish_product_repos.py").exists()

    pyproject = (repo / "pyproject.toml").read_text(encoding="utf-8")
    assert 'name = "easymanet-desktop"' in pyproject
    assert 'easymanet-desktop = "easymanet_desktop.server:main"' in pyproject
    assert '"easymanet_desktop" = ["static/*"]' in pyproject


def test_generation_metadata_is_deterministic():
    publish = load_publish_module()

    first = publish.generation_metadata(publish.REPO_SPECS["cli"], "main", "source-sha")
    second = publish.generation_metadata(publish.REPO_SPECS["cli"], "main", "source-sha")

    assert first == second
    assert "Generated at:" not in first


def test_tracked_files_for_rejects_existing_untracked_source(monkeypatch, tmp_path):
    publish = load_publish_module()
    (tmp_path / "local-only.txt").write_text("secret-ish local content\n")

    monkeypatch.setattr(publish, "ROOT", tmp_path)
    monkeypatch.setattr(publish, "git_output", lambda _args: "")

    with pytest.raises(FileNotFoundError, match="has no tracked files"):
        publish.tracked_files_for("local-only.txt")


def test_remote_url_never_embeds_publish_token(monkeypatch):
    publish = load_publish_module()
    monkeypatch.setenv("EASYMANET_PUBLIC_REPO_TOKEN", "secret-token")

    url = publish.remote_url("example", publish.REPO_SPECS["cli"])

    assert url == "https://github.com/example/easymanet-cli.git"
    assert "secret-token" not in url


def test_git_auth_env_injects_header_without_remote_url_token(monkeypatch):
    publish = load_publish_module()
    monkeypatch.setenv("EASYMANET_PUBLIC_REPO_TOKEN", "secret-token")

    env = publish.git_auth_env()

    assert env is not None
    assert env["GIT_CONFIG_COUNT"] == "1"
    assert env["GIT_CONFIG_KEY_0"] == "http.https://github.com/.extraheader"
    assert "secret-token" not in env["GIT_CONFIG_VALUE_0"]
    assert env["GIT_TERMINAL_PROMPT"] == "0"


def test_github_cli_env_maps_publish_token_to_gh_token(monkeypatch):
    publish = load_publish_module()
    monkeypatch.setenv("EASYMANET_PUBLIC_REPO_TOKEN", "secret-token")
    monkeypatch.delenv("GH_TOKEN", raising=False)

    env = publish.github_cli_env()

    assert env is not None
    assert env["GH_TOKEN"] == "secret-token"


def test_github_cli_env_prefers_publish_token_over_existing_gh_token(monkeypatch):
    publish = load_publish_module()
    monkeypatch.setenv("EASYMANET_PUBLIC_REPO_TOKEN", "publish-token")
    monkeypatch.setenv("GH_TOKEN", "default-token")

    env = publish.github_cli_env()

    assert env is not None
    assert env["GH_TOKEN"] == "publish-token"


def test_remote_default_branch_parses_symref(monkeypatch):
    publish = load_publish_module()

    def fake_run(args, **kwargs):
        assert args[:3] == ["git", "ls-remote", "--symref"]
        return subprocess.CompletedProcess(
            args,
            0,
            stdout="ref: refs/heads/trunk\tHEAD\nabc123\tHEAD\n",
            stderr="",
        )

    monkeypatch.setattr(publish, "run", fake_run)

    assert publish.remote_default_branch("example", publish.REPO_SPECS["cli"]) == "trunk"


def test_remote_default_branch_falls_back_to_main_on_error(monkeypatch):
    publish = load_publish_module()

    def fake_run(args, **kwargs):
        assert args[:3] == ["git", "ls-remote", "--symref"]
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="error")

    monkeypatch.setattr(publish, "run", fake_run)

    assert publish.remote_default_branch("example", publish.REPO_SPECS["cli"]) == "main"


def test_ensure_worktree_uses_detected_default_branch(monkeypatch, tmp_path):
    publish = load_publish_module()
    worktree = tmp_path / "worktree"
    (worktree / ".git").mkdir(parents=True)
    calls = []

    monkeypatch.setattr(publish, "remote_default_branch", lambda _owner, _spec: "stable")

    def fake_run(args, **kwargs):
        calls.append((args, kwargs.get("cwd")))
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(publish, "run", fake_run)

    branch = publish.ensure_worktree("example", publish.REPO_SPECS["cli"], worktree)

    assert branch == "stable"
    assert (["git", "fetch", "origin"], worktree) in calls
    assert (["git", "rev-parse", "--verify", "origin/stable"], worktree) in calls
    assert (["git", "checkout", "-B", "stable", "origin/stable"], worktree) in calls


def test_sync_to_remote_pushes_detected_branch(monkeypatch, tmp_path):
    publish = load_publish_module()
    output_dir = tmp_path / "out"
    generated_dir = tmp_path / "generated"
    worktree = output_dir.parent / "product-repo-worktrees" / publish.REPO_SPECS["cli"].name
    generated_dir.mkdir()
    (generated_dir / "README.md").write_text("generated\n")
    (worktree / ".git").mkdir(parents=True)
    calls = []

    def fake_ensure_worktree(_owner, _spec, _worktree):
        assert _worktree == worktree
        return "stable"

    def fake_run(args, **kwargs):
        calls.append((args, kwargs.get("cwd")))
        if args == ["git", "diff", "--cached", "--quiet"]:
            return subprocess.CompletedProcess(args, 1, stdout="", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(publish, "ensure_worktree", fake_ensure_worktree)
    monkeypatch.setattr(publish, "run", fake_run)
    monkeypatch.setattr(publish, "git_output", lambda _args, cwd=None: "published-sha")

    commit_sha = publish.sync_to_remote(
        "example",
        publish.REPO_SPECS["cli"],
        generated_dir,
        output_dir,
        "source-sha",
    )

    assert commit_sha == "published-sha"
    assert (["git", "push", "origin", "stable"], worktree) in calls


def test_sync_to_remote_skips_push_when_no_changes(monkeypatch, tmp_path):
    publish = load_publish_module()
    output_dir = tmp_path / "out"
    generated_dir = tmp_path / "generated"
    worktree = output_dir.parent / "product-repo-worktrees" / publish.REPO_SPECS["cli"].name
    generated_dir.mkdir()
    (generated_dir / "README.md").write_text("generated\n")
    (worktree / ".git").mkdir(parents=True)
    calls = []

    def fake_ensure_worktree(_owner, _spec, _worktree):
        assert _worktree == worktree
        return "stable"

    def fake_run(args, **kwargs):
        calls.append((args, kwargs.get("cwd")))
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(publish, "ensure_worktree", fake_ensure_worktree)
    monkeypatch.setattr(publish, "run", fake_run)
    monkeypatch.setattr(publish, "git_output", lambda _args, cwd=None: "published-sha")

    commit_sha = publish.sync_to_remote(
        "example",
        publish.REPO_SPECS["cli"],
        generated_dir,
        output_dir,
        "source-sha",
    )

    assert commit_sha is None
    assert (["git", "push", "origin", "stable"], worktree) not in calls


def publish_args(tmp_path, **overrides):
    values = {
        "product": "cli",
        "output_dir": tmp_path / "out",
        "remote_owner": "example",
        "source_repo": "example/easymanet",
        "source_ref": "feature",
        "source_sha": "source-sha",
        "create_missing": False,
        "push": False,
        "dispatch": False,
        "release_tag": "",
        "openmanet_version": "1.6.5",
        "board": "ekh-bcm2711",
        "target": "rpi4-mm6108-spi",
        "jobs": "2",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_main_rejects_dispatch_without_push(monkeypatch, tmp_path):
    publish = load_publish_module()
    monkeypatch.setattr(publish, "parse_args", lambda: publish_args(tmp_path, dispatch=True))

    with pytest.raises(SystemExit, match="--dispatch requires --push"):
        publish.main()


def test_main_dispatches_after_published_commit(monkeypatch, tmp_path):
    publish = load_publish_module()
    args = publish_args(tmp_path, push=True, dispatch=True)
    generated_dir = tmp_path / "generated"
    generated_dir.mkdir()
    dispatches = []

    monkeypatch.setattr(publish, "parse_args", lambda: args)
    monkeypatch.setattr(publish, "selected_specs", lambda _product: [publish.REPO_SPECS["cli"]])
    monkeypatch.setattr(publish, "generate_repo", lambda *_args: generated_dir)
    monkeypatch.setattr(publish, "sync_to_remote", lambda *_args: "published-sha")
    monkeypatch.setattr(publish, "dispatch_release", lambda *call_args: dispatches.append(call_args))

    assert publish.main() == 0

    assert len(dispatches) == 1


def test_main_dispatches_when_push_has_no_changes(monkeypatch, tmp_path):
    publish = load_publish_module()
    args = publish_args(tmp_path, push=True, dispatch=True)
    generated_dir = tmp_path / "generated"
    generated_dir.mkdir()
    dispatches = []

    monkeypatch.setattr(publish, "parse_args", lambda: args)
    monkeypatch.setattr(publish, "selected_specs", lambda _product: [publish.REPO_SPECS["cli"]])
    monkeypatch.setattr(publish, "generate_repo", lambda *_args: generated_dir)
    monkeypatch.setattr(publish, "sync_to_remote", lambda *_args: None)
    monkeypatch.setattr(publish, "dispatch_release", lambda *call_args: dispatches.append(call_args))

    assert publish.main() == 0

    assert len(dispatches) == 1


def test_publish_workflow_does_not_expand_inputs_inside_shell():
    workflow = (ROOT / ".github" / "workflows" / "publish-product-repos.yml").read_text()
    run_block = workflow.split("run: |", 1)[1].split("      - name: Upload", 1)[0]

    assert "${{ inputs." not in run_block
