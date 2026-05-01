"""YAML fleet manifest parser.

Parses fleet.yml, validates basic structure, and provides access
to mesh settings, defaults, and node definitions.
"""

from pathlib import Path
from typing import Any, Dict, List

import yaml


class ManifestError(Exception):
    pass


class Manifest:
    def __init__(self, path: str):
        self.path = Path(path)
        self.data: Dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            raise ManifestError(f"Config file not found: {self.path}")
        try:
            with open(self.path, "r") as f:
                self.data = yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            raise ManifestError(f"Invalid YAML in {self.path}: {e}")

    @property
    def version(self) -> int:
        return self.data.get("version", 0)

    @property
    def mesh(self) -> Dict[str, Any]:
        return self.data.get("mesh", {})

    @property
    def defaults(self) -> Dict[str, Any]:
        return self.data.get("defaults", {})

    @property
    def nodes(self) -> Dict[str, Any]:
        return self.data.get("nodes", {})

    def get_node(self, name: str) -> Dict[str, Any]:
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
