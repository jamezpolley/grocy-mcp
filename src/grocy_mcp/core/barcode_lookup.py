"""External barcode / product-database lookup helpers."""

from __future__ import annotations

import httpx

_OFF_URL = "https://world.openfoodfacts.org/api/v2/product/{barcode}.json"
_UPC_URL = "https://api.upcitemdb.com/prod/trial/lookup"


def _parse_off(data: dict) -> dict:
    """Normalise an OpenFoodFacts product payload."""
    product = data.get("product") or {}

    # categories_tags is a list like ["en:beverages", "en:juices"]
    raw_cats = product.get("categories_tags") or []
    categories = [c.split(":", 1)[-1].replace("-", " ") for c in raw_cats if ":" in c]

    nutriments = product.get("nutriments") or {}
    nutriments_summary = {
        k: nutriments[k]
        for k in ("energy-kcal_100g", "fat_100g", "sugars_100g", "proteins_100g", "salt_100g")
        if k in nutriments
    }

    return {
        "name": product.get("product_name_en") or product.get("product_name") or None,
        "brand": product.get("brands") or None,
        "quantity_text": product.get("quantity") or None,
        "categories": categories,
        "image_url": product.get("image_url") or None,
        "nutriments": nutriments_summary,
    }


def _parse_upc(data: dict) -> dict:
    """Normalise a UPCItemDB product payload."""
    items = data.get("items") or []
    item = items[0] if items else {}
    images = item.get("images") or []
    return {
        "name": item.get("title") or None,
        "brand": item.get("brand") or None,
        "quantity_text": None,
        "categories": [item["category"]] if item.get("category") else [],
        "image_url": images[0] if images else None,
        "nutriments": {},
    }


async def barcode_lookup_external(
    barcode: str,
    source: str = "openfoodfacts",
) -> dict:
    """Query an external product database by barcode.

    Supported sources:
    - ``openfoodfacts`` (default) — free, no key, best for grocery products.
    - ``upcitemdb`` — trial tier (100 req/day), no key, broader non-food coverage.

    Returns a normalised dict regardless of source.  The caller decides whether
    to act on the data — nothing is written to Grocy.

    Args:
        barcode: UPC / EAN / GTIN string.
        source: ``"openfoodfacts"`` or ``"upcitemdb"``.

    Returns:
        ``{found, source, barcode, name, brand, quantity_text, categories,
        image_url, nutriments, raw}``
    """
    source = source.lower()
    if source not in ("openfoodfacts", "upcitemdb"):
        raise ValueError(f"Unknown source '{source}'. Use 'openfoodfacts' or 'upcitemdb'.")

    async with httpx.AsyncClient(timeout=10.0) as http:
        if source == "openfoodfacts":
            url = _OFF_URL.format(barcode=barcode)
            resp = await http.get(url)
            resp.raise_for_status()
            data = resp.json()
            found = data.get("status") == 1
            normalised = _parse_off(data) if found else {}
            raw = data
        else:
            resp = await http.get(_UPC_URL, params={"upc": barcode})
            resp.raise_for_status()
            data = resp.json()
            items = data.get("items") or []
            found = bool(items)
            normalised = _parse_upc(data) if found else {}
            raw = data

    return {
        "found": found,
        "source": source,
        "barcode": barcode,
        "name": normalised.get("name"),
        "brand": normalised.get("brand"),
        "quantity_text": normalised.get("quantity_text"),
        "categories": normalised.get("categories", []),
        "image_url": normalised.get("image_url"),
        "nutriments": normalised.get("nutriments", {}),
        "raw": raw,
    }
