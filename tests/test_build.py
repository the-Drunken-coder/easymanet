"""Tests for Docker-backed image builds."""

from easymanet import build


def test_dockerfile_contents_include_core_packages():
    dockerfile = build._dockerfile_contents()

    assert "FROM ubuntu:24.04" in dockerfile
    assert "git" in dockerfile
    assert "libcap-dev" in dockerfile
    assert "libnl-3-dev" in dockerfile
    assert "libnl-genl-3-dev" in dockerfile
    assert "python3-setuptools" in dockerfile
    assert "subversion" in dockerfile


def test_docker_run_command_mounts_overlay_and_output(monkeypatch, tmp_path):
    overlay = tmp_path / "overlay"
    overlay.mkdir()
    output = tmp_path / "out"
    output.mkdir()

    import os

    monkeypatch.setattr(os, "getuid", lambda: 501)
    monkeypatch.setattr(os, "getgid", lambda: 20)

    command = build._docker_run_command(
        repo_url=build.DEFAULT_OPENMANET_REPO,
        openmanet_version="1.6.5",
        board="ekh-bcm2711",
        target="rpi4-mm6108-spi",
        jobs=8,
        overlay_dir=overlay,
        output_dir=output,
        clean=False,
        builder_image="builder:test",
    )

    assert command[:3] == ["docker", "run", "--rm"]
    assert "HOST_UID=501" in command
    assert "HOST_GID=20" in command
    assert f"type=volume,source={build.DEFAULT_CACHE_VOLUME},target=/cache" in command
    assert f"{overlay}:/overlay:ro" in command
    assert f"{output}:/out" in command
    assert "builder:test" in command


def test_container_script_builds_expected_artifact():
    script = build._container_script(
        repo_url="https://github.com/OpenMANET/firmware.git",
        openmanet_version="1.6.5",
        board="ekh-bcm2711",
        target="rpi4-mm6108-spi",
        jobs=8,
        clean=False,
    )

    assert "./scripts/openmanet_setup.sh -i -b ekh-bcm2711" in script
    assert 'cp -R /overlay/* files/' in script
    assert 'make -j8' in script
    assert 'openmanet-*-${TARGET}-squashfs-sysupgrade.img.gz' in script


def test_build_image_returns_expected_artifact(monkeypatch, tmp_path):
    output = tmp_path / "dist"
    overlay = tmp_path / "overlay"
    overlay.mkdir(parents=True)
    (overlay / "README.md").write_text("overlay")

    monkeypatch.setattr(build, "_overlay_dir", lambda: overlay)
    monkeypatch.setattr(build, "_ensure_builder_image", lambda *args, **kwargs: None)
    monkeypatch.setattr(build, "_ensure_build_dirs", lambda: None)

    def fake_run(cmd, check=False, timeout=None, **kwargs):
        del check, timeout, kwargs
        if cmd[0:2] == ["docker", "run"]:
            output.mkdir(parents=True, exist_ok=True)
            artifact = output / "openmanet-1.6.5-rpi4-mm6108-spi-squashfs-sysupgrade.img.gz"
            artifact.write_bytes(b"image")

        class Result:
            returncode = 0

        return Result()

    monkeypatch.setattr(build.subprocess, "run", fake_run)

    artifact = build.build_image(output_dir=str(output))

    assert artifact == output / "openmanet-1.6.5-rpi4-mm6108-spi-squashfs-sysupgrade.img.gz"
    assert artifact.exists()
