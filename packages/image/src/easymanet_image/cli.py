"""Compatibility shim for image command registration.

The Typer command surface is owned by :mod:`easymanet_cli.image`. Keep this
module importable for older internal callers that still import
``easymanet_image.cli.register_image_commands``.
"""

from easymanet.download import get_cached_image, get_image_config
from easymanet_cli.common import maybe_show_update_notice
from easymanet_cli.image import register_image_commands
from easymanet_image.build import build_image

__all__ = [
    "register_image_commands",
    "maybe_show_update_notice",
    "get_image_config",
    "get_cached_image",
    "build_image",
]
