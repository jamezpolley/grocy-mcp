"""Core stock management functions for Grocy."""

from __future__ import annotations

import asyncio

from grocy_mcp.client import GrocyClient
from grocy_mcp.core.resolve import resolve_location, resolve_product


async def stock_overview(client: GrocyClient) -> str:
    """Return a formatted overview of current stock."""
    items = await client.get_stock()
    if not items:
        return "No stock found."
    lines = ["Current stock:"]
    for item in items:
        product = item.get("product") or {}
        name = product.get("name", f"Product {item.get('product_id')}")
        amount = item.get("amount", 0)
        lines.append(f"  [{item.get('product_id', '?')}] {name} — {amount}")
    return "\n".join(lines)


async def stock_expiring(client: GrocyClient) -> str:
    """Return products that are expiring soon or already expired."""
    volatile = await client.get_volatile_stock()
    expiring = volatile.get("expiring_products", [])
    expired = volatile.get("expired_products", [])
    missing = volatile.get("missing_products", [])

    lines = []

    if expiring:
        lines.append("Expiring soon:")
        for item in expiring:
            product = item.get("product") or {}
            name = product.get("name", f"Product {item.get('product_id')}")
            lines.append(f"  {name}")

    if expired:
        lines.append("Expired:")
        for item in expired:
            product = item.get("product") or {}
            name = product.get("name", f"Product {item.get('product_id')}")
            lines.append(f"  {name}")

    if missing:
        lines.append("Missing (below min stock):")
        for item in missing:
            product = item.get("product") or {}
            name = product.get("name", f"Product {item.get('product_id')}")
            lines.append(f"  {name}")

    if not lines:
        return "No expiring, expired, or missing products found."

    return "\n".join(lines)


async def stock_product_info(client: GrocyClient, product: str) -> str:
    """Return detailed stock information for a specific product."""
    product_id = await resolve_product(client, product)
    info = await client.get_stock_product(product_id)

    product_data = info.get("product") or {}
    name = product_data.get("name", f"Product {product_id}")
    amount = info.get("stock_amount", 0)
    best_before = info.get("next_best_before_date", "unknown")

    return f"Product: {name}\n  In stock: {amount}\n  Next best before: {best_before}"


def _resolve_qu(info: dict, role: str) -> dict | None:
    """Extract a resolved QU object by role from a stock product response.

    Roles: 'stock' → quantity_unit_stock, 'purchase' → default_quantity_unit_purchase,
           'consume' → default_quantity_unit_consume, 'price' → quantity_unit_price.
    """
    key_map = {
        "stock": "quantity_unit_stock",
        "purchase": "default_quantity_unit_purchase",
        "consume": "default_quantity_unit_consume",
        "price": "quantity_unit_price",
    }
    key = key_map.get(role)
    if not key:
        return None
    qu = info.get(key)
    if not qu:
        return None
    return {"id": qu.get("id"), "name": qu.get("name"), "name_plural": qu.get("name_plural")}


async def stock_product_full_data(client: GrocyClient, product: str) -> dict:
    """Return a comprehensive dict for a single product in one call.

    Aggregates product fields, resolved names for all FK references, current stock
    totals, all product-specific quantity-unit conversions, and all product barcodes
    (with resolved QU and shopping-location names).

    Stock journal / history entries are intentionally excluded — use
    ``stock_journal_tool`` when history is needed.

    Response shape::

        {
          "product": {<full product object from /objects/products>},
          "stock": {
            "amount": float,
            "amount_opened": float,
            "amount_aggregated": float,
            "amount_opened_aggregated": float,
            "value": float,
            "last_purchased": str | None,
            "last_used": str | None,
            "last_price": float | None,
            "avg_price": float | None,
            "next_due_date": str | None,
          },
          "units": {
            "stock":    {"id": int, "name": str, "name_plural": str} | None,
            "purchase": {"id": int, "name": str, "name_plural": str} | None,
            "consume":  {"id": int, "name": str, "name_plural": str} | None,
            "price":    {"id": int, "name": str, "name_plural": str} | None,
          },
          "location": {"id": int, "name": str} | None,
          "shopping_location": {"id": int, "name": str} | None,
          "product_group": {"id": int, "name": str} | None,
          "parent_product": {"id": int, "name": str} | None,
          "barcodes": [
            {
              "id": int, "barcode": str, "amount": float | None,
              "last_price": float | None, "note": str | None,
              "qu": {"id": int, "name": str} | None,
              "shopping_location": {"id": int, "name": str} | None,
            }, ...
          ],
          "conversions": [
            {
              "id": int, "factor": float,
              "from_qu": {"id": int, "name": str},
              "to_qu":   {"id": int, "name": str},
            }, ...
          ],
        }

    Args:
        product: Product name (e.g. "Milk") or numeric product ID.
    """
    product_id = await resolve_product(client, product)

    # Fetch stock details and product-specific QU conversions in parallel.
    # Barcodes are already embedded in the stock/products/{id} response.
    info, conversions_raw = await asyncio.gather(
        client.get_stock_product(product_id),
        client.get_objects("quantity_unit_conversions", query=f"product_id={product_id}"),
    )

    product_data = info.get("product") or {}

    # ── Stock totals ──────────────────────────────────────────────────────────
    stock = {
        "amount": info.get("stock_amount"),
        "amount_opened": info.get("stock_amount_opened"),
        "amount_aggregated": info.get("stock_amount_aggregated"),
        "amount_opened_aggregated": info.get("stock_amount_opened_aggregated"),
        "value": info.get("stock_value"),
        "last_purchased": info.get("last_purchased"),
        "last_used": info.get("last_used"),
        "last_price": info.get("last_price"),
        "avg_price": info.get("avg_price"),
        "next_due_date": info.get("next_due_date"),
    }

    # ── Resolved QU roles ─────────────────────────────────────────────────────
    units = {
        "stock": _resolve_qu(info, "stock"),
        "purchase": _resolve_qu(info, "purchase"),
        "consume": _resolve_qu(info, "consume"),
        "price": _resolve_qu(info, "price"),
    }

    # ── Location ──────────────────────────────────────────────────────────────
    loc_raw = info.get("location")
    location = {"id": loc_raw["id"], "name": loc_raw["name"]} if loc_raw else None

    # ── Shopping location (product default) ───────────────────────────────────
    # The stock response embeds the last-used shopping location id but not the
    # product-default one.  Resolve the product's shopping_location_id if set.
    shopping_location: dict | None = None
    sl_id = product_data.get("shopping_location_id")
    if sl_id:
        try:
            sl_raw = await client.get_object("shopping_locations", sl_id)
            shopping_location = {"id": sl_raw["id"], "name": sl_raw["name"]}
        except Exception:
            shopping_location = {"id": sl_id, "name": None}

    # ── Product group ─────────────────────────────────────────────────────────
    product_group: dict | None = None
    pg_id = product_data.get("product_group_id")
    if pg_id:
        try:
            pg_raw = await client.get_object("product_groups", pg_id)
            product_group = {"id": pg_raw["id"], "name": pg_raw["name"]}
        except Exception:
            product_group = {"id": pg_id, "name": None}

    # ── Parent product ────────────────────────────────────────────────────────
    parent_product: dict | None = None
    pp_id = product_data.get("parent_product_id")
    if pp_id:
        try:
            pp_raw = await client.get_object("products", pp_id)
            parent_product = {"id": pp_raw["id"], "name": pp_raw["name"]}
        except Exception:
            parent_product = {"id": pp_id, "name": None}

    # ── Barcodes (already embedded in the stock response) ────────────────────
    # Build a QU id→name lookup from the four embedded QU objects to avoid
    # extra round-trips when resolving barcode QU names.
    qu_lookup: dict[int, str] = {}
    for role_key in ("quantity_unit_stock", "default_quantity_unit_purchase",
                     "default_quantity_unit_consume", "quantity_unit_price"):
        qu_obj = info.get(role_key) or {}
        if qu_obj.get("id"):
            qu_lookup[qu_obj["id"]] = qu_obj.get("name", "")

    barcodes = []
    for bc in info.get("product_barcodes") or []:
        qu_id = bc.get("qu_id")
        bc_qu = {"id": qu_id, "name": qu_lookup.get(qu_id)} if qu_id else None
        sl_bc_id = bc.get("shopping_location_id")
        bc_sl: dict | None = None
        if sl_bc_id:
            # Reuse the product-default shopping location dict if the id matches
            if shopping_location and shopping_location["id"] == sl_bc_id:
                bc_sl = shopping_location
            else:
                try:
                    sl_bc_raw = await client.get_object("shopping_locations", sl_bc_id)
                    bc_sl = {"id": sl_bc_raw["id"], "name": sl_bc_raw["name"]}
                except Exception:
                    bc_sl = {"id": sl_bc_id, "name": None}
        barcodes.append({
            "id": bc.get("id"),
            "barcode": bc.get("barcode"),
            "amount": bc.get("amount"),
            "last_price": bc.get("last_price"),
            "note": bc.get("note"),
            "qu": bc_qu,
            "shopping_location": bc_sl,
        })

    # ── QU conversions (product-specific only) ────────────────────────────────
    conversions = []
    for cv in conversions_raw:
        from_id = cv.get("from_qu_id")
        to_id = cv.get("to_qu_id")
        conversions.append({
            "id": cv.get("id"),
            "factor": cv.get("factor"),
            "from_qu": {"id": from_id, "name": qu_lookup.get(from_id)},
            "to_qu": {"id": to_id, "name": qu_lookup.get(to_id)},
        })

    return {
        "product": product_data,
        "stock": stock,
        "units": units,
        "location": location,
        "shopping_location": shopping_location,
        "product_group": product_group,
        "parent_product": parent_product,
        "barcodes": barcodes,
        "conversions": conversions,
    }


def _is_parent_flag(value) -> bool:
    """Coerce Grocy's 0/1/"0"/"1"/bool flag fields to a real bool."""
    return value in (1, "1", True)


async def product_family_data(client: GrocyClient, product: str) -> dict:
    """Resolve a product's parent/child family and aggregated stock in one call.

    Grocy models product variants with ``parent_product_id``: a "parent" product
    (e.g. "Laundry liquid") groups its concrete child products (e.g. "Omo Speed
    Clean 1.18L"). Parents often carry ``no_own_stock=1`` and
    ``cumulate_min_stock_amount_of_sub_products=1`` — their real stock lives in the
    children and surfaces on the parent as ``amount_aggregated``.

    This helper works from either end: given a parent OR a child (by name or id),
    it resolves up to the family root (the parent, or the product itself if it has
    no parent) and returns the root plus every child, each with its current stock
    amount and unit, alongside the root's aggregated totals.

    Response shape::

        {
          "root": {
            "id": int,
            "name": str,
            "is_parent": bool,                 # has children OR no_own_stock set
            "no_own_stock": bool,
            "cumulate_min_stock_amount_of_sub_products": bool,
            "min_stock_amount": float,
            "stock_unit": {"id": int, "name": str, "name_plural": str} | None,
            "amount": float,                   # root's own stock (often 0 for parents)
            "amount_opened": float,
            "amount_aggregated": float,        # root + all children
            "amount_opened_aggregated": float,
          },
          "queried": {"id": int, "name": str, "was_child": bool},
          "children": [
            {
              "id": int,
              "name": str,
              "amount": float,                 # current stock for this child
              "unit": {"id": int, "name": str, "name_plural": str} | None,
              "min_stock_amount": float,
            }, ...
          ],
        }

    Args:
        product: Product name (e.g. "Laundry liquid" or "Omo Speed Clean 1.18L")
            or numeric product ID. May be a parent or a child.
    """
    queried_id = await resolve_product(client, product)

    # Pull the queried product's full object (gives parent_product_id + flags),
    # the global stock snapshot (amount per in-stock product_id), and the unit
    # table (to name child units without N extra round-trips), in parallel.
    queried_info, stock_items, units_raw = await asyncio.gather(
        client.get_stock_product(queried_id),
        client.get_stock(),
        client.get_objects("quantity_units"),
    )
    queried_product = queried_info.get("product") or {}
    queried_name = queried_product.get("name", f"Product {queried_id}")

    # Build amount lookups from the stock snapshot (products with zero stock are
    # absent from /stock, so default to 0).
    amount_by_pid: dict[int, float] = {}
    opened_by_pid: dict[int, float] = {}
    for item in stock_items:
        pid = item.get("product_id")
        if pid is None:
            continue
        amount_by_pid[pid] = item.get("amount", 0) or 0
        opened_by_pid[pid] = item.get("amount_opened", 0) or 0

    # Unit id → unit dict lookup.
    unit_by_id: dict[int, dict] = {
        u["id"]: {"id": u["id"], "name": u.get("name"), "name_plural": u.get("name_plural")}
        for u in units_raw
        if u.get("id") is not None
    }

    # Resolve the family root: the parent if this is a child, else self.
    parent_id = queried_product.get("parent_product_id")
    was_child = bool(parent_id)
    if was_child:
        root_info = await client.get_stock_product(int(parent_id))
        root_product = root_info.get("product") or {}
    else:
        root_info = queried_info
        root_product = queried_product
    root_id = root_product.get("id", queried_id)

    # Children: every product whose parent_product_id == root_id.
    children_raw = await client.get_objects(
        "products", query=f"parent_product_id={root_id}"
    )

    children = []
    for c in children_raw:
        cid = c.get("id")
        qu_id = c.get("qu_id_stock")
        children.append({
            "id": cid,
            "name": c.get("name"),
            "amount": amount_by_pid.get(cid, 0),
            "unit": unit_by_id.get(qu_id) if qu_id else None,
            "min_stock_amount": c.get("min_stock_amount", 0),
        })

    root_qu_id = root_product.get("qu_id_stock")
    root = {
        "id": root_id,
        "name": root_product.get("name", f"Product {root_id}"),
        "is_parent": bool(children) or _is_parent_flag(root_product.get("no_own_stock")),
        "no_own_stock": _is_parent_flag(root_product.get("no_own_stock")),
        "cumulate_min_stock_amount_of_sub_products": _is_parent_flag(
            root_product.get("cumulate_min_stock_amount_of_sub_products")
        ),
        "min_stock_amount": root_product.get("min_stock_amount", 0),
        "stock_unit": unit_by_id.get(root_qu_id) if root_qu_id else None,
        "amount": root_info.get("stock_amount"),
        "amount_opened": root_info.get("stock_amount_opened"),
        "amount_aggregated": root_info.get("stock_amount_aggregated"),
        "amount_opened_aggregated": root_info.get("stock_amount_opened_aggregated"),
    }

    return {
        "root": root,
        "queried": {"id": queried_id, "name": queried_name, "was_child": was_child},
        "children": children,
    }


async def stock_add(client: GrocyClient, product: str, amount: float, **kwargs) -> str:
    """Add stock for a product."""
    product_id = await resolve_product(client, product)
    await client.add_stock(product_id, amount, **kwargs)
    return f"Added {amount} of '{product}' to stock."


async def stock_consume(client: GrocyClient, product: str, amount: float, **kwargs) -> str:
    """Consume stock for a product."""
    product_id = await resolve_product(client, product)
    await client.consume_stock(product_id, amount, **kwargs)
    return f"Consumed {amount} of '{product}' from stock."


async def stock_transfer(client: GrocyClient, product: str, amount: float, to_location: str) -> str:
    """Transfer stock to a different location."""
    product_id = await resolve_product(client, product)
    location_id = await resolve_location(client, to_location)
    await client.transfer_stock(product_id, amount, location_id)
    return f"Transferred {amount} of '{product}' to location '{to_location}'."


async def stock_inventory(client: GrocyClient, product: str, new_amount: float) -> str:
    """Set the stock amount for a product via inventory."""
    product_id = await resolve_product(client, product)
    await client.inventory_stock(product_id, new_amount)
    return f"Inventory updated: '{product}' set to {new_amount}."


async def stock_open(client: GrocyClient, product: str, amount: float = 1.0) -> str:
    """Mark stock as opened for a product."""
    product_id = await resolve_product(client, product)
    await client.open_stock(product_id, amount)
    return f"Opened {amount} of '{product}'."


async def stock_search(client: GrocyClient, query: str) -> str:
    """Search for products by name or barcode."""
    products = await client.get_objects("products")
    query_lower = query.lower()
    matches = [p for p in products if query_lower in p.get("name", "").lower()]

    barcodes = await client.get_objects("product_barcodes")
    barcode_ids = {b["product_id"] for b in barcodes if query_lower in b.get("barcode", "").lower()}
    for p in products:
        if p["id"] in barcode_ids and p not in matches:
            matches.append(p)

    if not matches:
        return f"No products found matching '{query}'."

    lines = [f"Products matching '{query}':"]
    for p in matches:
        lines.append(f"  [{p['id']}] {p.get('name', '?')}")
    return "\n".join(lines)


async def stock_barcode_lookup(client: GrocyClient, barcode: str) -> str:
    """Look up stock information by barcode."""
    info = await client.get_stock_by_barcode(barcode)
    product = info.get("product") or {}
    name = product.get("name", f"Barcode {barcode}")
    amount = info.get("stock_amount", 0)
    return f"Barcode {barcode}: {name} — {amount} in stock."
