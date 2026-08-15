"""Disk image payload validation helpers."""

from __future__ import annotations

from pathlib import Path
import zlib

_GZIP_MAGIC = b"\x1f\x8b"
_READ_BYTES = 1024 * 1024


def gzip_decompressed_bytes(image_path: Path) -> int:
    total = 0
    with image_path.open("rb") as f:
        pending = f.read(_READ_BYTES)
        if not pending.startswith(_GZIP_MAGIC):
            raise zlib.error("compressed image does not start with a gzip member")
        while pending.startswith(_GZIP_MAGIC):
            decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
            while not decompressor.eof:
                if not pending:
                    pending = f.read(_READ_BYTES)
                    if not pending:
                        raise zlib.error(
                            "compressed image ended before the gzip stream completed"
                        )
                total += len(decompressor.decompress(pending))
                pending = decompressor.unused_data

            if not pending:
                pending = f.read(_READ_BYTES)
            if pending == _GZIP_MAGIC[:1]:
                pending += f.read(_READ_BYTES)
                if pending == _GZIP_MAGIC[:1]:
                    raise zlib.error(
                        "compressed image ended during the next gzip member header"
                    )
    return total


def check_gzip_payload(image_path: Path) -> int:
    total = gzip_decompressed_bytes(image_path)
    if total == 0:
        raise zlib.error("compressed image did not contain a disk image payload")
    return total
