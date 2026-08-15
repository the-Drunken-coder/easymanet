"""Tests for config rendering (defaults merging + provision.json output)."""

import json
import os
from pathlib import Path
import tempfile

import pytest
import yaml

from easymanet.manifest import ManifestError, load_manifest
from easymanet.provision import (
    ProvisionAttestation,
    ProvisionPayload,
    provision_json_bool,
    resolve_provision,
)
from easymanet.render import render, render_dict


VALID_CONFIG = """
version: 1

mesh:
  id: test-mesh
  password: "test-password"
  channel: 42
  bandwidth_mhz: 2
  country: US

defaults:
  target: rpi4-mm6108-spi
  local_ap:
    enabled: true
    password: "ap-password"
  management:
    root_password_hash: ""
    ssh_authorized_keys:
      - "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKm8abcdefgh"

nodes:
  node01:
    role: gate
    hostname: node01
    ip: 10.41.1.1
    local_ap:
      ssid: node01-local
    gateway:
      enabled: true
      uplink_interface: eth0
  node02:
    role: point
    hostname: node02
    ip: 10.41.2.1
    local_ap:
      ssid: node02-local
"""


def _write_config(content: str) -> str:
    fd, path = tempfile.mkstemp(suffix=".yml", prefix="easymanet_test_")
    with os.fdopen(fd, "w") as f:
        f.write(content)
    return path


def test_provision_json_bool_does_not_coerce_non_booleans():
    assert provision_json_bool(True) is True
    for value in (False, 1, 0, "true", "false", "yes", None):
        assert provision_json_bool(value) is False


def test_render_valid_provision_json():
    path = _write_config(VALID_CONFIG)
    m = load_manifest(path)
    output = render(m, "node02")
    data = json.loads(output)

    assert data["version"] == 1
    assert data["mesh"]["id"] == "test-mesh"
    assert data["mesh"]["password"] == "test-password"
    assert data["mesh"]["channel"] == 42
    assert data["mesh"]["bandwidth_mhz"] == 2
    assert data["mesh"]["country"] == "US"

    assert data["node"]["name"] == "node02"
    assert data["node"]["hostname"] == "node02"
    assert data["node"]["role"] == "point"
    assert data["node"]["target"] == "rpi4-mm6108-spi"
    assert data["node"]["ip"] == "10.41.2.1"

    assert data["node"]["local_ap"]["enabled"] is True
    assert data["node"]["local_ap"]["ssid"] == "node02-local"
    assert data["node"]["local_ap"]["password"] == "ap-password"

    assert data["node"]["gateway"]["enabled"] is False

    assert data["management"]["root_password_hash"] == ""
    assert len(data["management"]["ssh_authorized_keys"]) == 1

    os.unlink(path)


def test_render_includes_hil_attestation_when_supplied():
    path = _write_config(VALID_CONFIG)
    manifest = load_manifest(path)
    attestation = ProvisionAttestation(
        hil_run_nonce="c" * 32,
        image_sha256="d" * 64,
        fleet_config_sha256="e" * 64,
        source_git_sha="f" * 40,
        hil_started_at="2026-06-30T12:00:00Z",
    )

    data = render_dict(manifest, "node02", attestation=attestation)

    assert data["attestation"] == attestation.to_dict()
    os.unlink(path)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"hil_run_nonce": ""}, "attestation.hil_run_nonce"),
        ({"image_sha256": "not-a-digest"}, "attestation.image_sha256"),
        ({"fleet_config_sha256": "E" * 64}, "attestation.fleet_config_sha256"),
        ({"source_git_sha": "f" * 39}, "attestation.source_git_sha"),
        ({"hil_started_at": "2026-06-30T12:00:00"}, "must include a timezone"),
    ],
)
def test_provision_attestation_rejects_incomplete_or_malformed_values(
    changes,
    message,
):
    values = {
        "hil_run_nonce": "c" * 32,
        "image_sha256": "d" * 64,
        "fleet_config_sha256": "e" * 64,
        "source_git_sha": "f" * 40,
        "hil_started_at": "2026-06-30T12:00:00Z",
        **changes,
    }

    with pytest.raises(ManifestError, match=message):
        ProvisionAttestation.from_mapping(values)


def test_provision_attestation_requires_every_field():
    with pytest.raises(ManifestError, match="attestation.hil_run_nonce is required"):
        ProvisionAttestation.from_mapping({})


def test_render_includes_non_secret_fleet_inventory():
    path = _write_config(VALID_CONFIG)
    m = load_manifest(path)
    data = render_dict(m, "node02")

    assert data["fleet"]["nodes"] == [
        {
            "name": "node01",
            "hostname": "node01",
            "role": "gate",
            "target": "rpi4-mm6108-spi",
            "ip": "10.41.1.1",
        },
        {
            "name": "node02",
            "hostname": "node02",
            "role": "point",
            "target": "rpi4-mm6108-spi",
            "ip": "10.41.2.1",
        },
    ]
    serialized = json.dumps(data["fleet"])
    assert "test-password" not in serialized
    assert "ap-password" not in serialized
    assert "ssh-ed25519" not in serialized
    os.unlink(path)


def test_render_gate_node():
    path = _write_config(VALID_CONFIG)
    m = load_manifest(path)
    data = render_dict(m, "node01")

    assert data["node"]["role"] == "gate"
    assert data["node"]["gateway"]["enabled"] is True
    assert data["node"]["gateway"]["uplink_interface"] == "eth0"
    os.unlink(path)


def test_render_rejects_unknown_node_role():
    path = _write_config(VALID_CONFIG.replace("role: point", "role: gateway"))
    manifest = load_manifest(path)

    with pytest.raises(ManifestError, match="role must be one of"):
        render_dict(manifest, "node02")

    os.unlink(path)


def test_render_defaults_merge():
    config = """
version: 1
mesh:
  id: test
  password: "pw"
  channel: 1
  bandwidth_mhz: 1
  country: US
defaults:
  target: rpi4-mm6108-spi
  local_ap:
    enabled: false
    password: "default-ap-pw"
  management:
    root_password_hash: "$6$hash"
    ssh_authorized_keys: []
nodes:
  n1:
    role: point
    hostname: n1
    ip: 10.0.0.1
    local_ap:
      enabled: true
      ssid: n1-custom
"""
    path = _write_config(config)
    m = load_manifest(path)
    data = render_dict(m, "n1")

    assert data["node"]["local_ap"]["enabled"] is True
    assert data["node"]["local_ap"]["ssid"] == "n1-custom"
    assert data["node"]["local_ap"]["password"] == "default-ap-pw"
    assert data["management"]["root_password_hash"] == "$6$hash"
    os.unlink(path)


def test_resolve_provision_returns_typed_payload_used_by_render():
    path = _write_config(VALID_CONFIG)
    m = load_manifest(path)

    payload = resolve_provision(m, "node02", ssh_enabled=True)

    assert isinstance(payload, ProvisionPayload)
    assert payload.management.ssh_enabled is True
    assert payload.node.local_ap.enabled is True
    assert payload.node.local_ap.ssid == "node02-local"
    assert payload.node.local_ap.password == "ap-password"
    assert payload.node.gateway.enabled is False
    assert payload.node.gateway.wifi is None
    assert payload.to_dict() == render_dict(m, "node02", ssh_enabled=True)
    os.unlink(path)


def test_resolve_provision_includes_api_wan_override():
    path = _write_config(VALID_CONFIG)
    m = load_manifest(path)

    payload = resolve_provision(m, "node01", api_wan_enabled=True)

    assert payload.management.api_wan_enabled is True
    assert payload.to_dict()["management"]["api_wan_enabled"] is True
    assert render_dict(m, "node01", api_wan_enabled=False)["management"]["api_wan_enabled"] is False
    os.unlink(path)


def test_render_deep_merges_gateway_wifi_defaults():
    config = """
version: 1
mesh:
  id: test
  password: "pw"
  channel: 1
  bandwidth_mhz: 1
  country: US
defaults:
  target: rpi4-mm6108-spi
  gateway:
    enabled: true
    wifi:
      enabled: false
      ssid: default-uplink
      password: default-password
  management:
    root_password_hash: ""
    ssh_authorized_keys: []
nodes:
  n1:
    role: gate
    hostname: n1
    ip: 10.0.0.1
    gateway:
      wifi:
        enabled: true
"""
    path = _write_config(config)
    m = load_manifest(path)
    payload = resolve_provision(m, "n1")
    data = render_dict(m, "n1")

    assert payload.node.gateway.enabled is True
    assert payload.node.gateway.wifi is not None
    assert payload.node.gateway.wifi.enabled is True
    assert data["node"]["gateway"]["wifi"] == {
        "enabled": True,
        "ssid": "default-uplink",
        "password": "default-password",
    }
    os.unlink(path)


def test_render_omits_disabled_gateway_wifi_defaults():
    config = """
version: 1
mesh:
  id: test
  password: "pw"
  channel: 42
  bandwidth_mhz: 2
  country: US
defaults:
  target: rpi4-mm6108-spi
  gateway:
    wifi:
      enabled: false
      ssid: operator-uplink
      password: operator-password
  management:
    root_password_hash: ""
    ssh_authorized_keys: []
nodes:
  n1:
    role: point
    hostname: n1
    ip: 10.41.2.1
  n2:
    role: gate
    hostname: n2
    ip: 10.41.3.1
"""
    path = _write_config(config)
    m = load_manifest(path)
    for node_name in ("n1", "n2"):
        payload = resolve_provision(m, node_name)
        data = render_dict(m, node_name)

        assert payload.node.gateway.enabled is (node_name == "n2")
        assert payload.node.gateway.wifi is None
        assert "wifi" not in data["node"]["gateway"]
    os.unlink(path)


def test_render_starter_gate_uses_wifi_uplink_shape():
    root = Path(__file__).resolve().parents[1]
    m = load_manifest(str(root / "examples" / "three-node-field-mesh.yml"))
    gate = render_dict(m, "gate01", ssh_enabled=True)

    assert gate["node"]["gateway"]["enabled"] is True
    assert gate["node"]["gateway"]["uplink_interface"] == "wifi"
    assert gate["node"]["gateway"]["wifi"]["enabled"] is True
    assert gate["node"]["gateway"]["wifi"]["ssid"]
    assert gate["node"]["gateway"]["wifi"]["password"]
    assert gate["node"]["local_ap"]["enabled"] is False
    assert gate["management"]["ssh_enabled"] is True


def test_render_preserves_safe_scalar_content_and_canonical_booleans(tmp_path):
    data = yaml.safe_load(VALID_CONFIG)
    scalar = "  ops 'east' / west \\\\ \"quoted\"  "
    data["mesh"]["id"] = scalar
    data["mesh"]["password"] = scalar
    data["defaults"]["local_ap"]["password"] = scalar
    data["defaults"]["management"]["root_password_hash"] = scalar
    data["nodes"]["node01"]["local_ap"]["ssid"] = scalar
    data["nodes"]["node01"]["local_ap"]["enabled"] = False
    data["nodes"]["node01"]["gateway"] = {
        "enabled": True,
        "uplink_interface": "wifi",
        "wifi": {
            "enabled": True,
            "ssid": scalar,
            "password": scalar,
        },
    }
    path = tmp_path / "safe-scalars.yml"
    path.write_text(yaml.safe_dump(data, sort_keys=False))

    manifest = load_manifest(str(path))
    result = render_dict(manifest, "node01")

    assert result["mesh"]["id"] == scalar
    assert result["mesh"]["password"] == scalar
    assert result["node"]["local_ap"]["ssid"] == scalar
    assert result["node"]["local_ap"]["password"] == scalar
    assert result["node"]["gateway"]["wifi"]["ssid"] == scalar
    assert result["node"]["gateway"]["wifi"]["password"] == scalar
    assert result["management"]["root_password_hash"] == scalar
    assert result["node"]["local_ap"]["enabled"] is False
    assert type(result["node"]["gateway"]["enabled"]) is bool
    assert type(result["node"]["gateway"]["wifi"]["enabled"]) is bool


def test_render_rejects_local_ap_with_gateway_wifi():
    config = VALID_CONFIG.replace(
        "      uplink_interface: eth0",
        """      uplink_interface: wifi
      wifi:
        enabled: true
        ssid: operator-wifi
        password: operator-password""",
        1,
    )
    path = _write_config(config)
    manifest = load_manifest(path)

    with pytest.raises(
        ManifestError,
        match=r"local_ap\.enabled and gateway\.wifi\.enabled cannot both be true",
    ):
        render_dict(manifest, "node01")
    os.unlink(path)


def test_render_derives_gateway_enabled_from_role():
    config = VALID_CONFIG.replace("      enabled: true\n", "", 1)
    path = _write_config(config)
    manifest = load_manifest(path)

    assert render_dict(manifest, "node01")["node"]["gateway"]["enabled"] is True
    assert render_dict(manifest, "node02")["node"]["gateway"]["enabled"] is False
    os.unlink(path)


@pytest.mark.parametrize(
    ("node_name", "gateway", "expected"),
    [
        (
            "node02",
            {"enabled": True, "uplink_interface": "eth0"},
            r"gateway.enabled must match role 'point' \(false\)",
        ),
        (
            "node01",
            {
                "enabled": True,
                "uplink_interface": "eth0",
                "wifi": {
                    "enabled": True,
                    "ssid": "operator-uplink",
                    "password": "operator-password",
                },
            },
            "gateway.wifi.enabled requires gateway.uplink_interface: wifi",
        ),
        (
            "node01",
            {"enabled": True, "uplink_interface": "wifi"},
            "gateway.uplink_interface: wifi requires gateway.wifi.enabled: true",
        ),
    ],
)
def test_render_rejects_gateway_contract_mismatches(
    tmp_path,
    node_name,
    gateway,
    expected,
):
    data = yaml.safe_load(VALID_CONFIG)
    data["nodes"][node_name]["gateway"] = gateway
    path = tmp_path / "fleet.yml"
    path.write_text(yaml.safe_dump(data, sort_keys=False))

    with pytest.raises(ManifestError, match=expected):
        render_dict(load_manifest(str(path)), node_name)


def test_render_omits_ssh_enabled_when_unspecified():
    path = _write_config(VALID_CONFIG)
    m = load_manifest(path)
    gate = render_dict(m, "node01")
    point = render_dict(m, "node02")

    assert "ssh_enabled" not in gate["management"]
    assert "ssh_enabled" not in point["management"]
    os.unlink(path)


def test_render_ssh_enabled_explicit_override():
    path = _write_config(VALID_CONFIG)
    m = load_manifest(path)

    point_on = render_dict(m, "node02", ssh_enabled=True)
    assert point_on["management"]["ssh_enabled"] is True

    gate_off = render_dict(m, "node01", ssh_enabled=False)
    assert gate_off["management"]["ssh_enabled"] is False
    os.unlink(path)


def test_render_no_local_ap():
    config = """
version: 1
mesh:
  id: test
  password: "pw"
  channel: 1
  bandwidth_mhz: 1
  country: US
defaults:
  target: rpi4-mm6108-spi
  management:
    root_password_hash: ""
    ssh_authorized_keys: []
nodes:
  n1:
    role: point
    hostname: n1
    ip: 10.0.0.1
"""
    path = _write_config(config)
    m = load_manifest(path)
    data = render_dict(m, "n1")

    assert data["node"]["local_ap"]["enabled"] is False
    os.unlink(path)


def test_render_rejects_malformed_management_defaults():
    needle = (
        '  management:\n'
        '    root_password_hash: ""\n'
        '    ssh_authorized_keys:\n'
        '      - "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKm8abcdefgh"'
    )
    config = VALID_CONFIG.replace(
        needle,
        "  management: not-a-mapping",
    )
    path = _write_config(config)
    with pytest.raises(ManifestError, match="defaults.management must be a mapping"):
        load_manifest(path)
    os.unlink(path)


def test_render_rejects_malformed_mesh_object():
    class BadManifest:
        mesh = "not-a-mapping"
        defaults = {}
        nodes = {"node01": {}}

        def get_node(self, name):
            return self.nodes[name]

    with pytest.raises(ManifestError, match="'mesh' must be a mapping"):
        render(BadManifest(), "node01")
