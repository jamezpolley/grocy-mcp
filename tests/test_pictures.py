"""Tests for product picture upload helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from grocy_mcp.core.pictures import (
    _build_picture_filename,
    _encode_filename,
    stock_product_picture_upload,
)


# --- unit helpers ---


def test_encode_filename_roundtrip():
    import base64

    name = "product-42-1234567890.jpg"
    encoded = _encode_filename(name)
    assert base64.b64decode(encoded.encode("ascii")).decode("utf-8") == name


def test_build_picture_filename_override():
    result = _build_picture_filename(7, "/tmp/foo.png", "custom.png")
    assert result == "custom.png"


def test_build_picture_filename_auto_ext():
    result = _build_picture_filename(7, "/tmp/photo.png", None)
    assert result.startswith("product-7-")
    assert result.endswith(".png")


def test_build_picture_filename_auto_jpg():
    result = _build_picture_filename(7, "/tmp/photo.jpg", None)
    assert result.endswith(".jpg")


def test_build_picture_filename_no_ext_defaults_jpg():
    result = _build_picture_filename(7, "/tmp/noext", None)
    assert result.endswith(".jpg")


# --- integration-style (mock client + real file I/O) ---


@pytest.mark.asyncio
async def test_upload_success(tmp_path):
    image = tmp_path / "product-1.jpg"
    image.write_bytes(b"\xff\xd8\xff" + b"\x00" * 10)  # minimal JPEG-like bytes

    client = AsyncMock()
    client.upload_file = AsyncMock()
    client.update_object = AsyncMock()

    result = await stock_product_picture_upload(
        client, product_id=42, image_path=str(image), filename="my-pic.jpg"
    )

    assert result["product_id"] == 42
    assert result["picture_file_name"] == "my-pic.jpg"
    assert result["upload_status"] == "ok"
    assert result["link_status"] == "ok"

    client.upload_file.assert_awaited_once()
    call_args = client.upload_file.call_args
    assert call_args.args[0] == "productpictures"
    # second arg is the b64-encoded filename
    import base64

    assert base64.b64decode(call_args.args[1]).decode() == "my-pic.jpg"
    assert call_args.args[2] == image.read_bytes()

    client.update_object.assert_awaited_once_with(
        "products", 42, {"picture_file_name": "my-pic.jpg"}
    )


@pytest.mark.asyncio
async def test_upload_file_not_found():
    client = AsyncMock()
    with pytest.raises(FileNotFoundError):
        await stock_product_picture_upload(client, 1, "/nonexistent/path/image.jpg")


@pytest.mark.asyncio
async def test_upload_auto_filename(tmp_path):
    image = tmp_path / "photo.png"
    image.write_bytes(b"\x89PNG\r\n")

    client = AsyncMock()
    client.upload_file = AsyncMock()
    client.update_object = AsyncMock()

    result = await stock_product_picture_upload(client, product_id=5, image_path=str(image))

    fname = result["picture_file_name"]
    assert fname.startswith("product-5-")
    assert fname.endswith(".png")
