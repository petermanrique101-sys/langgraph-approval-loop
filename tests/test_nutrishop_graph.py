"""The NutriShop scenario through the graph with a scripted model: the draft
passes under autonomous, the send cards, a denial's reason reaches the model."""

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

import approval_loop.scenarios.nutrishop as shop
from approval_loop.graph import build_graph
from tests.test_graph import scripted

CONFIG = {"configurable": {"thread_id": "reorder1"}}


def _point_workspace_at(tmp_path, monkeypatch):
    monkeypatch.setattr(shop, "DATA", tmp_path)
    monkeypatch.setattr(shop, "INVENTORY", tmp_path / "inventory.csv")
    monkeypatch.setattr(shop, "ORDERS", tmp_path / "orders")


def test_send_cards_after_autonomous_draft_and_denial_reason_lands(tmp_path, monkeypatch):
    _point_workspace_at(tmp_path, monkeypatch)
    draft = AIMessage(content="", tool_calls=[{
        "name": "draft_purchase_order", "id": "c1",
        "args": {"supplier": "Optimum", "lines": [{"sku": "WHEY-CHOC-5LB", "qty": 12}]},
    }])
    graph = build_graph(model=scripted(draft, AIMessage("drafted")), checkpointer=InMemorySaver(), scenario=shop.SCENARIO)
    result = graph.invoke({"messages": [HumanMessage("restock")], "profile": "autonomous", "pending": [], "approvals": []}, CONFIG)
    draft_msg = next(m for m in result["messages"] if isinstance(m, ToolMessage))
    assert draft_msg.content.endswith("1 lines, total $528.00")
    po_id = draft_msg.content.split()[0]
    assert (tmp_path / "orders" / f"{po_id}.json").exists()
    assert "__interrupt__" not in result  # autonomous: the draft went through without a card

    send = AIMessage(content="", tool_calls=[{"name": "send_purchase_order", "id": "c2", "args": {"po_id": po_id}}])
    graph2 = build_graph(model=scripted(send, AIMessage("holding the order")),
                         checkpointer=graph.checkpointer, scenario=shop.SCENARIO)
    result = graph2.invoke({"messages": [HumanMessage("now send it")]}, CONFIG)
    card = result["__interrupt__"][0].value
    assert card["tool"] == "send_purchase_order"
    assert card["reason"] == "irreversible: commits the store to paying the supplier"
    assert card["question"] == (f"Send {po_id} to Optimum for $528.00? "
                                "Items: 12 x Whey Protein Chocolate 5lb. Once sent, the store owes the supplier.")

    final = graph2.invoke(Command(resume="no, wait for Friday's cash"), CONFIG)
    denial = [m for m in final["messages"] if isinstance(m, ToolMessage)][-1]
    assert denial.content == "Denied by the user: wait for Friday's cash"
    assert (tmp_path / "orders" / f"{po_id}.json").read_text().count('"status": "draft"') == 1



def test_find_low_stock_returns_only_items_at_or_below_reorder_point(tmp_path, monkeypatch):
    _point_workspace_at(tmp_path, monkeypatch)
    plan = shop.low_stock()
    assert plan == {
        "Optimum": [{"sku": "WHEY-CHOC-5LB", "name": "Whey Protein Chocolate 5lb", "qty": 12}],
        "Ghost": [{"sku": "PREW-BLUE-30", "name": "Pre-Workout Blue Razz 30srv", "qty": 10}],
        "NOW": [{"sku": "FISH-OIL-120", "name": "Fish Oil 1000mg 120ct", "qty": 18}],
    }  # creatine (14 > 8) and multivitamin (9 > 4) are not low
    assert "CREA-MONO-500" not in shop.find_low_stock.invoke({})
    assert "MULTI-MEN-90" not in shop.find_low_stock.invoke({})


def test_find_low_stock_includes_item_exactly_at_reorder_point(tmp_path, monkeypatch):
    _point_workspace_at(tmp_path, monkeypatch)
    shop.seed()
    text = shop.INVENTORY.read_text(encoding="utf-8").replace("CREA-MONO-500,Creatine Monohydrate 500g,14,", "CREA-MONO-500,Creatine Monohydrate 500g,8,")
    shop.INVENTORY.write_text(text, encoding="utf-8")
    assert {"sku": "CREA-MONO-500", "name": "Creatine Monohydrate 500g", "qty": 24} in shop.low_stock()["Optimum"]


def test_find_low_stock_when_nothing_is_low(tmp_path, monkeypatch):
    _point_workspace_at(tmp_path, monkeypatch)
    shop.DATA.mkdir(parents=True, exist_ok=True)
    shop.INVENTORY.write_text("sku,name,on_hand,reorder_at,reorder_qty,supplier,unit_cost\nX,Thing,10,2,5,Acme,1.0\n", encoding="utf-8")
    assert shop.find_low_stock.invoke({}) == "Nothing is at or below its reorder point. No orders needed."