"""Compatibility shim for image command registration.

The Typer command surface is owned by :mod:`easymanet_cli.image`. Keep this
module importable for older internal callers that still import
``easymanet_image.cli.register_image_commands``.
"""

from easymanet_cli.image import register_image_commands

__all__ = ["register_image_commands"]
