import importlib.util
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "publish_product_repos.py"


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


def test_publish_script_stays_decomposed():
    assert len(SCRIPT_PATH.read_text().splitlines()) < 1000


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

    assert (generated["images"] / "tests" / "test_image_workflows.py").exists()
    assert not (generated["cli"] / "tests" / "test_image_workflows.py").exists()

    image_workflows = generated["images"] / ".github" / "workflows"
    assert (image_workflows / "image-release.yml").exists()
    assert not (image_workflows / "build-openmanet-image.yml").exists()
    assert not (image_workflows / "prove-overlay-weekly.yml").exists()


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


def test_publish_workflow_does_not_expand_inputs_inside_shell():
    workflow = (ROOT / ".github" / "workflows" / "publish-product-repos.yml").read_text()
    run_block = workflow.split("run: |", 1)[1].split("      - name: Upload", 1)[0]

    assert "${{ inputs." not in run_block
