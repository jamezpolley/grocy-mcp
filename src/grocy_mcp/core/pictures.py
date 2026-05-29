"""Product picture upload helpers for Grocy."""

from __future__ import annotations

import base64
import os
import time
from pathlib import Path

from grocy_mcp.client import GrocyClient


def _encode_filename(file_name: str) -> str:
    """Base64-encode a filename for use in Grocy's /files/{group}/{filename_b64} path."""
    return base64.b64encode(file_name.encode("utf-8")).decode("ascii")


def _build_picture_filename(product_id: int, source_path: str, override: str | None) -> str:
    """Return the picture filename to store in Grocy (plain, before b64 encoding)."""
    if override:
        return override
    ext = Path(source_path).suffix.lower() or ".jpg"
    epoch = int(time.time())
    return f"product-{product_id}-{epoch}{ext}"


async def stock_product_picture_upload(
    client: GrocyClient,
    product_id: int,
    image_path: str,
    filename: str | None = None,
) -> dict:
    """Upload a product picture and link it to the product.

    Reads the image from *image_path*, uploads it to Grocy's
    ``productpictures`` file group, then PATCHes the product's
    ``picture_file_name`` field so the UI shows the image.

    Args:
        client: Authenticated GrocyClient.
        product_id: Grocy product ID.
        image_path: Absolute or relative path to a PNG or JPG file on disk.
        filename: Override the auto-generated filename (default:
            ``product-{id}-{epoch}.{ext}``).

    Returns:
        dict with ``product_id``, ``picture_file_name``,
        ``upload_status``, and ``link_status``.
    """
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")

    image_bytes = path.read_bytes()
    picture_filename = _build_picture_filename(product_id, image_path, filename)
    filename_b64 = _encode_filename(picture_filename)

    # 1. PUT /files/productpictures/{filename_b64}
    await client.upload_file("productpictures", filename_b64, image_bytes)

    # 2. PATCH /objects/products/{id}  (PUT semantics — only send changed field)
    await client.update_object("products", product_id, {"picture_file_name": picture_filename})

    return {
        "product_id": product_id,
        "picture_file_name": picture_filename,
        "upload_status": "ok",
        "link_status": "ok",
    }
