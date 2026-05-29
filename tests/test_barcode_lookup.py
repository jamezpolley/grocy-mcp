"""Tests for external barcode lookup helpers."""

from __future__ import annotations

import json
import pytest
import httpx
import respx

from grocy_mcp.core.barcode_lookup import barcode_lookup_external


_OFF_BASE = "https://world.openfoodfacts.org"
_UPC_BASE = "https://api.upcitemdb.com"


# --- OpenFoodFacts ---

_OFF_HIT = {
    "status": 1,
    "product": {
        "product_name": "Oat Milk",
        "product_name_en": "Oat Milk",
        "brands": "Oatly",
        "quantity": "1L",
        "categories_tags": ["en:beverages", "en:plant-based-milks"],
        "image_url": "https://images.openfoodfacts.org/oat-milk.jpg",
        "nutriments": {
            "energy-kcal_100g": 47,
            "fat_100g": 1.5,
            "sugars_100g": 4.0,
            "proteins_100g": 1.0,
            "salt_100g": 0.1,
        },
    },
}

_OFF_MISS = {"status": 0, "product": None}


@pytest.mark.asyncio
async def test_off_found():
    with respx.mock(base_url=_OFF_BASE) as mock:
        mock.get("/api/v2/product/1234567890123.json").mock(
            return_value=httpx.Response(200, json=_OFF_HIT)
        )
        result = await barcode_lookup_external("1234567890123", source="openfoodfacts")

    assert result["found"] is True
    assert result["source"] == "openfoodfacts"
    assert result["barcode"] == "1234567890123"
    assert result["name"] == "Oat Milk"
    assert result["brand"] == "Oatly"
    assert result["quantity_text"] == "1L"
    assert "beverages" in result["categories"]
    assert result["image_url"] == "https://images.openfoodfacts.org/oat-milk.jpg"
    assert result["nutriments"]["energy-kcal_100g"] == 47
    assert "raw" in result


@pytest.mark.asyncio
async def test_off_not_found():
    with respx.mock(base_url=_OFF_BASE) as mock:
        mock.get("/api/v2/product/0000000000000.json").mock(
            return_value=httpx.Response(200, json=_OFF_MISS)
        )
        result = await barcode_lookup_external("0000000000000", source="openfoodfacts")

    assert result["found"] is False
    assert result["name"] is None
    assert result["categories"] == []


# --- UPCItemDB ---

_UPC_HIT = {
    "code": "OK",
    "total": 1,
    "offset": 0,
    "items": [
        {
            "ean": "9780201379624",
            "title": "Widget Pro 3000",
            "upc": "9780201379624",
            "brand": "Widgetco",
            "category": "Electronics",
            "images": ["https://cdn.upcitemdb.com/widget.jpg"],
        }
    ],
}

_UPC_MISS = {"code": "OK", "total": 0, "offset": 0, "items": []}


@pytest.mark.asyncio
async def test_upc_found():
    with respx.mock(base_url=_UPC_BASE) as mock:
        mock.get("/prod/trial/lookup").mock(
            return_value=httpx.Response(200, json=_UPC_HIT)
        )
        result = await barcode_lookup_external("9780201379624", source="upcitemdb")

    assert result["found"] is True
    assert result["source"] == "upcitemdb"
    assert result["name"] == "Widget Pro 3000"
    assert result["brand"] == "Widgetco"
    assert result["categories"] == ["Electronics"]
    assert result["image_url"] == "https://cdn.upcitemdb.com/widget.jpg"
    assert result["nutriments"] == {}


@pytest.mark.asyncio
async def test_upc_not_found():
    with respx.mock(base_url=_UPC_BASE) as mock:
        mock.get("/prod/trial/lookup").mock(
            return_value=httpx.Response(200, json=_UPC_MISS)
        )
        result = await barcode_lookup_external("0000000000000", source="upcitemdb")

    assert result["found"] is False
    assert result["name"] is None


# --- default source ---

@pytest.mark.asyncio
async def test_default_source_is_openfoodfacts():
    with respx.mock(base_url=_OFF_BASE) as mock:
        mock.get("/api/v2/product/111.json").mock(
            return_value=httpx.Response(200, json=_OFF_MISS)
        )
        result = await barcode_lookup_external("111")

    assert result["source"] == "openfoodfacts"


# --- invalid source ---

@pytest.mark.asyncio
async def test_invalid_source_raises():
    with pytest.raises(ValueError, match="Unknown source"):
        await barcode_lookup_external("123", source="baddb")
