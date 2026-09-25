"""A supplement store's reorder agent.

Reading stock is free. Drafting a purchase order is gated (the owner may run
autonomous and let drafts through). Sending one to the supplier commits money,
so it sits on the irreversible floor: it always cards, and approving one PO
never approves a different one.
"""

import csv
import json
from datetime import date
from pathlib import Path

from langchain.tools import tool

from ..policy import Rules
from ..tools import WORKSPACE
from . import Scenario

DATA = WORKSPACE / "nutrishop"
INVENTORY = DATA / "inventory.csv"
ORDERS = DATA / "orders"

SEED_INVENTORY = [
    {"sku": "WHEY-CHOC-5LB", "name": "Whey Protein Chocolate 5lb", "on_hand": 3, "reorder_at": 6, "reorder_qty": 12, "supplier": "Optimum", "unit_cost": 44.00},
    {"sku": "CREA-MONO-500", "name": "Creatine Monohydrate 500g", "on_hand": 14, "reorder_at": 8, "reorder_qty": 24, "supplier": "Optimum", "unit_cost": 18.50},
    {"sku": "PREW-BLUE-30", "name": "Pre-Workout Blue Razz 30srv", "on_hand": 2, "reorder_at": 5, "reorder_qty": 10, "supplier": "Ghost", "unit_cost": 27.00},
    {"sku": "MULTI-MEN-90", "name": "Men's Multivitamin 90ct", "on_hand": 9, "reorder_at": 4, "reorder_qty": 12, "supplier": "NOW", "unit_cost": 12.25},
    {"sku": "FISH-OIL-120", "name": "Fish Oil 1000mg 120ct", "on_hand": 1, "reorder_at": 6, "reorder_qty": 18, "supplier": "NOW", "unit_cost": 9.80},
]


def seed() -> None:
    """Write the sample inventory if none exists. Idempotent."""
    if INVENTORY.exists():
        return
    DATA.mkdir(parents=True, exist_ok=True)
    with INVENTORY.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(SEED_INVENTORY[0]))
        writer.writeheader()
        writer.writerows(SEED_INVENTORY)


@tool
def read_inventory() -> str:
    """Current stock levels: sku, name, on_hand, reorder_at, reorder_qty, supplier, unit_cost."""
    seed()
    return INVENTORY.read_text(encoding="utf-8")


def low_stock() -> dict[str, list[dict]]:
    """Items at or below their reorder point, grouped by supplier, at their reorder quantity."""
    seed()
    plan: dict[str, list[dict]] = {}
    for row in csv.DictReader(INVENTORY.open(encoding="utf-8")):
        if int(row["on_hand"]) <= int(row["reorder_at"]):
            plan.setdefault(row["supplier"], []).append(
                {"sku": row["sku"], "name": row["name"], "qty": int(row["reorder_qty"])})
    return plan


@tool
def find_low_stock() -> str:
    """What to reorder right now: items at or below their reorder point, grouped by supplier,
    each with the exact quantity to order. Draft one PO per supplier with exactly these lines."""
    plan = low_stock()
    if not plan:
        return "Nothing is at or below its reorder point. No orders needed."
    return json.dumps(
        [{"supplier": s, "lines": [{"sku": l["sku"], "qty": l["qty"]} for l in lines],
          "items": [f"{l['qty']} x {l['name']}" for l in lines]} for s, lines in plan.items()],
        indent=2)


@tool
def draft_purchase_order(supplier: str, lines: list[dict]) -> str:
    """Write a draft PO for one supplier. `lines` is a list of {"sku": str, "qty": int}. Returns the PO id and total."""
    seed()
    costs = {row["sku"]: float(row["unit_cost"]) for row in csv.DictReader(INVENTORY.open(encoding="utf-8"))}
    total = sum(costs[line["sku"]] * int(line["qty"]) for line in lines)
    ORDERS.mkdir(parents=True, exist_ok=True)
    po_id = f"PO-{date.today():%Y%m%d}-{supplier.upper()[:3]}-{len(list(ORDERS.glob('*.json'))) + 1:03d}"
    (ORDERS / f"{po_id}.json").write_text(
        json.dumps({"id": po_id, "supplier": supplier, "lines": lines, "total": round(total, 2), "status": "draft"}, indent=2),
        encoding="utf-8",
    )
    return f"{po_id} drafted for {supplier}: {len(lines)} lines, total ${total:,.2f}"


@tool
def send_purchase_order(po_id: str) -> str:
    """Send a drafted PO to the supplier. This commits the store to paying for it."""
    path = ORDERS / f"{po_id}.json"
    po = json.loads(path.read_text(encoding="utf-8"))
    po["status"] = "sent"
    path.write_text(json.dumps(po, indent=2), encoding="utf-8")
    return f"{po_id} sent to {po['supplier']} for ${po['total']:,.2f}"


def _names() -> dict[str, str]:
    if not INVENTORY.exists():
        return {}
    return {row["sku"]: row["name"] for row in csv.DictReader(INVENTORY.open(encoding="utf-8"))}


def _items(lines: list[dict]) -> str:
    names = _names()
    return ", ".join(f"{line.get('qty')} x {names.get(line.get('sku'), line.get('sku'))}" for line in lines)


def describe(tool_name: str, args: dict) -> str:
    if tool_name == "send_purchase_order":
        po_id = args.get("po_id", "?")
        path = ORDERS / f"{po_id}.json"
        if not path.exists():
            return f"Send {po_id}? (No draft with that number exists; sending will fail.)"
        po = json.loads(path.read_text(encoding="utf-8"))
        return (f"Send {po_id} to {po['supplier']} for ${po['total']:,.2f}? "
                f"Items: {_items(po['lines'])}. Once sent, the store owes the supplier.")
    if tool_name == "draft_purchase_order":
        return f"Draft a purchase order to {args.get('supplier', '?')} for {_items(args.get('lines', []))}? Nothing is sent yet."
    return f"Run {tool_name}?"


SCENARIO = Scenario(
    name="nutrishop",
    system_prompt=(
        "You are the reorder assistant for NutriShop, a supplement store. To restock: "
        "1) call find_low_stock; it returns exactly what to order, do not add or change items or quantities. "
        "2) draft one purchase order per supplier with those lines. "
        "3) send each drafted PO by calling send_purchase_order. The owner approves or denies each send "
        "on an approval card, so do not ask for permission in chat; just call the tool. "
        "If a send is denied, read the reason in the tool result, leave that PO as a draft, and do not retry it. "
        "4) finish with a short summary table: supplier, PO, items, total, status. "
        "For any PO the owner held, put the owner's reason in its status. "
        "Use read_inventory only to answer questions about stock levels."
    ),
    tools=[find_low_stock, read_inventory, draft_purchase_order, send_purchase_order],
    rules=Rules(
        gated={"draft_purchase_order": "writes a purchase order"},
        irreversible={"send_purchase_order": "commits the store to paying the supplier"},
    ),
    describe=describe,
)
