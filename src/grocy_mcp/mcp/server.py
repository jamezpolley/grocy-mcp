"""MCP server exposing Grocy tools via FastMCP."""

from __future__ import annotations

import argparse
import json
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastmcp import FastMCP

from grocy_mcp.client import GrocyClient
from grocy_mcp.config import load_config
from grocy_mcp.exceptions import GrocyValidationError
from grocy_mcp.core.batteries import (
    batteries_due_data,
    batteries_list_data,
    batteries_overdue_data,
    battery_charge,
    battery_create,
    battery_cycle_history_data,
    battery_details_data,
    battery_undo_cycle,
    battery_update,
)
from grocy_mcp.core.calendar import calendar_ical_export, calendar_summary_data
from grocy_mcp.core.chores import (
    chore_create,
    chore_execute,
    chore_undo,
    chores_list,
    chores_overdue,
)
from grocy_mcp.core.equipment import (
    equipment_create,
    equipment_details_data,
    equipment_list_data,
    equipment_update,
)
from grocy_mcp.core.files import (
    file_delete,
    file_download_data,
    file_upload_data,
    print_battery_label,
    print_chore_label,
    print_product_label,
    print_recipe_label,
    print_shopping_list_thermal,
    print_stock_entry_label,
)
from grocy_mcp.core.recipes import (
    recipe_add_ingredient,
    recipe_add_to_shopping,
    recipe_consume,
    recipe_consume_preview,
    recipe_create,
    recipe_create_by_name,
    recipe_details,
    recipe_fulfillment,
    recipe_remove_ingredient,
    recipe_update,
    recipes_list,
)
from grocy_mcp.core.shopping import (
    shopping_list_add,
    shopping_list_add_missing,
    shopping_list_clear,
    shopping_list_remove,
    shopping_list_set_amount,
    shopping_list_set_note,
    shopping_list_update,
    shopping_list_view,
)
from grocy_mcp.core.stock import (
    product_family_data,
    stock_add,
    stock_barcode_lookup,
    stock_consume,
    stock_entry_edit,
    stock_expiring,
    stock_inventory,
    stock_open,
    stock_overview,
    stock_product_full_data,
    stock_product_info,
    stock_search,
    stock_transfer,
)
from grocy_mcp.core.locations import location_create, locations_list
from grocy_mcp.core.meal_plan import (
    meal_plan_add,
    meal_plan_list,
    meal_plan_remove,
    meal_plan_shopping,
    meal_plan_summary_data,
)
from grocy_mcp.core.reference_data import (
    describe_entity_data,
    discover_entity_fields_data,
    entity_create_view,
    entity_get_data,
    entity_query_data,
    entity_update_view,
    list_entity_records,
    search_entity_candidates_data,
)
from grocy_mcp.core.barcode_lookup import barcode_lookup_external
from grocy_mcp.core.pictures import stock_product_picture_upload
from grocy_mcp.core.stock_journal import stock_journal
from grocy_mcp.core.system import entity_list, entity_manage, system_info
from grocy_mcp.core.tasks import task_complete, task_create, task_delete, task_undo, tasks_list
from grocy_mcp.core.workflows import (
    workflow_match_products_preview_data,
    workflow_shopping_reconcile_apply_data,
    workflow_shopping_reconcile_preview_data,
    workflow_stock_intake_apply_data,
    workflow_stock_intake_preview_data,
)


@asynccontextmanager
async def _get_client() -> AsyncIterator[GrocyClient]:
    """Create a GrocyClient from the current configuration."""
    config = load_config()
    async with GrocyClient(config.url, config.api_key) as client:
        yield client


def _parse_json_arg(value: str, label: str) -> dict | list:
    """Parse a JSON tool argument and raise a user-facing validation error on failure."""
    try:
        return json.loads(value)
    except json.JSONDecodeError as e:
        raise GrocyValidationError(f"Invalid JSON for {label}: {e}") from e


def create_mcp_server() -> FastMCP:
    """Create and return a FastMCP server with all Grocy tools registered."""
    mcp = FastMCP("grocy-mcp")

    # ------------------------------------------------------------------ Stock

    @mcp.tool()
    async def stock_overview_tool() -> str:
        """List all products currently in stock with their quantities.

        Returns each product with its ID, name, and amount. Use this to see
        what is available before adding, consuming, or transferring stock.
        """
        async with _get_client() as client:
            return await stock_overview(client)

    @mcp.tool()
    async def stock_expiring_tool() -> str:
        """List products that are expiring soon, already expired, or below minimum stock.

        Useful for daily checks or deciding what to consume or restock first.
        """
        async with _get_client() as client:
            return await stock_expiring(client)

    @mcp.tool()
    async def stock_product_info_tool(product: str) -> str:
        """Get detailed stock information for a single product.

        Returns current amount, best-before date, and product metadata.

        Args:
            product: Product name (e.g. "Milk") or numeric product ID.
        """
        async with _get_client() as client:
            return await stock_product_info(client, product)

    @mcp.tool()
    async def stock_product_full_tool(product: str) -> dict:
        """Get the complete picture for a single product in one call.

        Returns a structured dict containing:
        - ``product``: full product object (all fields from /objects/products)
        - ``stock``: current totals (amount, value, opened, aggregated, prices, next due date)
        - ``units``: resolved QU names for all four roles (stock / purchase / consume / price)
        - ``location``: resolved default storage location (id + name)
        - ``shopping_location``: resolved product-default shopping location, or null
        - ``product_group``: resolved product group (id + name), or null
        - ``parent_product``: resolved parent product (id + name), or null
        - ``barcodes``: all barcodes for this product, each with resolved QU and
          shopping-location names
        - ``conversions``: all product-specific QU conversion factors (global conversions
          with product_id=null are excluded — they apply to all products)

        Stock journal / history entries are a separate concern and can be voluminous.
        Use ``stock_journal_tool`` when you need transaction history for a product.

        Args:
            product: Product name (e.g. "Milk") or numeric product ID.
        """
        async with _get_client() as client:
            return await stock_product_full_data(client, product)

    @mcp.tool()
    async def stock_add_tool(
        product: str,
        amount: float,
        location: str | None = None,
        shopping_location: str | None = None,
        price: float | None = None,
        best_before_date: str | None = None,
        purchased_date: str | None = None,
        note: str | None = None,
    ) -> str:
        """Add stock for a product (e.g. after a purchase).

        Args:
            product: Product name (e.g. "Milk") or numeric product ID.
            amount: Quantity to add (e.g. 2.0 for two units).
            location: Optional storage location (e.g. "Freezer") where the stock
                is stored. Defaults to the product's default location.
            shopping_location: Optional store name (e.g. "Coles Woolloongabba") where
                the purchase was made. Records a purchase entry for price history.
            price: Optional price per unit paid. Combined with shopping_location to
                build a price-over-time history in Grocy.
            best_before_date: Optional best-before / expiry date in YYYY-MM-DD format.
                Defaults to today if omitted.
            purchased_date: Optional purchase date in YYYY-MM-DD format (e.g.
                "2026-05-31"). Not in Grocy's official add spec — try passing it
                here first; if the entry shows the wrong date afterwards, fall back
                to stock_entry_edit_tool to correct it.
            note: Optional note to attach to the stock entry.
        """
        kwargs: dict = {}
        if best_before_date is not None:
            kwargs["best_before_date"] = best_before_date
        if purchased_date is not None:
            kwargs["purchased_date"] = purchased_date
        if price is not None:
            kwargs["price"] = price
        if note is not None:
            kwargs["note"] = note
        async with _get_client() as client:
            return await stock_add(client, product, amount, location, shopping_location, **kwargs)

    @mcp.tool()
    async def stock_consume_tool(product: str, amount: float) -> str:
        """Consume stock for a product (reduces the quantity on hand).

        Args:
            product: Product name (e.g. "Milk") or numeric product ID.
            amount: Quantity to consume.
        """
        async with _get_client() as client:
            return await stock_consume(client, product, amount)

    @mcp.tool()
    async def stock_transfer_tool(
        product: str, amount: float, to_location: str, from_location: str
    ) -> str:
        """Move stock of a product between two storage locations.

        Grocy requires an explicit source location, so both ends are mandatory.

        Args:
            product: Product name (e.g. "Milk") or numeric product ID.
            amount: Quantity to transfer.
            to_location: Destination location name (e.g. "Freezer") or numeric location ID.
            from_location: Source location name (e.g. "Pantry") or numeric location ID.
                Use locations_list_tool to see options.
        """
        async with _get_client() as client:
            return await stock_transfer(client, product, amount, to_location, from_location)

    @mcp.tool()
    async def stock_inventory_tool(product: str, new_amount: float) -> str:
        """Correct the stock level for a product by setting an absolute quantity.

        Use this when the actual count differs from what Grocy shows — e.g. after
        a manual count. This replaces the current amount, not adds to it.

        Args:
            product: Product name (e.g. "Milk") or numeric product ID.
            new_amount: The corrected total stock quantity.
        """
        async with _get_client() as client:
            return await stock_inventory(client, product, new_amount)

    @mcp.tool()
    async def stock_open_tool(product: str, amount: float = 1.0) -> str:
        """Mark stock units as opened (e.g. an opened bottle of milk).

        Args:
            product: Product name (e.g. "Milk") or numeric product ID.
            amount: Number of units to mark as opened (default 1).
        """
        async with _get_client() as client:
            return await stock_open(client, product, amount)

    @mcp.tool()
    async def stock_entry_edit_tool(
        entry_id: int,
        best_before_date: str | None = None,
        price: float | None = None,
        purchased_date: str | None = None,
        location: str | None = None,
        shopping_location: str | None = None,
        note: str | None = None,
        amount: float | None = None,
    ) -> str:
        """Edit fields on an existing stock entry (best-before, price, date, location, note).

        Fetches the current entry first so Grocy's full-payload PUT requirement is
        satisfied automatically — only the fields you pass are changed.

        To find an entry_id: use stock_journal_tool or stock_product_info_tool to
        see stock entries with their IDs.

        Args:
            entry_id: Numeric ID of the stock entry to edit.
            best_before_date: New best-before / expiry date in YYYY-MM-DD format.
            price: New price per stock unit.
            purchased_date: Purchase date in YYYY-MM-DD format — use this to backdate
                an entry (e.g. "2026-05-31"). Confirmed in Grocy's OpenAPI spec.
            location: New storage location name or numeric ID.
            shopping_location: Store where purchased (e.g. "Coles"). Updates
                shopping_location_id on the entry.
            note: New note text to attach to this stock entry.
            amount: Corrected quantity for this specific entry (use stock_inventory_tool
                to set the total for a product instead).
        """
        async with _get_client() as client:
            return await stock_entry_edit(
                client, entry_id, best_before_date, price, purchased_date,
                location, shopping_location, note, amount
            )

    @mcp.tool()
    async def stock_product_entries_tool(product: str) -> str:
        """List all individual stock entries for a product, with their entry IDs.

        Use this to find the entry_id required by stock_entry_edit_tool. Each entry
        represents a discrete batch (e.g. two cans bought on different dates will be
        two separate entries with different IDs, best-before dates, and prices).

        Args:
            product: Product name (e.g. "Milk") or numeric product ID.
        """
        from grocy_mcp.core.resolve import resolve_product
        async with _get_client() as client:
            product_id = await resolve_product(client, product)
            entries = await client.get_product_entries(product_id)
            if not entries:
                return f"No stock entries found for '{product}'."
            lines = [f"Stock entries for '{product}' (product ID {product_id}):"]
            for e in entries:
                eid = e.get("id")
                amount = e.get("amount")
                bbd = e.get("best_before_date", "—")
                price = e.get("price")
                loc = e.get("location_id")
                note = e.get("note", "")
                parts = [f"  [{eid}] amount={amount}  bbd={bbd}"]
                if price is not None:
                    parts[0] += f"  price={price}"
                if loc is not None:
                    parts[0] += f"  location_id={loc}"
                if note:
                    parts[0] += f"  note={note!r}"
                lines.append(parts[0])
            return "\n".join(lines)

    @mcp.tool()
    async def stock_search_tool(query: str) -> str:
        """Find products whose NAME or BARCODE contains a substring.

        This is a plain case-insensitive SUBSTRING match on the product name and
        barcode fields ONLY. It does NOT understand categories, variants, or
        parent/child relationships, so it will MISS related products that don't
        literally contain the query text. Do not conclude "there's only one" from
        a name search — a single hit may be a parent with differently-named
        children, or a category whose members use brand names.

        Escalate to a relationship- or category-aware tool when the question is
        "show me all X" rather than "find the product literally called X":
        - Variants / children of a product → product_family_tool (one call returns
          the product, its children, and aggregated stock), or
          entity_query_tool(entity="products", filters={"parent_product_id": <id>}).
        - Everything in a category → entity_query_tool(entity="products",
          filters={"product_group_id": <id>}) (find the group id via
          entity_list_tool(entity="product_groups")).
        For a direct barcode lookup with stock details, use stock_barcode_lookup_tool.

        Args:
            query: Substring to match against product names and barcodes.
        """
        async with _get_client() as client:
            return await stock_search(client, query)

    @mcp.tool()
    async def product_family_tool(product: str) -> dict:
        """Get a product's full parent/child family + aggregated stock in one call.

        Grocy models product variants with ``parent_product_id``: a parent product
        (e.g. "Laundry liquid") groups concrete children (e.g. "Omo Speed Clean
        1.18L", "Omo Odor Refresh 1.94L"). Parents commonly have ``no_own_stock=1``
        and ``cumulate_min_stock_amount_of_sub_products=1`` — their real stock lives
        in the children and shows on the parent as ``amount_aggregated``.

        Use this for "show me all <category/variant>" questions where a plain name
        search (stock_search_tool) would only return one product. It works from
        EITHER end: pass a parent or a child (by name or id) and it resolves up to
        the family root and returns the whole family.

        Returns a structured dict:
        - ``root``: the family root — id, name, ``is_parent``, ``no_own_stock``,
          ``cumulate_min_stock_amount_of_sub_products``, ``min_stock_amount``,
          ``stock_unit``, and stock totals (``amount``, ``amount_opened``,
          ``amount_aggregated``, ``amount_opened_aggregated``).
        - ``queried``: the product you passed (id, name, ``was_child``).
        - ``children``: each child product with ``amount`` (current stock),
          ``unit``, and ``min_stock_amount``.

        Args:
            product: Product name (e.g. "Laundry liquid") or numeric product ID;
                may be a parent or a child.
        """
        async with _get_client() as client:
            return await product_family_data(client, product)

    @mcp.tool()
    async def stock_barcode_lookup_tool(barcode: str) -> str:
        """Look up a product and its current stock level by exact barcode.

        Returns the product name and quantity in stock. For partial or name-based
        searches, use stock_search_tool instead.

        Args:
            barcode: The exact barcode string (e.g. "5000112637922").
        """
        async with _get_client() as client:
            return await stock_barcode_lookup(client, barcode)

    @mcp.tool()
    async def stock_price_history_tool(product: str) -> str:
        """Return the purchase price history for a product.

        Shows each recorded price entry with the price, shopping location, and date.
        Useful for tracking price trends over time.

        Args:
            product: Product name (e.g. "Milk") or numeric product ID.
        """
        from grocy_mcp.core.resolve import resolve_product
        async with _get_client() as client:
            product_id = await resolve_product(client, product)
            history = await client.get_product_price_history(product_id)
            if not history:
                return f"No price history found for '{product}'."
            lines = [f"Price history for '{product}':"]
            for entry in history:
                price = entry.get("price", "?")
                store = entry.get("shopping_location", {}) or {}
                store_name = store.get("name") if isinstance(store, dict) else "?"
                date = entry.get("date", "?")
                lines.append(f"  {date}  price={price}  store={store_name or '—'}")
            return "\n".join(lines)

    @mcp.tool()
    async def stock_product_merge_tool(product_to_keep: str, product_to_remove: str) -> str:
        """Merge two products into one, keeping all stock and history under the first product.

        The product_to_remove will be deleted; all its stock entries, barcodes, and
        history are transferred to product_to_keep. This cannot be undone.

        Args:
            product_to_keep: Name or ID of the product to keep.
            product_to_remove: Name or ID of the product to delete after merging.
        """
        from grocy_mcp.core.resolve import resolve_product
        async with _get_client() as client:
            keep_id = await resolve_product(client, product_to_keep)
            remove_id = await resolve_product(client, product_to_remove)
            await client.merge_products(keep_id, remove_id)
            return (
                f"Merged '{product_to_remove}' (ID {remove_id}) into "
                f"'{product_to_keep}' (ID {keep_id}). The removed product no longer exists."
            )

    @mcp.tool()
    async def stock_product_locations_tool(product: str) -> str:
        """List all locations where a product currently has stock.

        Useful before a transfer to confirm where stock is currently held.

        Args:
            product: Product name (e.g. "Milk") or numeric product ID.
        """
        from grocy_mcp.core.resolve import resolve_product
        async with _get_client() as client:
            product_id = await resolve_product(client, product)
            locations = await client.get_product_locations(product_id)
            if not locations:
                return f"No stock locations found for '{product}'."
            lines = [f"Stock locations for '{product}':"]
            for loc in locations:
                loc_id = loc.get("id") or loc.get("location_id")
                name = loc.get("name", f"Location {loc_id}")
                amount = loc.get("amount", "?")
                is_freezer = loc.get("is_freezer")
                suffix = " (freezer)" if is_freezer else ""
                lines.append(f"  [{loc_id}] {name}{suffix} — amount: {amount}")
            return "\n".join(lines)

    @mcp.tool()
    async def stock_location_entries_tool(location_id: int) -> str:
        """List all stock entries at a specific location.

        Shows every individual batch stored at the location with amount, product,
        and best-before date.

        Args:
            location_id: Numeric location ID (from locations_list_tool).
        """
        async with _get_client() as client:
            entries = await client.get_location_entries(location_id)
            if not entries:
                return f"No stock entries found at location ID {location_id}."
            lines = [f"Stock entries at location {location_id}:"]
            for e in entries:
                eid = e.get("id")
                product_id = e.get("product_id")
                amount = e.get("amount")
                bbd = e.get("best_before_date", "—")
                note = e.get("note", "")
                line = f"  [{eid}] product_id={product_id}  amount={amount}  bbd={bbd}"
                if note:
                    line += f"  note={note!r}"
                lines.append(line)
            return "\n".join(lines)

    @mcp.tool()
    async def stock_transaction_undo_tool(booking_id: int) -> str:
        """Undo a specific stock booking/transaction by its booking ID.

        Reverses a single stock change (purchase, consumption, transfer, etc.).
        Use stock_journal_tool to find booking IDs — look for the 'id' field
        in recent transactions.

        Args:
            booking_id: Numeric stock booking ID to undo.
        """
        async with _get_client() as client:
            await client.undo_booking(booking_id)
            return f"Stock booking {booking_id} has been undone."

    @mcp.tool()
    async def shopping_list_add_expired_tool(list_id: int = 1) -> str:
        """Add all expired products to the shopping list for restocking.

        Scans stock for expired items and adds them to the given shopping list.
        Useful for identifying what needs replacing after a fridge/pantry clear-out.

        Args:
            list_id: Shopping list ID (default 1).
        """
        async with _get_client() as client:
            await client.add_expired_to_shopping_list(list_id)
            return f"Expired products added to shopping list {list_id}."

    @mcp.tool()
    async def shopping_list_add_overdue_tool(list_id: int = 1) -> str:
        """Add all overdue products to the shopping list for restocking.

        Scans stock for products past their best-before date and adds them to
        the given shopping list.

        Args:
            list_id: Shopping list ID (default 1).
        """
        async with _get_client() as client:
            await client.add_overdue_to_shopping_list(list_id)
            return f"Overdue products added to shopping list {list_id}."

    # --------------------------------------------------------------- Shopping

    @mcp.tool()
    async def shopping_list_view_tool(list_id: int = 1) -> str:
        """View all items on a shopping list.

        Returns each item with its ID, product name, quantity, and optional note.
        Item IDs are needed for update and remove operations.

        Args:
            list_id: Shopping list ID (default 1, which is the primary list).
        """
        async with _get_client() as client:
            return await shopping_list_view(client, list_id)

    @mcp.tool()
    async def shopping_list_add_tool(
        product: str, amount: float = 1.0, list_id: int = 1, note: str | None = None
    ) -> str:
        """Add a product to the shopping list.

        Args:
            product: Product name (e.g. "Butter") or numeric product ID.
            amount: Quantity to buy (default 1).
            list_id: Shopping list ID (default 1).
            note: Optional free-text note (e.g. "salted" or "organic").
        """
        async with _get_client() as client:
            return await shopping_list_add(client, product, amount, list_id, note)

    @mcp.tool()
    async def shopping_list_update_tool(item_id: int, data: str) -> str:
        """Update fields on an existing shopping list item.

        Use shopping_list_view_tool first to find the item_id.

        Args:
            item_id: The shopping list item ID (from shopping_list_view_tool output).
            data: JSON object with fields to update. Supported fields include
                  "amount" (number), "note" (string), and "product_id" (integer).
                  Example: '{"amount": 3, "note": "unsalted"}'.
        """
        async with _get_client() as client:
            return await shopping_list_update(client, item_id, _parse_json_arg(data, "data"))

    @mcp.tool()
    async def shopping_list_remove_tool(item_id: int) -> str:
        """Remove a single item from the shopping list.

        Use shopping_list_view_tool first to find the item_id.

        Args:
            item_id: The shopping list item ID to remove.
        """
        async with _get_client() as client:
            return await shopping_list_remove(client, item_id)

    @mcp.tool()
    async def shopping_list_clear_tool(list_id: int = 1) -> str:
        """Remove ALL items from a shopping list. This cannot be undone.

        Args:
            list_id: Shopping list ID to clear (default 1).
        """
        async with _get_client() as client:
            return await shopping_list_clear(client, list_id)

    @mcp.tool()
    async def shopping_list_add_missing_tool(list_id: int = 1) -> str:
        """Add all products that are below their minimum stock level to the shopping list.

        This is a bulk operation — it scans all products and adds any that are
        below their configured minimum stock quantity.

        Args:
            list_id: Shopping list ID to add missing products to (default 1).
        """
        async with _get_client() as client:
            return await shopping_list_add_missing(client, list_id)

    @mcp.tool()
    async def shopping_list_set_amount_tool(item_id: int, amount: float) -> str:
        """Change the quantity for a shopping list item.

        A simpler alternative to shopping_list_update_tool when you only
        need to change the amount.

        Args:
            item_id: The shopping list item ID (from shopping_list_view_tool).
            amount: New quantity.
        """
        async with _get_client() as client:
            return await shopping_list_set_amount(client, item_id, amount)

    @mcp.tool()
    async def shopping_list_set_note_tool(item_id: int, note: str) -> str:
        """Set or update the note on a shopping list item.

        A simpler alternative to shopping_list_update_tool when you only
        need to change the note.

        Args:
            item_id: The shopping list item ID (from shopping_list_view_tool).
            note: The new note text (e.g. "organic", "2 for 1 deal").
        """
        async with _get_client() as client:
            return await shopping_list_set_note(client, item_id, note)

    # ---------------------------------------------------------------- Recipes

    @mcp.tool()
    async def recipes_list_tool() -> str:
        """List all recipes with their IDs and descriptions.

        Use this to discover available recipes before checking fulfillment
        or consuming ingredients.
        """
        async with _get_client() as client:
            return await recipes_list(client)

    @mcp.tool()
    async def recipe_details_tool(recipe: str) -> str:
        """Show full details for a recipe including all ingredients and amounts.

        Args:
            recipe: Recipe name (e.g. "Spaghetti Bolognese") or numeric recipe ID.
        """
        async with _get_client() as client:
            return await recipe_details(client, recipe)

    @mcp.tool()
    async def recipe_fulfillment_tool(recipe: str) -> str:
        """Check whether a recipe can be made with current stock.

        Reports whether all ingredients are available and how many are missing.

        Args:
            recipe: Recipe name (e.g. "Spaghetti Bolognese") or numeric recipe ID.
        """
        async with _get_client() as client:
            return await recipe_fulfillment(client, recipe)

    @mcp.tool()
    async def recipe_consume_tool(recipe: str) -> str:
        """Consume stock for all ingredients of a recipe (as if you cooked it).

        This deducts each ingredient amount from stock. Check fulfillment first
        to make sure all ingredients are available.

        Args:
            recipe: Recipe name (e.g. "Spaghetti Bolognese") or numeric recipe ID.
        """
        async with _get_client() as client:
            return await recipe_consume(client, recipe)

    @mcp.tool()
    async def recipe_add_to_shopping_tool(recipe: str) -> str:
        """Add only the missing ingredients for a recipe to the shopping list.

        Does not add ingredients that are already sufficiently in stock.

        Args:
            recipe: Recipe name (e.g. "Spaghetti Bolognese") or numeric recipe ID.
        """
        async with _get_client() as client:
            return await recipe_add_to_shopping(client, recipe)

    @mcp.tool()
    async def recipe_create_tool(name: str, description: str = "", ingredients: str = "[]") -> str:
        """Create a new recipe in Grocy.

        Args:
            name: Recipe name (e.g. "Banana Bread").
            description: Optional description or instructions for the recipe.
            ingredients: JSON array of ingredient objects. Each object should have
                         "product_id" (integer) and "amount" (number). Use
                         stock_search_tool to find product IDs.
                         Example: '[{"product_id": 1, "amount": 2}, {"product_id": 5, "amount": 0.5}]'.
        """
        parsed_ingredients = _parse_json_arg(ingredients, "ingredients")
        async with _get_client() as client:
            return await recipe_create(client, name, description, parsed_ingredients or None)

    @mcp.tool()
    async def recipe_create_by_name_tool(
        name: str, description: str = "", ingredients: str = "[]"
    ) -> str:
        """Create a recipe with ingredients specified by product name instead of ID.

        This is the easier alternative to recipe_create_tool — you can use
        product names directly, and they will be resolved automatically.

        Args:
            name: Recipe name (e.g. "Banana Bread").
            description: Optional description or instructions.
            ingredients: JSON array of ingredient objects. Each should have
                         "product" (name string) and "amount" (number).
                         Example: '[{"product": "Flour", "amount": 2}, {"product": "Banana", "amount": 3}]'.
        """
        parsed_ingredients = _parse_json_arg(ingredients, "ingredients")
        async with _get_client() as client:
            return await recipe_create_by_name(
                client, name, description, parsed_ingredients or None
            )

    @mcp.tool()
    async def recipe_update_tool(
        recipe: str,
        name: str | None = None,
        description: str | None = None,
    ) -> str:
        """Update a recipe's name or description.

        Args:
            recipe: Current recipe name or ID to update.
            name: New name (omit to keep current).
            description: New description (omit to keep current).
        """
        async with _get_client() as client:
            return await recipe_update(client, recipe, name, description)

    @mcp.tool()
    async def recipe_add_ingredient_tool(recipe: str, product: str, amount: float = 1.0) -> str:
        """Add an ingredient to an existing recipe using the product name.

        Args:
            recipe: Recipe name or ID.
            product: Product name (e.g. "Flour") — resolved automatically.
            amount: Quantity needed for the recipe (default 1).
        """
        async with _get_client() as client:
            return await recipe_add_ingredient(client, recipe, product, amount)

    @mcp.tool()
    async def recipe_remove_ingredient_tool(position_id: int) -> str:
        """Remove an ingredient from a recipe.

        Use recipe_details_tool to see ingredient position IDs.

        Args:
            position_id: The recipe ingredient position ID to remove.
        """
        async with _get_client() as client:
            return await recipe_remove_ingredient(client, position_id)

    @mcp.tool()
    async def recipe_consume_preview_tool(recipe: str) -> str:
        """Preview what stock would be consumed without actually consuming.

        Shows each ingredient, the amount needed, and whether there is
        enough in stock. Use this before recipe_consume_tool to verify.

        Args:
            recipe: Recipe name or ID.
        """
        async with _get_client() as client:
            return await recipe_consume_preview(client, recipe)

    @mcp.tool()
    async def recipe_copy_tool(recipe_id: int) -> str:
        """Clone an existing recipe, creating a duplicate with a new ID.

        Useful for creating variations without modifying the original.
        The copy will have the same name as the original (typically with
        a "Copy of" prefix as set by Grocy).

        Args:
            recipe_id: Numeric recipe ID to copy (from recipes_list_tool).
        """
        async with _get_client() as client:
            new_id = await client.copy_recipe(recipe_id)
            return f"Recipe {recipe_id} copied successfully. New recipe ID: {new_id}."

    @mcp.tool()
    async def recipe_fulfillment_all_tool() -> str:
        """Check stock fulfillment status for ALL recipes at once.

        Returns a summary showing which recipes can be made with current stock
        and which are missing ingredients. Useful for meal planning.
        """
        async with _get_client() as client:
            results = await client.get_all_recipes_fulfillment()
            if not results:
                return "No recipes found."
            lines = ["Recipe fulfillment status:"]
            for r in results:
                recipe_id = r.get("recipe_id")
                name = r.get("recipe", {}).get("name") if isinstance(r.get("recipe"), dict) else f"Recipe {recipe_id}"
                fulfilled = r.get("need_fulfilled")
                missing = r.get("missing_products_count", 0)
                status = "✓ ready" if fulfilled else f"✗ missing {missing} ingredient(s)"
                lines.append(f"  [{recipe_id}] {name} — {status}")
            return "\n".join(lines)

    # ----------------------------------------------------------------- Chores

    @mcp.tool()
    async def chores_list_tool() -> str:
        """List all chores with their IDs and next scheduled execution time.

        Use this to see what chores exist and when they are due next.
        """
        async with _get_client() as client:
            return await chores_list(client)

    @mcp.tool()
    async def chores_overdue_tool() -> str:
        """List chores that are past their scheduled execution time.

        Returns only chores where the next execution time is in the past.
        """
        async with _get_client() as client:
            return await chores_overdue(client)

    @mcp.tool()
    async def chore_execute_tool(chore: str, done_by: int | None = None) -> str:
        """Mark a chore as done.

        This records an execution and advances the next scheduled time.

        Args:
            chore: Chore name (e.g. "Vacuum living room") or numeric chore ID.
            done_by: Optional Grocy user ID of the person who did the chore.
        """
        async with _get_client() as client:
            return await chore_execute(client, chore, done_by)

    @mcp.tool()
    async def chore_undo_tool(chore: str) -> str:
        """Undo the most recent execution of a chore.

        Removes the last recorded execution and reverts the schedule.

        Args:
            chore: Chore name (e.g. "Vacuum living room") or numeric chore ID.
        """
        async with _get_client() as client:
            return await chore_undo(client, chore)

    @mcp.tool()
    async def chore_create_tool(
        name: str,
        description: str | None = None,
        period_type: str | None = None,
        period_interval: int | None = None,
        period_config: str | None = None,
        track_date_only: bool = False,
        rollover: bool = False,
        assignment_type: str | None = None,
        assignment_config: str | None = None,
        consume_product_on_execution: bool = False,
        product_id: int | None = None,
        product_amount: float | None = None,
        active: bool = True,
        start_date: str | None = None,
    ) -> str:
        """Create a new chore in Grocy with optional scheduling and assignment settings.

        Args:
            name: Name for the chore (e.g. "Clean bathroom").
            description: Optional description.
            period_type: How often the chore repeats. One of: "manually", "daily",
                "weekly" (period_config = comma-separated ISO weekday numbers 1-7),
                "monthly", "yearly", "hourly", "half-hourly", "quarter-hourly",
                "two-hourly", "every-72-hours". Omit for manual-only chores.
            period_interval: How many period units between executions (default 1).
                E.g. period_type="weekly", period_interval=2 = every 2 weeks.
            period_config: Extra config for the period type. For "weekly": comma-separated
                day numbers (1=Mon … 7=Sun, e.g. "1,3,5" for Mon/Wed/Fri).
            track_date_only: If true, track only the date (not time) of execution.
            rollover: If true, skip overdue executions and roll to the next scheduled time.
            assignment_type: How to assign the chore. One of: "no-assignment",
                "random", "in-order-starting-with-first-user",
                "in-order-starting-with-last-user".
            assignment_config: JSON array of Grocy user IDs for rotation/assignment,
                e.g. "[1, 2, 3]". Required when assignment_type is not "no-assignment".
            consume_product_on_execution: If true, consume product_id/product_amount stock.
            product_id: Product ID to consume on execution (requires consume_product_on_execution).
            product_amount: Amount of product to consume on execution.
            active: Whether the chore is active (default true).
            start_date: ISO date string (YYYY-MM-DD) for when the chore starts.
        """
        async with _get_client() as client:
            return await chore_create(
                client, name, description, period_type, period_interval, period_config,
                track_date_only, rollover, assignment_type, assignment_config,
                consume_product_on_execution, product_id, product_amount, active, start_date,
            )

    @mcp.tool()
    async def chore_merge_tool(chore_to_keep: str, chore_to_remove: str) -> str:
        """Merge two chores into one, keeping all execution history under the first chore.

        The chore_to_remove will be deleted; all its execution log entries are
        transferred to chore_to_keep. This cannot be undone.

        Args:
            chore_to_keep: Name or ID of the chore to keep.
            chore_to_remove: Name or ID of the chore to delete after merging.
        """
        from grocy_mcp.core.resolve import resolve_chore
        async with _get_client() as client:
            keep_id = await resolve_chore(client, chore_to_keep)
            remove_id = await resolve_chore(client, chore_to_remove)
            await client.merge_chores(keep_id, remove_id)
            return (
                f"Merged '{chore_to_remove}' (ID {remove_id}) into "
                f"'{chore_to_keep}' (ID {keep_id}). The removed chore no longer exists."
            )

    @mcp.tool()
    async def chore_next_assignments_tool() -> str:
        """Recalculate next assigned user for all chores with user rotation.

        Grocy tracks whose turn it is for chores with rotation-based assignment.
        Call this after changing chore assignments or execution history to
        ensure the next-user field is up to date.
        """
        async with _get_client() as client:
            await client.calculate_chore_next_assignments()
            return "Next user assignments recalculated for all chores."

    # -------------------------------------------------------------- Locations

    @mcp.tool()
    async def locations_list_tool() -> str:
        """List all storage locations in Grocy.

        Shows location names, IDs, and whether each is a freezer.
        """
        async with _get_client() as client:
            return await locations_list(client)

    @mcp.tool()
    async def location_create_tool(
        name: str, is_freezer: bool = False, description: str = ""
    ) -> str:
        """Create a new storage location.

        Args:
            name: Location name (e.g. "Pantry", "Garage fridge").
            is_freezer: Whether this location is a freezer (default false).
            description: Optional description.
        """
        async with _get_client() as client:
            return await location_create(client, name, is_freezer, description)

    # ---------------------------------------------------------- Stock Journal

    @mcp.tool()
    async def stock_journal_tool(product: str | None = None) -> str:
        """View recent stock transaction history.

        Shows the 50 most recent stock changes (purchases, consumption,
        transfers, inventory corrections). Optionally filter by product.

        Args:
            product: Optional product name or ID to filter by.
        """
        async with _get_client() as client:
            return await stock_journal(client, product)

    # ------------------------------------------------------------------ Tasks

    @mcp.tool()
    async def tasks_list_tool(show_done: bool = False) -> str:
        """List tasks (to-do items separate from chores).

        By default shows only incomplete tasks.

        Args:
            show_done: If true, also include completed tasks.
        """
        async with _get_client() as client:
            return await tasks_list(client, show_done)

    @mcp.tool()
    async def task_create_tool(
        name: str,
        due_date: str | None = None,
        assigned_to_user_id: int | None = None,
        description: str = "",
    ) -> str:
        """Create a new task.

        Args:
            name: Task description (e.g. "Buy birthday present").
            due_date: Optional due date in YYYY-MM-DD format.
            assigned_to_user_id: Optional Grocy user ID to assign the task to.
            description: Optional longer description or notes.
        """
        async with _get_client() as client:
            return await task_create(client, name, due_date, assigned_to_user_id, description)

    @mcp.tool()
    async def task_complete_tool(task_id: int) -> str:
        """Mark a task as done.

        Args:
            task_id: The task ID (from tasks_list_tool output).
        """
        async with _get_client() as client:
            return await task_complete(client, task_id)

    @mcp.tool()
    async def task_undo_tool(task_id: int) -> str:
        """Mark a task as not completed.

        Args:
            task_id: The task ID to undo.
        """
        async with _get_client() as client:
            return await task_undo(client, task_id)

    @mcp.tool()
    async def task_delete_tool(task_id: int) -> str:
        """Delete a task. This cannot be undone.

        Args:
            task_id: The task ID to delete.
        """
        async with _get_client() as client:
            return await task_delete(client, task_id)

    # --------------------------------------------------------------- Meal Plan

    @mcp.tool()
    async def meal_plan_list_tool() -> str:
        """List all meal plan entries sorted by date.

        Shows scheduled meals with their dates, recipe names, and notes.
        """
        async with _get_client() as client:
            return await meal_plan_list(client)

    @mcp.tool()
    async def meal_plan_add_tool(
        day: str,
        recipe: str | None = None,
        note: str = "",
        meal_type: str = "",
    ) -> str:
        """Add an entry to the meal plan.

        Either specify a recipe or a free-text note (or both).

        Args:
            day: Date in YYYY-MM-DD format (e.g. "2026-04-05").
            recipe: Optional recipe name or ID to schedule.
            note: Optional free-text note (e.g. "Eat out" or "Leftovers").
            meal_type: Optional meal type (e.g. "recipe", "note"). Auto-detected
                       if not provided.
        """
        async with _get_client() as client:
            return await meal_plan_add(client, day, recipe, note, meal_type)

    @mcp.tool()
    async def meal_plan_remove_tool(entry_id: int) -> str:
        """Remove an entry from the meal plan.

        Args:
            entry_id: The meal plan entry ID (from meal_plan_list_tool output).
        """
        async with _get_client() as client:
            return await meal_plan_remove(client, entry_id)

    @mcp.tool()
    async def meal_plan_shopping_tool(
        start_date: str | None = None, end_date: str | None = None
    ) -> str:
        """Add missing ingredients for all planned recipes to the shopping list.

        Scans the meal plan (optionally filtered by date range), finds all
        scheduled recipes, and adds their unfulfilled ingredients to the
        shopping list. This is the "plan meals → shop" workflow in one step.

        Args:
            start_date: Optional start date filter (YYYY-MM-DD, inclusive).
            end_date: Optional end date filter (YYYY-MM-DD, inclusive).
        """
        async with _get_client() as client:
            return await meal_plan_shopping(client, start_date, end_date)

    @mcp.tool()
    async def meal_plan_summary_tool(
        start_date: str | None = None,
        end_date: str | None = None,
        section_id: int | None = None,
    ) -> dict:
        """Return a structured meal-plan summary with recipe and section names.

        Args:
            start_date: Optional start date filter in YYYY-MM-DD format.
            end_date: Optional end date filter in YYYY-MM-DD format.
            section_id: Optional meal-plan section filter.
        """
        async with _get_client() as client:
            return await meal_plan_summary_data(client, start_date, end_date, section_id)

    # ---------------------------------------------------------------- Catalog

    @mcp.tool()
    async def catalog_list_tool(entity: str, query: str | None = None) -> list[dict]:
        """List first-class catalog and metadata entities.

        Supported entities include shopping_lists, shopping_locations,
        quantity_units, quantity_unit_conversions, product_groups,
        task_categories, meal_plan_sections, products_last_purchased,
        and products_average_price.
        """
        async with _get_client() as client:
            return await list_entity_records(client, entity, query)

    @mcp.tool()
    async def catalog_details_tool(entity: str, obj_id: int) -> dict:
        """Return details for a first-class catalog entity record."""
        async with _get_client() as client:
            return await client.get_object(entity, obj_id)

    @mcp.tool()
    async def catalog_create_tool(entity: str, data: str) -> str:
        """Create a record in a writable first-class catalog entity."""
        parsed_data = _parse_json_arg(data, "data")
        async with _get_client() as client:
            return await entity_create_view(client, entity, parsed_data)

    @mcp.tool()
    async def catalog_update_tool(entity: str, obj_id: int, data: str) -> str:
        """Update a record in a writable first-class catalog entity."""
        parsed_data = _parse_json_arg(data, "data")
        async with _get_client() as client:
            return await entity_update_view(client, entity, obj_id, parsed_data)

    # -------------------------------------------------------------- Batteries

    @mcp.tool()
    async def batteries_list_tool() -> list[dict]:
        """List batteries with next estimated charge times."""
        async with _get_client() as client:
            return await batteries_list_data(client)

    @mcp.tool()
    async def battery_details_tool(battery: str) -> dict:
        """Return detailed information for a battery by name or ID."""
        async with _get_client() as client:
            return await battery_details_data(client, battery)

    @mcp.tool()
    async def batteries_due_tool(days: int = 7) -> list[dict]:
        """Return batteries due within the next given number of days."""
        async with _get_client() as client:
            return await batteries_due_data(client, days)

    @mcp.tool()
    async def batteries_overdue_tool() -> list[dict]:
        """Return batteries that are already overdue for charging."""
        async with _get_client() as client:
            return await batteries_overdue_data(client)

    @mcp.tool()
    async def battery_charge_tool(battery: str, tracked_time: str | None = None) -> str:
        """Track a battery charge cycle."""
        async with _get_client() as client:
            return await battery_charge(client, battery, tracked_time)

    @mcp.tool()
    async def battery_history_tool(battery: str) -> list[dict]:
        """Return charge-cycle history for a battery."""
        async with _get_client() as client:
            return await battery_cycle_history_data(client, battery)

    @mcp.tool()
    async def battery_undo_cycle_tool(cycle_id: int) -> str:
        """Undo a tracked battery charge cycle."""
        async with _get_client() as client:
            return await battery_undo_cycle(client, cycle_id)

    @mcp.tool()
    async def battery_create_tool(
        name: str,
        used_in: str = "",
        charge_interval_days: int = 0,
        description: str = "",
    ) -> str:
        """Create a battery object."""
        async with _get_client() as client:
            return await battery_create(client, name, used_in, charge_interval_days, description)

    @mcp.tool()
    async def battery_update_tool(
        battery: str,
        name: str | None = None,
        used_in: str | None = None,
        charge_interval_days: int | None = None,
        description: str | None = None,
    ) -> str:
        """Update a battery object."""
        async with _get_client() as client:
            return await battery_update(
                client, battery, name, used_in, charge_interval_days, description
            )

    # -------------------------------------------------------------- Equipment

    @mcp.tool()
    async def equipment_list_tool() -> list[dict]:
        """List equipment with linked battery visibility where available."""
        async with _get_client() as client:
            return await equipment_list_data(client)

    @mcp.tool()
    async def equipment_details_tool(equipment: str) -> dict:
        """Return details for an equipment item by name or ID."""
        async with _get_client() as client:
            return await equipment_details_data(client, equipment)

    @mcp.tool()
    async def equipment_create_tool(
        name: str,
        description: str = "",
        battery_id: int | None = None,
    ) -> str:
        """Create an equipment item."""
        async with _get_client() as client:
            return await equipment_create(client, name, description, battery_id)

    @mcp.tool()
    async def equipment_update_tool(
        equipment: str,
        name: str | None = None,
        description: str | None = None,
        battery_id: int | None = None,
    ) -> str:
        """Update an equipment item."""
        async with _get_client() as client:
            return await equipment_update(client, equipment, name, description, battery_id)

    # --------------------------------------------------------------- Calendar

    @mcp.tool()
    async def calendar_summary_tool(
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict:
        """Return a read-only planning summary across tasks, chores, batteries, and meal plan."""
        async with _get_client() as client:
            return await calendar_summary_data(client, start_date, end_date)

    @mcp.tool()
    async def calendar_ical_tool() -> dict:
        """Return the raw Grocy iCal export."""
        async with _get_client() as client:
            return {"content": await calendar_ical_export(client)}

    @mcp.tool()
    async def calendar_sharing_link_tool() -> dict:
        """Return the public Grocy iCal sharing link."""
        async with _get_client() as client:
            return await client.get_calendar_sharing_link()

    # ------------------------------------------------------------------ Files

    @mcp.tool()
    async def file_download_tool(
        group: str,
        file_name: str,
        force_picture: bool = False,
        best_fit_width: int | None = None,
        best_fit_height: int | None = None,
    ) -> dict:
        """Download a Grocy-managed file as base64 content."""
        async with _get_client() as client:
            return await file_download_data(
                client, group, file_name, force_picture, best_fit_width, best_fit_height
            )

    @mcp.tool()
    async def file_upload_tool(group: str, file_name: str, content_base64: str) -> dict:
        """Upload a Grocy-managed file from base64 content."""
        async with _get_client() as client:
            return await file_upload_data(client, group, file_name, content_base64)

    @mcp.tool()
    async def file_delete_tool(group: str, file_name: str) -> str:
        """Delete a Grocy-managed file."""
        async with _get_client() as client:
            return await file_delete(client, group, file_name)

    # ------------------------------------------------------------------ Print

    @mcp.tool()
    async def print_stock_entry_label_tool(entry_id: int) -> str:
        """Trigger printing of a stock-entry label."""
        async with _get_client() as client:
            return await print_stock_entry_label(client, entry_id)

    @mcp.tool()
    async def print_product_label_tool(product: str) -> str:
        """Trigger printing of a product label."""
        async with _get_client() as client:
            return await print_product_label(client, product)

    @mcp.tool()
    async def print_recipe_label_tool(recipe: str) -> str:
        """Trigger printing of a recipe label."""
        async with _get_client() as client:
            return await print_recipe_label(client, recipe)

    @mcp.tool()
    async def print_chore_label_tool(chore: str) -> str:
        """Trigger printing of a chore label."""
        async with _get_client() as client:
            return await print_chore_label(client, chore)

    @mcp.tool()
    async def print_battery_label_tool(battery: str) -> str:
        """Trigger printing of a battery label."""
        async with _get_client() as client:
            return await print_battery_label(client, battery)

    @mcp.tool()
    async def print_shopping_list_thermal_tool() -> str:
        """Trigger thermal printing of the shopping list."""
        async with _get_client() as client:
            return await print_shopping_list_thermal(client)

    # --------------------------------------------------------------- Discover

    @mcp.tool()
    async def discover_candidates_tool(entity: str, query: str, limit: int = 10) -> list[dict]:
        """Search products, recipes, chores, locations, tasks, or supported metadata domains."""
        async with _get_client() as client:
            return await search_entity_candidates_data(client, entity, query, limit)

    @mcp.tool()
    async def describe_entity_tool(entity: str) -> dict:
        """Describe a Grocy entity and its discovered fields."""
        async with _get_client() as client:
            return await describe_entity_data(client, entity)

    @mcp.tool()
    async def discover_fields_tool(entity: str) -> dict:
        """Return discovered sample fields for a Grocy entity."""
        async with _get_client() as client:
            return await discover_entity_fields_data(client, entity)

    # --------------------------------------------------------------- Workflow

    @mcp.tool()
    async def workflow_match_products_preview_tool(items: str) -> list[dict]:
        """Preview product matches for normalized external items.

        Use this when an LLM or another client has already converted a receipt,
        chat message, or image into a normalized item list and you need Grocy
        product IDs before applying stock changes.

        Args:
            items: JSON array of normalized input items.
        """
        parsed_items = _parse_json_arg(items, "items")
        async with _get_client() as client:
            return await workflow_match_products_preview_data(client, parsed_items)

    @mcp.tool()
    async def workflow_stock_intake_preview_tool(items: str) -> list[dict]:
        """Preview Grocy stock additions for normalized external items.

        This uses the same matching contract as workflow_match_products_preview_tool,
        but is named for the common \"I bought these groceries\" workflow.

        Args:
            items: JSON array of normalized input items.
        """
        parsed_items = _parse_json_arg(items, "items")
        async with _get_client() as client:
            return await workflow_stock_intake_preview_data(client, parsed_items)

    @mcp.tool()
    async def workflow_stock_intake_apply_tool(items: str) -> dict:
        """Apply confirmed stock additions using explicit Grocy product IDs.

        Apply only confirmed IDs from a prior preview step. This tool does not
        resolve names implicitly.

        Args:
            items: JSON array of confirmed apply items. Each item requires
                ``product_id`` (int) and ``amount`` (float > 0). Optional fields
                passed through to the Grocy ``/stock/products/{productId}/add``
                endpoint:

                - ``price`` (float): price per stock quantity unit in configured currency
                - ``best_before_date`` (str, ISO date YYYY-MM-DD): due/expiry date; defaults to today if omitted
                - ``shopping_location_id`` (int): store where item was purchased
                - ``purchased_date`` (str, ISO date YYYY-MM-DD): date of purchase
                - ``note`` (str): free-text note for the stock entry
        """
        parsed_items = _parse_json_arg(items, "items")
        async with _get_client() as client:
            return await workflow_stock_intake_apply_data(client, parsed_items)

    @mcp.tool()
    async def workflow_shopping_reconcile_preview_tool(items: str, list_id: int = 1) -> list[dict]:
        """Preview shopping-list removals and amount updates after a purchase.

        Provide confirmed Grocy product IDs for what was purchased and this tool
        will propose explicit shopping-item actions without applying them.

        Args:
            items: JSON array of confirmed apply items, each with product_id and amount.
            list_id: Shopping list ID to reconcile against.
        """
        parsed_items = _parse_json_arg(items, "items")
        async with _get_client() as client:
            return await workflow_shopping_reconcile_preview_data(client, parsed_items, list_id)

    @mcp.tool()
    async def workflow_shopping_reconcile_apply_tool(actions: str) -> dict:
        """Apply explicit shopping-list reconciliation actions from a preview step.

        Args:
            actions: JSON array of action objects from workflow_shopping_reconcile_preview_tool.
        """
        parsed_actions = _parse_json_arg(actions, "actions")
        async with _get_client() as client:
            return await workflow_shopping_reconcile_apply_data(client, parsed_actions)

    # --------------------------------------------------------------- Userfields

    @mcp.tool()
    async def userfields_list_tool(entity: str) -> str:
        """List all custom userfield definitions for a Grocy entity.

        Userfields are custom fields you can add to any entity in Grocy.
        This lists the field definitions (name, type, caption) for all userfields
        on the given entity type.

        Args:
            entity: Entity name to list userfields for (e.g. "products", "chores",
                "batteries", "locations", "recipes", "tasks").
        """
        async with _get_client() as client:
            # Userfield definitions live in /objects/userfields filtered by entity
            fields = await client.get_objects("userfields", query=f"entity={entity}")
            if not fields:
                return f"No custom userfields defined for entity '{entity}'."
            lines = [f"Userfields for '{entity}':"]
            for f in fields:
                fid = f.get("id")
                name = f.get("name", "?")
                caption = f.get("caption", "")
                ftype = f.get("type", "?")
                lines.append(f"  [{fid}] {name} ({ftype})" + (f" — {caption}" if caption else ""))
            return "\n".join(lines)

    @mcp.tool()
    async def userfields_get_tool(entity: str, object_id: int) -> dict:
        """Get the custom userfield values for a specific object.

        Returns a dict of field-name → value for all userfields on the object.

        Args:
            entity: Entity name (e.g. "products", "chores", "batteries").
            object_id: Numeric ID of the object to read userfields from.
        """
        async with _get_client() as client:
            return await client.get_userfields(entity, object_id)

    @mcp.tool()
    async def userfields_set_tool(entity: str, object_id: int, fields: str) -> str:
        """Set custom userfield values on a specific object.

        Args:
            entity: Entity name (e.g. "products", "chores", "batteries").
            object_id: Numeric ID of the object to update.
            fields: JSON object of field-name → value pairs to set.
                Example: '{"who_uses": "james", "priority": "high"}'.
        """
        parsed_fields = _parse_json_arg(fields, "fields")
        async with _get_client() as client:
            await client.set_userfields(entity, object_id, parsed_fields)
            return f"Userfields updated for {entity} ID {object_id}."

    # -------------------------------------------------------- User profile & settings

    @mcp.tool()
    async def user_profile_tool() -> str:
        """Return the currently authenticated Grocy user's profile.

        Shows id, username, display name, first name, and last name.
        """
        async with _get_client() as client:
            user = await client.get_current_user()
            uid = user.get("id")
            username = user.get("username", "?")
            display = user.get("display_name") or ""
            first = user.get("first_name", "")
            last = user.get("last_name", "")
            full_name = f"{first} {last}".strip()
            parts = [f"Current user: [{uid}] {username}"]
            if full_name:
                parts.append(f"  Name: {full_name}")
            if display:
                parts.append(f"  Display name: {display}")
            return "\n".join(parts)

    @mcp.tool()
    async def user_settings_tool(key: str | None = None) -> str:
        """Read the current user's settings from Grocy.

        Returns all settings as key=value pairs, or a single setting if key is given.

        Args:
            key: Optional setting key to read (e.g. "night_mode_enabled"). If omitted,
                all settings are returned.
        """
        async with _get_client() as client:
            data = await client.get_user_settings(key)
            if key is not None:
                # Single setting returns {"value": ...}
                value = data.get("value") if isinstance(data, dict) else data
                return f"{key} = {value!r}"
            # All settings: dict of key → value
            if not data:
                return "No user settings found."
            lines = ["User settings:"]
            for k, v in sorted(data.items()):
                lines.append(f"  {k} = {v!r}")
            return "\n".join(lines)

    @mcp.tool()
    async def user_setting_set_tool(key: str, value: str) -> str:
        """Set a user setting key to a string value.

        Args:
            key: The setting key to set (e.g. "night_mode_enabled").
            value: The value to set (always a string; Grocy converts as needed).
        """
        async with _get_client() as client:
            await client.set_user_setting(key, value)
            return f"User setting '{key}' set to {value!r}."

    # ------------------------------------------------------------------ Users

    @mcp.tool()
    async def users_list_tool() -> str:
        """List all Grocy users with their IDs, usernames, and display names.

        Useful for looking up user IDs needed for chore assignment (assignment_config)
        or for identifying a user before updating their account.
        """
        async with _get_client() as client:
            users = await client.get_users()
            if not users:
                return "No users found."
            lines = ["Users:"]
            for u in users:
                uid = u.get("id")
                username = u.get("username", "?")
                display = u.get("display_name") or f"{u.get('first_name', '')} {u.get('last_name', '')}".strip()
                lines.append(f"  [{uid}] {username}" + (f" ({display})" if display else ""))
            return "\n".join(lines)

    @mcp.tool()
    async def user_update_tool(
        user_id: int,
        username: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
        password: str | None = None,
    ) -> str:
        """Edit a Grocy user account — change display name, username, or reset password.

        Fetches the current user first so unspecified fields are preserved.

        Args:
            user_id: Numeric user ID (from users_list_tool).
            username: New username (login name).
            first_name: New first name.
            last_name: New last name.
            password: New password — use this to reset a user's password.
        """
        async with _get_client() as client:
            users = await client.get_users()
            current = next((u for u in users if u.get("id") == user_id), None)
            if current is None:
                return f"User ID {user_id} not found."
            payload: dict = {
                "username": username if username is not None else current.get("username", ""),
                "first_name": first_name if first_name is not None else current.get("first_name", ""),
                "last_name": last_name if last_name is not None else current.get("last_name", ""),
            }
            if password is not None:
                payload["password"] = password
            await client.update_user(user_id, payload)
            changed = []
            if username is not None:
                changed.append(f"username → {username}")
            if first_name is not None or last_name is not None:
                changed.append("name updated")
            if password is not None:
                changed.append("password reset")
            return f"User {user_id} ({current.get('username')}) updated: {', '.join(changed) or 'no changes'}."

    # ----------------------------------------------------------------- System

    @mcp.tool()
    async def system_info_tool() -> str:
        """Show Grocy server version, PHP version, and SQLite version.

        Useful for verifying connectivity and checking compatibility.
        """
        async with _get_client() as client:
            return await system_info(client)

    @mcp.tool()
    async def system_api_docs_tool(endpoint_filter: str | None = None) -> str:
        """Retrieve the Grocy OpenAPI spec from this instance's /api/ endpoint.

        Returns the full OpenAPI JSON spec, optionally filtered to paths matching
        a substring. Use this to verify exact field names and types before
        implementing or modifying tools.

        Args:
            endpoint_filter: Optional substring to filter paths by (e.g. "add",
                "/stock/", "purchase"). If omitted, returns all paths.
        """
        import json

        async with _get_client() as client:
            spec = await client.get_api_spec()

        if endpoint_filter:
            paths = spec.get("paths", {})
            filtered = {
                path: methods
                for path, methods in paths.items()
                if endpoint_filter.lower() in path.lower()
            }
            return json.dumps({"paths": filtered}, indent=2)

        return json.dumps(spec, indent=2)

    @mcp.tool()
    async def entity_list_tool(entity: str) -> str:
        """List all objects of a Grocy entity type.

        This is a generic tool for browsing any Grocy data table.

        Args:
            entity: Entity type name. Common values: 'products', 'locations',
                    'product_groups', 'quantity_units', 'shopping_list',
                    'recipes', 'chores', 'batteries', 'tasks'.
        """
        async with _get_client() as client:
            return await entity_list(client, entity)

    @mcp.tool()
    async def entity_get_tool(entity: str, obj_id: int) -> dict:
        """Fetch the FULL field set of one Grocy entity object by ID.

        Unlike entity_list_tool (which shows only id + name) or describe_entity_tool
        (which only samples field names), this returns every column of a single
        object — including fields like min_stock_amount, default_consume_location_id,
        description, picture_file_name, shopping_location_id, and timestamps.

        Args:
            entity: Entity type name (e.g. 'products', 'locations', 'chores').
            obj_id: The object ID to fetch (use entity_list_tool to find IDs).
        """
        async with _get_client() as client:
            return await entity_get_data(client, entity, obj_id)

    @mcp.tool()
    async def entity_query_tool(
        entity: str, filters: str | None = None, fields: str | None = None
    ) -> list[dict]:
        """Query a Grocy entity with server-side filters, returning STRUCTURED rows.

        Maps each filter to a Grocy 'query[]=field=value' clause (filters are ANDed
        together server-side). Returns matching rows as JSON objects — not a
        human-readable string — so you can count, filter, or aggregate them
        programmatically. Examples: products where shopping_location_id=1, or
        products with no parent_product_id (filter value null/empty).

        Args:
            entity: Entity type name (e.g. 'products', 'product_barcodes').
            filters: Optional JSON object of {field: value} equality filters.
                Booleans become 1/0; null matches an empty/NULL value. Example:
                '{"shopping_location_id": 1}'. Omit to return all rows.
            fields: Optional JSON array of field names to project each row down to.
                Example: '["id", "name", "min_stock_amount"]'. Omit for full rows.
        """
        parsed_filters = _parse_json_arg(filters, "filters") if filters else None
        parsed_fields = _parse_json_arg(fields, "fields") if fields else None
        if parsed_filters is not None and not isinstance(parsed_filters, dict):
            raise GrocyValidationError("filters must be a JSON object of field/value pairs.")
        if parsed_fields is not None and not isinstance(parsed_fields, list):
            raise GrocyValidationError("fields must be a JSON array of field names.")
        async with _get_client() as client:
            return await entity_query_data(client, entity, parsed_filters, parsed_fields)

    @mcp.tool()
    async def entity_create_tool(entity: str, data: str) -> str:
        """Create a new object of any Grocy entity type.

        This is a low-level tool — prefer the domain-specific create tools
        (recipe_create_tool, chore_create_tool) when available.

        Args:
            entity: Entity type name (e.g. 'products', 'locations', 'tasks').
            data: JSON object with fields for the new entity. Required fields vary
                  by entity type. Example for products: '{"name": "Oat Milk"}'.
                  Example for locations: '{"name": "Pantry", "is_freezer": 0}'.
        """
        parsed_data = _parse_json_arg(data, "data")
        async with _get_client() as client:
            return await entity_manage(client, entity, "create", data=parsed_data or None)

    @mcp.tool()
    async def entity_update_tool(entity: str, obj_id: int, data: str) -> str:
        """Update an existing Grocy entity object by its ID.

        Only the fields provided in data are changed; other fields are left as-is.

        Args:
            entity: Entity type name (e.g. 'products', 'locations').
            obj_id: The object ID to update (use entity_list_tool to find IDs).
            data: JSON object with fields to update.
                  Example: '{"name": "Updated Name", "description": "New desc"}'.
        """
        parsed_data = _parse_json_arg(data, "data")
        async with _get_client() as client:
            return await entity_manage(client, entity, "update", obj_id=obj_id, data=parsed_data)

    @mcp.tool()
    async def entity_delete_tool(entity: str, obj_id: int) -> str:
        """Delete a Grocy entity object by its ID. This cannot be undone.

        Args:
            entity: Entity type name (e.g. 'products', 'locations').
            obj_id: The object ID to delete (use entity_list_tool to find IDs).
        """
        async with _get_client() as client:
            return await entity_manage(client, entity, "delete", obj_id=obj_id)

    # ------------------------------------------------------ Product pictures

    @mcp.tool()
    async def stock_product_picture_upload_tool(
        product_id: int,
        image_path: str,
        filename: str | None = None,
    ) -> dict:
        """Upload a product picture from disk and link it to a Grocy product.

        Reads the image file at *image_path*, uploads it to Grocy's
        ``productpictures`` file group, then updates the product's
        ``picture_file_name`` so it appears in the UI.

        Args:
            product_id: Numeric Grocy product ID.
            image_path: Absolute or relative path to a PNG or JPG file on disk.
            filename: Override the stored filename (default:
                ``product-{id}-{epoch}.{ext}`` derived from the source file).

        Returns:
            dict with ``product_id``, ``picture_file_name``,
            ``upload_status``, and ``link_status``.
        """
        async with _get_client() as client:
            return await stock_product_picture_upload(client, product_id, image_path, filename)

    # ------------------------------------------------------ External barcode lookup

    @mcp.tool()
    async def barcode_lookup_external_tool(
        barcode: str,
        source: str = "openfoodfacts",
    ) -> dict:
        """Look up a product by barcode in an external database.

        Useful for pre-populating name, brand, and category before creating
        a new product in Grocy. No data is written to Grocy — the caller
        decides what to do with the result.

        Supported sources:
        - ``openfoodfacts`` (default) — free, no API key, best for grocery products.
        - ``upcitemdb`` — trial tier (100 req/day), no API key, broader non-food coverage.

        Args:
            barcode: UPC / EAN / GTIN barcode string (e.g. ``"5000112637922"``).
            source: ``"openfoodfacts"`` or ``"upcitemdb"`` (default: ``"openfoodfacts"``).

        Returns:
            ``{found, source, barcode, name, brand, quantity_text,
            categories, image_url, nutriments, raw}``
        """
        return await barcode_lookup_external(barcode, source)

    return mcp


def main() -> None:
    """Entry point for the grocy-mcp MCP server."""
    parser = argparse.ArgumentParser(description="Grocy MCP server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default="stdio",
        help="Transport mechanism (default: stdio)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for streamable-http transport (default: 8000)",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Bind address for streamable-http transport (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--path",
        default="/mcp",
        help="MCP endpoint URL path (default: /mcp)",
    )
    args = parser.parse_args()

    server = create_mcp_server()

    if args.transport == "stdio":
        server.run(transport="stdio")
    else:
        server.run(
            transport="streamable-http",
            host=args.host,
            port=args.port,
            path=args.path,
            stateless_http=True,
        )
