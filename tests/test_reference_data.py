"""Tests for first-class metadata and discovery helpers."""

from unittest.mock import AsyncMock

import pytest

from grocy_mcp.core.reference_data import (
    describe_entity_data,
    entity_get_data,
    entity_query_data,
    list_entity_records,
    list_entity_view,
    search_entity_candidates_data,
)
from grocy_mcp.exceptions import GrocyValidationError


async def test_list_entity_view_for_shopping_locations():
    client = AsyncMock()
    client.get_objects.return_value = [
        {"id": 1, "name": "Market", "description": "Weekly shop"},
        {"id": 2, "name": "Pharmacy", "description": ""},
    ]

    result = await list_entity_view(client, "shopping_locations")

    assert "Shopping locations" in result
    assert "[1] Market" in result
    assert "description=Weekly shop" in result


async def test_list_entity_records_applies_query_filter():
    client = AsyncMock()
    client.get_objects.return_value = [
        {"id": 1, "name": "Pantry"},
        {"id": 2, "name": "Freezer"},
    ]

    result = await list_entity_records(client, "shopping_lists", "pan")

    assert result == [{"id": 1, "name": "Pantry"}]


async def test_search_entity_candidates_data_for_products():
    client = AsyncMock()
    client.get_objects.return_value = [
        {"id": 1, "name": "Whole Milk", "description": "Organic"},
        {"id": 2, "name": "Bread", "description": "Sourdough"},
    ]

    result = await search_entity_candidates_data(client, "products", "milk")

    assert result == [{"id": 1, "label": "Whole Milk", "summary": ["description=Organic"]}]


async def test_describe_entity_data_marks_read_only_views():
    client = AsyncMock()
    client.get_objects.return_value = [{"id": 1, "product_id": 3, "avg_price": 1.29}]

    result = await describe_entity_data(client, "products_average_price")

    assert result["supports_create"] is False
    assert result["supports_update"] is False
    assert result["supports_delete"] is False
    assert "avg_price" in result["sample_fields"]


async def test_entity_get_data_returns_full_object():
    client = AsyncMock()
    full = {
        "id": 7,
        "name": "Milk",
        "min_stock_amount": 2,
        "default_consume_location_id": 3,
        "description": "Full cream",
        "picture_file_name": "milk.jpg",
    }
    client.get_object.return_value = full

    result = await entity_get_data(client, "products", 7)

    assert result == full
    client.get_object.assert_awaited_once_with("products", 7)


async def test_entity_get_data_rejects_unknown_entity():
    client = AsyncMock()
    with pytest.raises(GrocyValidationError):
        await entity_get_data(client, "not_a_real_entity", 1)


async def test_entity_query_data_builds_query_and_returns_rows():
    client = AsyncMock()
    rows = [
        {"id": 1, "name": "Milk", "shopping_location_id": 1},
        {"id": 2, "name": "Bread", "shopping_location_id": 1},
    ]
    client.get_objects.return_value = rows

    result = await entity_query_data(client, "products", {"shopping_location_id": 1})

    assert result == rows
    client.get_objects.assert_awaited_once_with(
        "products", query=["shopping_location_id=1"]
    )


async def test_entity_query_data_ands_multiple_filters():
    client = AsyncMock()
    client.get_objects.return_value = []

    await entity_query_data(
        client, "products", {"shopping_location_id": 1, "active": True}
    )

    client.get_objects.assert_awaited_once_with(
        "products", query=["shopping_location_id=1", "active=1"]
    )


async def test_entity_query_data_none_filter_renders_empty():
    client = AsyncMock()
    client.get_objects.return_value = []

    await entity_query_data(client, "products", {"parent_product_id": None})

    client.get_objects.assert_awaited_once_with("products", query=["parent_product_id="])


async def test_entity_query_data_projects_fields():
    client = AsyncMock()
    client.get_objects.return_value = [
        {"id": 1, "name": "Milk", "min_stock_amount": 2, "extra": "drop me"},
    ]

    result = await entity_query_data(
        client, "products", fields=["id", "name", "missing_field"]
    )

    assert result == [{"id": 1, "name": "Milk"}]


async def test_entity_query_data_no_filters_returns_all():
    client = AsyncMock()
    rows = [{"id": 1}, {"id": 2}]
    client.get_objects.return_value = rows

    result = await entity_query_data(client, "products")

    assert result == rows
    client.get_objects.assert_awaited_once_with("products", query=None)


async def test_entity_query_data_rejects_unknown_entity():
    client = AsyncMock()
    with pytest.raises(GrocyValidationError):
        await entity_query_data(client, "not_a_real_entity")
