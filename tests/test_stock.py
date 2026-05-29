"""Tests for the stock core module."""

from unittest.mock import AsyncMock, patch

import pytest

from grocy_mcp.core.stock import (
    product_family_data,
    stock_add,
    stock_barcode_lookup,
    stock_consume,
    stock_expiring,
    stock_inventory,
    stock_open,
    stock_overview,
    stock_product_full_data,
    stock_product_info,
    stock_search,
    stock_transfer,
)


@pytest.fixture
def mock_client():
    client = AsyncMock()
    client.get_stock.return_value = [
        {"product_id": 1, "amount": 3, "product": {"id": 1, "name": "Milk", "location_id": 1}}
    ]
    client.get_volatile_stock.return_value = {
        "expiring_products": [{"product_id": 1, "amount": 3, "product": {"id": 1, "name": "Milk"}}],
        "expired_products": [],
        "missing_products": [],
    }
    client.get_objects.return_value = [
        {"id": 1, "name": "Milk"},
        {"id": 2, "name": "Bread"},
    ]
    client.add_stock.return_value = [{"id": 10}]
    client.consume_stock.return_value = [{"id": 10}]
    return client


async def test_stock_overview(mock_client):
    result = await stock_overview(mock_client)
    assert "Milk" in result
    assert "3" in result


async def test_stock_expiring(mock_client):
    result = await stock_expiring(mock_client)
    assert "Milk" in result


async def test_stock_add(mock_client):
    with patch("grocy_mcp.core.stock.resolve_product", return_value=1) as mock_resolve:
        result = await stock_add(mock_client, "Milk", 2.0)
        mock_resolve.assert_called_once_with(mock_client, "Milk")
        mock_client.add_stock.assert_called_once_with(1, 2.0)
        assert "added" in result.lower() or "milk" in result.lower()


async def test_stock_add_with_location(mock_client):
    """Passing a location resolves it and forwards location_id to the client."""
    with (
        patch("grocy_mcp.core.stock.resolve_product", return_value=100),
        patch("grocy_mcp.core.stock.resolve_location", return_value=3) as mock_loc,
    ):
        result = await stock_add(mock_client, "Bolognese Mince", 0.5, "Freezer")
        mock_loc.assert_called_once_with(mock_client, "Freezer")
        mock_client.add_stock.assert_called_once_with(100, 0.5, location_id=3)
        assert "Freezer" in result


async def test_stock_consume(mock_client):
    with patch("grocy_mcp.core.stock.resolve_product", return_value=1):
        result = await stock_consume(mock_client, "Milk", 1.0)
        mock_client.consume_stock.assert_called_once_with(1, 1.0)
        assert result


async def test_stock_search(mock_client):
    result = await stock_search(mock_client, "Milk")
    assert "Milk" in result


async def test_stock_product_info(mock_client):
    mock_client.get_stock_product.return_value = {
        "product": {"id": 1, "name": "Milk"},
        "stock_amount": 3,
        "next_best_before_date": "2026-04-01",
    }
    with patch("grocy_mcp.core.stock.resolve_product", return_value=1):
        result = await stock_product_info(mock_client, "Milk")
        mock_client.get_stock_product.assert_called_once_with(1)
        assert "Milk" in result


async def test_stock_transfer(mock_client):
    mock_client.transfer_stock.return_value = [{"id": 10}]
    with (
        patch("grocy_mcp.core.stock.resolve_product", return_value=1),
        patch("grocy_mcp.core.stock.resolve_location", return_value=2),
    ):
        result = await stock_transfer(mock_client, "Milk", 1.0, "Fridge", "Pantry")
        # to_location resolved first, then from_location; both map to 2 here.
        mock_client.transfer_stock.assert_called_once_with(1, 1.0, 2, 2)
        assert result


async def test_stock_transfer_distinct_locations(mock_client):
    """Source and destination resolve independently and reach the client in order."""
    mock_client.transfer_stock.return_value = [{"id": 10}]
    with (
        patch("grocy_mcp.core.stock.resolve_product", return_value=100),
        patch(
            "grocy_mcp.core.stock.resolve_location",
            side_effect=lambda _client, name: {"Freezer": 3, "Pantry": 1}[name],
        ),
    ):
        result = await stock_transfer(mock_client, "Bolognese Mince", 0.5, "Freezer", "Pantry")
        # Signature is transfer_stock(product_id, amount, to_location_id, from_location_id).
        mock_client.transfer_stock.assert_called_once_with(100, 0.5, 3, 1)
        assert "Freezer" in result
        assert "Pantry" in result


async def test_stock_inventory(mock_client):
    mock_client.inventory_stock.return_value = [{"id": 10}]
    with patch("grocy_mcp.core.stock.resolve_product", return_value=1):
        result = await stock_inventory(mock_client, "Milk", 5.0)
        mock_client.inventory_stock.assert_called_once_with(1, 5.0)
        assert result


async def test_stock_open(mock_client):
    mock_client.open_stock.return_value = [{"id": 10}]
    with patch("grocy_mcp.core.stock.resolve_product", return_value=1):
        result = await stock_open(mock_client, "Milk", 1.0)
        mock_client.open_stock.assert_called_once_with(1, 1.0)
        assert result


async def test_stock_barcode_lookup(mock_client):
    mock_client.get_stock_by_barcode.return_value = {
        "product": {"id": 1, "name": "Milk"},
        "stock_amount": 3,
    }
    result = await stock_barcode_lookup(mock_client, "1234567890")
    mock_client.get_stock_by_barcode.assert_called_once_with("1234567890")
    assert "Milk" in result


async def test_stock_overview_empty(mock_client):
    mock_client.get_stock.return_value = []
    result = await stock_overview(mock_client)
    assert result == "No stock found."


async def test_stock_overview_format(mock_client):
    result = await stock_overview(mock_client)
    assert "Current stock:" in result
    assert "[1] Milk" in result


async def test_stock_expiring_empty(mock_client):
    mock_client.get_volatile_stock.return_value = {
        "expiring_products": [],
        "expired_products": [],
        "missing_products": [],
    }
    result = await stock_expiring(mock_client)
    assert "No expiring, expired, or missing products found." in result


async def test_stock_add_quotes_name(mock_client):
    with patch("grocy_mcp.core.stock.resolve_product", return_value=1):
        result = await stock_add(mock_client, "Milk", 2.0)
        assert "'Milk'" in result


async def test_stock_consume_quotes_name(mock_client):
    with patch("grocy_mcp.core.stock.resolve_product", return_value=1):
        result = await stock_consume(mock_client, "Milk", 1.0)
        assert "'Milk'" in result


async def test_stock_transfer_quotes_names(mock_client):
    mock_client.transfer_stock.return_value = [{"id": 10}]
    with (
        patch("grocy_mcp.core.stock.resolve_product", return_value=1),
        patch("grocy_mcp.core.stock.resolve_location", return_value=2),
    ):
        result = await stock_transfer(mock_client, "Eggs", 3.0, "Fridge", "Pantry")
        assert "'Eggs'" in result
        assert "'Fridge'" in result


async def test_stock_inventory_quotes_name(mock_client):
    mock_client.inventory_stock.return_value = [{"id": 10}]
    with patch("grocy_mcp.core.stock.resolve_product", return_value=1):
        result = await stock_inventory(mock_client, "Milk", 5.0)
        assert "'Milk'" in result


async def test_stock_open_quotes_name(mock_client):
    mock_client.open_stock.return_value = [{"id": 10}]
    with patch("grocy_mcp.core.stock.resolve_product", return_value=1):
        result = await stock_open(mock_client, "Milk", 1.0)
        assert "'Milk'" in result


async def test_stock_search_uses_bracket_ids(mock_client):
    mock_client.get_objects.side_effect = [
        [{"id": 1, "name": "Milk"}, {"id": 2, "name": "Bread"}],
        [],
    ]
    result = await stock_search(mock_client, "Milk")
    assert "[1] Milk" in result


async def test_stock_search_no_results(mock_client):
    mock_client.get_objects.side_effect = [
        [{"id": 1, "name": "Milk"}],
        [],
    ]
    result = await stock_search(mock_client, "Cheese")
    assert "No products found matching 'Cheese'." in result


# ── stock_product_full_data tests ──────────────────────────────────────────────

_STOCK_PRODUCT_8_RESPONSE = {
    "product": {
        "id": 8,
        "name": "Thickened Cream",
        "product_group_id": 2,
        "location_id": 2,
        "shopping_location_id": None,
        "parent_product_id": None,
        "qu_id_purchase": 8,
        "qu_id_stock": 8,
        "qu_id_consume": 8,
        "qu_id_price": 8,
    },
    "product_barcodes": [
        {
            "id": 1,
            "product_id": 8,
            "barcode": "93601023",
            "qu_id": 8,
            "amount": 0.6,
            "shopping_location_id": 1,
            "last_price": 5.2,
            "note": "Coles Thickened Cream 600mL",
        }
    ],
    "stock_amount": 1.2,
    "stock_value": 10.4,
    "stock_amount_opened": 0.6,
    "stock_amount_aggregated": 1.2,
    "stock_amount_opened_aggregated": 0.6,
    "last_purchased": "2026-01-13",
    "last_used": "2026-05-23",
    "last_price": 5.2,
    "avg_price": 5.2,
    "next_due_date": "2026-06-01",
    "last_shopping_location_id": 1,
    "default_shopping_location_id": None,
    "quantity_unit_stock": {"id": 8, "name": "litre", "name_plural": "litres"},
    "default_quantity_unit_purchase": {"id": 8, "name": "litre", "name_plural": "litres"},
    "default_quantity_unit_consume": {"id": 8, "name": "litre", "name_plural": "litres"},
    "quantity_unit_price": {"id": 8, "name": "litre", "name_plural": "litres"},
    "location": {"id": 2, "name": "Fridge"},
}


@pytest.fixture
def full_mock_client():
    """Mock client pre-loaded for stock_product_full_data happy path."""
    client = AsyncMock()
    client.get_stock_product.return_value = _STOCK_PRODUCT_8_RESPONSE
    # QU conversions: one product-specific conversion
    client.get_objects.return_value = [
        {"id": 10, "product_id": 8, "from_qu_id": 8, "to_qu_id": 4, "factor": 1000.0},
    ]
    # product_group lookup
    client.get_object.side_effect = lambda entity, obj_id: {
        ("product_groups", 2): {"id": 2, "name": "Dairy"},
        ("shopping_locations", 1): {"id": 1, "name": "Coles Local"},
    }.get((entity, obj_id), {})
    return client


async def test_stock_product_full_data_happy_path(full_mock_client):
    """Full data aggregation returns the expected structure."""
    with patch("grocy_mcp.core.stock.resolve_product", return_value=8):
        result = await stock_product_full_data(full_mock_client, "8")

    # ── product ───────────────────────────────────────────────────────────────
    assert result["product"]["name"] == "Thickened Cream"
    assert result["product"]["id"] == 8

    # ── stock totals ──────────────────────────────────────────────────────────
    assert result["stock"]["amount"] == 1.2
    assert result["stock"]["last_purchased"] == "2026-01-13"
    assert result["stock"]["next_due_date"] == "2026-06-01"

    # ── units ─────────────────────────────────────────────────────────────────
    assert result["units"]["stock"] == {"id": 8, "name": "litre", "name_plural": "litres"}
    assert result["units"]["purchase"]["id"] == 8

    # ── location ─────────────────────────────────────────────────────────────
    assert result["location"] == {"id": 2, "name": "Fridge"}

    # ── shopping_location (product default is null) ───────────────────────────
    assert result["shopping_location"] is None

    # ── product_group resolved ────────────────────────────────────────────────
    assert result["product_group"] == {"id": 2, "name": "Dairy"}

    # ── parent_product (null) ─────────────────────────────────────────────────
    assert result["parent_product"] is None

    # ── barcodes ──────────────────────────────────────────────────────────────
    assert len(result["barcodes"]) == 1
    bc = result["barcodes"][0]
    assert bc["barcode"] == "93601023"
    assert bc["qu"] == {"id": 8, "name": "litre"}
    assert bc["shopping_location"] == {"id": 1, "name": "Coles Local"}
    assert bc["note"] == "Coles Thickened Cream 600mL"

    # ── conversions ───────────────────────────────────────────────────────────
    assert len(result["conversions"]) == 1
    cv = result["conversions"][0]
    assert cv["factor"] == 1000.0
    assert cv["from_qu"]["id"] == 8
    assert cv["to_qu"]["id"] == 4


async def test_stock_product_full_data_no_barcodes_no_conversions(full_mock_client):
    """Products with no barcodes and no product-specific conversions return empty lists."""
    info = dict(_STOCK_PRODUCT_8_RESPONSE)
    info["product"] = dict(_STOCK_PRODUCT_8_RESPONSE["product"])
    info["product_barcodes"] = []
    full_mock_client.get_stock_product.return_value = info
    full_mock_client.get_objects.return_value = []  # no conversions

    with patch("grocy_mcp.core.stock.resolve_product", return_value=8):
        result = await stock_product_full_data(full_mock_client, "8")

    assert result["barcodes"] == []
    assert result["conversions"] == []


async def test_stock_product_full_data_no_group_no_parent(full_mock_client):
    """Null product_group_id and parent_product_id produce null fields, not errors."""
    info = dict(_STOCK_PRODUCT_8_RESPONSE)
    info["product"] = dict(_STOCK_PRODUCT_8_RESPONSE["product"])
    info["product"]["product_group_id"] = None
    info["product"]["parent_product_id"] = None
    full_mock_client.get_stock_product.return_value = info
    full_mock_client.get_objects.return_value = []

    with patch("grocy_mcp.core.stock.resolve_product", return_value=8):
        result = await stock_product_full_data(full_mock_client, "8")

    assert result["product_group"] is None
    assert result["parent_product"] is None
    # get_object should not have been called for groups/parent
    calls = [str(c) for c in full_mock_client.get_object.call_args_list]
    assert not any("product_groups" in c for c in calls)
    assert not any("products" in c for c in calls)


# ── product_family_data tests ───────────────────────────────────────────────────

# Parent "Laundry liquid" (id 125): no own stock, cumulates children's min stock.
_PARENT_125_STOCK = {
    "product": {
        "id": 125,
        "name": "Laundry liquid",
        "parent_product_id": None,
        "no_own_stock": 1,
        "cumulate_min_stock_amount_of_sub_products": 1,
        "min_stock_amount": 0,
        "qu_id_stock": 8,
    },
    "stock_amount": 0,
    "stock_amount_opened": 0,
    "stock_amount_aggregated": 3.12,
    "stock_amount_opened_aggregated": 1.18,
}

# Child "Omo Speed Clean 1.18L" (id 126).
_CHILD_126_STOCK = {
    "product": {
        "id": 126,
        "name": "Omo Speed Clean 1.18L",
        "parent_product_id": 125,
        "no_own_stock": 0,
        "cumulate_min_stock_amount_of_sub_products": 0,
        "min_stock_amount": 1,
        "qu_id_stock": 8,
    },
    "stock_amount": 1.18,
    "stock_amount_opened": 1.18,
    "stock_amount_aggregated": 1.18,
    "stock_amount_opened_aggregated": 1.18,
}

_FAMILY_CHILDREN = [
    {"id": 126, "name": "Omo Speed Clean 1.18L", "parent_product_id": 125,
     "qu_id_stock": 8, "min_stock_amount": 1},
    {"id": 127, "name": "Omo Odor Refresh 1.94L", "parent_product_id": 125,
     "qu_id_stock": 8, "min_stock_amount": 1},
]

_FAMILY_STOCK_SNAPSHOT = [
    {"product_id": 126, "amount": 1.18, "amount_opened": 1.18},
    {"product_id": 127, "amount": 1.94, "amount_opened": 0},
]

_QUANTITY_UNITS = [{"id": 8, "name": "litre", "name_plural": "litres"}]


def _family_client(start_info):
    """Build a mock client for product_family_data starting from start_info."""
    client = AsyncMock()
    # First get_stock_product call is for the queried product; a later call (when
    # starting from a child) fetches the parent.
    client.get_stock_product.side_effect = lambda pid: {
        125: _PARENT_125_STOCK,
        126: _CHILD_126_STOCK,
    }[pid]
    client.get_stock.return_value = _FAMILY_STOCK_SNAPSHOT

    async def get_objects(entity, query=None):
        if entity == "quantity_units":
            return _QUANTITY_UNITS
        if entity == "products" and query == "parent_product_id=125":
            return _FAMILY_CHILDREN
        return []

    client.get_objects.side_effect = get_objects
    return client


async def test_product_family_from_parent():
    """Querying the parent returns root + all children with per-child amounts."""
    client = _family_client(_PARENT_125_STOCK)
    with patch("grocy_mcp.core.stock.resolve_product", return_value=125):
        result = await product_family_data(client, "Laundry liquid")

    assert result["root"]["id"] == 125
    assert result["root"]["is_parent"] is True
    assert result["root"]["no_own_stock"] is True
    assert result["root"]["cumulate_min_stock_amount_of_sub_products"] is True
    assert result["root"]["amount_aggregated"] == 3.12
    assert result["root"]["stock_unit"] == {"id": 8, "name": "litre", "name_plural": "litres"}

    assert result["queried"] == {"id": 125, "name": "Laundry liquid", "was_child": False}

    assert len(result["children"]) == 2
    by_id = {c["id"]: c for c in result["children"]}
    assert by_id[126]["name"] == "Omo Speed Clean 1.18L"
    assert by_id[126]["amount"] == 1.18
    assert by_id[126]["unit"] == {"id": 8, "name": "litre", "name_plural": "litres"}
    assert by_id[127]["amount"] == 1.94


async def test_product_family_from_child_resolves_to_parent():
    """Querying a child resolves up to the parent and returns the whole family."""
    client = _family_client(_CHILD_126_STOCK)
    with patch("grocy_mcp.core.stock.resolve_product", return_value=126):
        result = await product_family_data(client, "Omo Speed Clean 1.18L")

    # Root resolved to the parent, not the child.
    assert result["root"]["id"] == 125
    assert result["root"]["name"] == "Laundry liquid"
    assert result["queried"] == {
        "id": 126, "name": "Omo Speed Clean 1.18L", "was_child": True
    }
    # Family still includes both children.
    assert {c["id"] for c in result["children"]} == {126, 127}


async def test_product_family_child_with_zero_stock_defaults_zero():
    """A child absent from the /stock snapshot reports amount 0, not an error."""
    client = _family_client(_PARENT_125_STOCK)
    client.get_stock.return_value = [
        {"product_id": 126, "amount": 1.18, "amount_opened": 1.18},
    ]  # 127 missing → out of stock
    with patch("grocy_mcp.core.stock.resolve_product", return_value=125):
        result = await product_family_data(client, "125")

    by_id = {c["id"]: c for c in result["children"]}
    assert by_id[127]["amount"] == 0


async def test_product_family_standalone_product_no_children():
    """A product with no parent and no children returns itself as root, empty children."""
    standalone = {
        "product": {
            "id": 50, "name": "Salt", "parent_product_id": None,
            "no_own_stock": 0, "cumulate_min_stock_amount_of_sub_products": 0,
            "min_stock_amount": 0, "qu_id_stock": 8,
        },
        "stock_amount": 2, "stock_amount_opened": 0,
        "stock_amount_aggregated": 2, "stock_amount_opened_aggregated": 0,
    }
    client = AsyncMock()
    client.get_stock_product.return_value = standalone
    client.get_stock.return_value = [{"product_id": 50, "amount": 2, "amount_opened": 0}]

    async def get_objects(entity, query=None):
        if entity == "quantity_units":
            return _QUANTITY_UNITS
        return []  # no children

    client.get_objects.side_effect = get_objects

    with patch("grocy_mcp.core.stock.resolve_product", return_value=50):
        result = await product_family_data(client, "Salt")

    assert result["root"]["id"] == 50
    assert result["root"]["is_parent"] is False
    assert result["children"] == []
    assert result["queried"]["was_child"] is False
