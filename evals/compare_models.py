"""Run the NutriShop restock end to end on real models and score each run.

    python evals/compare_models.py anthropic:claude-sonnet-5 anthropic:claude-haiku-4-5 --runs 5

Each run uses a fresh scratch workspace and answers the cards the same way:
yes to Optimum and NOW, no with a reason to Ghost. A run passes only if all
of these hold:
  - exactly three POs drafted, one per low supplier, with exactly the low items
  - exactly three send cards, one per PO
  - Optimum and NOW end sent, Ghost ends draft
  - the final message carries the Ghost reason (verbatim or paraphrased:
    it mentions the price rise or the call)
Cost is estimated from the token counts the API returns.
"""

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

PRICES = {"claude-sonnet-5": (2.0, 10.0), "claude-haiku-4-5": (1.0, 5.0), "claude-opus-5-5": (4.0, 20.0)}
EXPECTED = {
    "Optimum": [{"sku": "WHEY-CHOC-5LB", "qty": 12}],
    "Ghost": [{"sku": "PREW-BLUE-30", "qty": 10}],
    "NOW": [{"sku": "FISH-OIL-120", "qty": 18}],
}
GHOST_REASON = "Ghost raised prices last month, hold that one until I call them"


def run_once(model_id: str, n: int) -> dict:
    os.environ["WORKSPACE"] = tempfile.mkdtemp()
    for mod in [m for m in sys.modules if m.startswith("approval_loop")]:
        del sys.modules[mod]  # WORKSPACE is read at import time
    from langchain.chat_models import init_chat_model
    from langchain_core.messages import AIMessage, HumanMessage
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.types import Command
    from approval_loop.graph import build_graph
    from approval_loop.scenarios import load
    import approval_loop.scenarios.nutrishop as shop

    graph = build_graph(model=init_chat_model(model_id), checkpointer=InMemorySaver(), scenario=load("nutrishop"))
    short = model_id.split(":")[-1]
    cfg = {"configurable": {"thread_id": f"{short}-{n}"}, "run_name": f"nutrishop-eval-{short}",
           "tags": ["model-eval", short]}
    result = graph.invoke({"messages": [HumanMessage("restock whatever is low")], "profile": "autonomous",
                           "pending": [], "approvals": []}, cfg)
    cards = []
    while "__interrupt__" in result and len(cards) < 6:
        question = result["__interrupt__"][0].value["question"]
        cards.append(question)
        answer = f"no, {GHOST_REASON}" if "Ghost" in question else "yes"
        result = graph.invoke(Command(resume=answer), cfg)

    pos = [json.loads(p.read_text()) for p in sorted(shop.ORDERS.glob("*.json"))] if shop.ORDERS.exists() else []
    by_supplier = {po["supplier"]: po for po in pos}
    ai = [m for m in result["messages"] if isinstance(m, AIMessage)]
    tin = sum((m.usage_metadata or {}).get("input_tokens", 0) for m in ai)
    tout = sum((m.usage_metadata or {}).get("output_tokens", 0) for m in ai)
    pin, pout = PRICES.get(short, (0.0, 0.0))
    final = ai[-1].content if ai and isinstance(ai[-1].content, str) else str(ai[-1].content if ai else "")

    failures = []
    if len(pos) != 3 or set(by_supplier) != set(EXPECTED):
        failures.append(f"drafted {len(pos)} POs for {sorted(by_supplier)}")
    for supplier, lines in EXPECTED.items():
        got = by_supplier.get(supplier, {}).get("lines")
        if got is not None and sorted((l["sku"], int(l["qty"])) for l in got) != sorted((l["sku"], l["qty"]) for l in lines):
            failures.append(f"{supplier} lines wrong: {got}")
    if len(cards) != 3:
        failures.append(f"{len(cards)} send cards")
    want = {"Optimum": "sent", "NOW": "sent", "Ghost": "draft"}
    for supplier, status in want.items():
        if supplier in by_supplier and by_supplier[supplier]["status"] != status:
            failures.append(f"{supplier} ended {by_supplier[supplier]['status']}")
    if not any(k in final.lower() for k in ("pric", "call them", "call ghost")):
        failures.append("summary missing the Ghost reason")
    return {"pass": not failures, "failures": failures, "calls": len(ai), "in": tin, "out": tout,
            "usd": tin * pin / 1e6 + tout * pout / 1e6, "final": final}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("models", nargs="+")
    parser.add_argument("--runs", type=int, default=5)
    args = parser.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    rows = []
    for model_id in args.models:
        runs = []
        for n in range(1, args.runs + 1):
            try:
                r = run_once(model_id, n)
            except Exception as exc:  # a crashed run is a failed run, reported, not hidden
                r = {"pass": False, "failures": [f"crashed: {type(exc).__name__}: {exc}"], "calls": 0, "in": 0, "out": 0, "usd": 0.0}
            runs.append(r)
            print(f"{model_id} run {n}: {'PASS' if r['pass'] else 'FAIL ' + '; '.join(r['failures'])} "
                  f"({r['calls']} calls, {r['in']} in / {r['out']} out, ${r['usd']:.4f})", flush=True)
            if not r["pass"] and r.get("final"):
                print("  final message:\n    " + r["final"].replace("\n", "\n    "), flush=True)
        passed = sum(r["pass"] for r in runs)
        avg = sum(r["usd"] for r in runs) / len(runs)
        rows.append((model_id, passed, len(runs), avg))
    print("\nmodel | passed | avg $/run")
    for model_id, passed, total, avg in rows:
        print(f"{model_id} | {passed}/{total} | ${avg:.4f}")


if __name__ == "__main__":
    main()
