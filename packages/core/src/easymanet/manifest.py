"""Strict parser for the documented ``fleet.yml`` manifest contract."""

from pathlib import Path
import unicodedata
from typing import (
    Any,
    List,
    TypedDict,
    cast,
    get_args,
    get_origin,
    get_type_hints,
    is_typeddict,
)

import yaml


class ManifestError(Exception):
    pass


class LocalApManifest(TypedDict, total=False):
    enabled: bool
    ssid: str
    password: str


class GatewayWifiManifest(TypedDict, total=False):
    enabled: bool
    ssid: str
    password: str
    encryption: str


class GatewayManifest(TypedDict, total=False):
    enabled: bool
    uplink_interface: str
    wifi: GatewayWifiManifest


class ManagementManifest(TypedDict, total=False):
    root_password_hash: str
    ssh_authorized_keys: list[str]


class MeshManifest(TypedDict, total=False):
    id: str
    password: str
    channel: int
    bandwidth_mhz: int
    country: str


class DefaultsManifest(TypedDict, total=False):
    target: str
    role: str
    local_ap: LocalApManifest
    gateway: GatewayManifest
    management: ManagementManifest


class NodeManifest(TypedDict, total=False):
    role: str
    hostname: str
    ip: str
    target: str
    local_ap: LocalApManifest
    gateway: GatewayManifest


class ManifestData(TypedDict, total=False):
    version: int
    mesh: MeshManifest
    defaults: DefaultsManifest
    nodes: dict[str, NodeManifest]


class Manifest:
    def __init__(self, path: str):
        self.path = Path(path)
        self.data: ManifestData = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            raise ManifestError(f"Config file not found: {self.path}")
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f)
        except OSError as e:
            raise ManifestError(f"Could not read config file {self.path}: {e}") from e
        except yaml.YAMLError as e:
            raise ManifestError(f"Invalid YAML in {self.path}: {e}") from e
        self.data = self._validate_structure(raw)

    def _validate_structure(self, raw: Any) -> ManifestData:
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise ManifestError(
                f"Manifest root must be a mapping, got {type(raw).__name__}"
            )
        for section in ("mesh", "defaults", "nodes"):
            value = raw.get(section)
            if value is not None and not isinstance(value, dict):
                raise ManifestError(
                    f"Manifest section '{section}' must be a mapping, "
                    f"got {type(value).__name__}"
                )
        nodes = raw.get("nodes", {})
        if isinstance(nodes, dict):
            for name, node in nodes.items():
                if not isinstance(node, dict):
                    raise ManifestError(
                        f"Manifest node '{name}' must be a mapping, "
                        f"got {type(node).__name__}"
                    )
        errors = _contract_errors(raw)
        if errors:
            details = "\n".join(f"  - {error}" for error in errors)
            raise ManifestError(f"Invalid manifest contract:\n{details}")
        return cast(ManifestData, raw)

    @property
    def version(self) -> int:
        return self.data.get("version", 0)

    @property
    def mesh(self) -> MeshManifest:
        return self.data.get("mesh", {})

    @property
    def defaults(self) -> DefaultsManifest:
        return self.data.get("defaults", {})

    @property
    def nodes(self) -> dict[str, NodeManifest]:
        return self.data.get("nodes", {})

    def get_node(self, name: str) -> NodeManifest:
        if name not in self.nodes:
            raise ManifestError(f"Node '{name}' not found in manifest")
        return self.nodes[name]

    def get_default(self, key: str, default: Any = None) -> Any:
        return self.defaults.get(key, default)

    def get_mesh(self, key: str, default: Any = None) -> Any:
        return self.mesh.get(key, default)

    def node_names(self) -> List[str]:
        return list(self.nodes.keys())


def load_manifest(path: str) -> Manifest:
    return Manifest(path)


def _contract_errors(raw: dict[object, object]) -> list[str]:
    errors: list[str] = []
    _check_contract_value(raw, ManifestData, "manifest", errors)
    return errors


def _check_contract_value(
    value: object,
    expected_type: object,
    path: str,
    errors: list[str],
) -> None:
    if is_typeddict(expected_type):
        _check_typed_mapping(value, expected_type, path, errors)
        return
    origin = get_origin(expected_type)
    if origin is dict:
        _check_typed_dict(value, expected_type, path, errors)
        return
    if origin is list:
        _check_typed_list(value, expected_type, path, errors)
        return
    if expected_type is str:
        if not isinstance(value, str):
            errors.append(f"{path} must be a string, got {type(value).__name__}")
            return
        if any(
            unicodedata.category(character) in {"Cc", "Zl", "Zp"}
            for character in value
        ):
            errors.append(
                f"{path} must not contain control or line-separator characters"
            )
        return
    if expected_type is bool and type(value) is not bool:
        errors.append(f"{path} must be a boolean, got {type(value).__name__}")
        return
    if expected_type is int and type(value) is not int:
        errors.append(f"{path} must be an integer, got {type(value).__name__}")


def _check_typed_mapping(
    value: object,
    expected_type: object,
    path: str,
    errors: list[str],
) -> None:
    if not isinstance(value, dict):
        errors.append(f"{path} must be a mapping, got {type(value).__name__}")
        return
    fields = get_type_hints(expected_type)
    for field_name in value:
        if field_name not in fields:
            errors.append(f"{path} contains unsupported field {field_name!r}")
    for field_name, field_type in fields.items():
        if field_name in value:
            field_path = field_name if path == "manifest" else f"{path}.{field_name}"
            _check_contract_value(value[field_name], field_type, field_path, errors)


def _check_typed_dict(
    value: object,
    expected_type: object,
    path: str,
    errors: list[str],
) -> None:
    if not isinstance(value, dict):
        errors.append(f"{path} must be a mapping, got {type(value).__name__}")
        return
    key_type, item_type = get_args(expected_type)
    for key, item in value.items():
        if key_type is str and not isinstance(key, str):
            errors.append(f"{path} keys must be strings, got {type(key).__name__}")
            continue
        if isinstance(key, str):
            _check_contract_value(key, str, f"{path} key {key!r}", errors)
        _check_contract_value(item, item_type, f"{path}.{key}", errors)


def _check_typed_list(
    value: object,
    expected_type: object,
    path: str,
    errors: list[str],
) -> None:
    if not isinstance(value, list):
        errors.append(f"{path} must be a list, got {type(value).__name__}")
        return
    (item_type,) = get_args(expected_type)
    for index, item in enumerate(value):
        _check_contract_value(item, item_type, f"{path}[{index}]", errors)
