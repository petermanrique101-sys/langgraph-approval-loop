# Recording the demo

Two clips, about thirty seconds each. Terminal first, Studio second.

## Before you start

```powershell
cd C:\Users\peter\langgraph-approval-loop
.venv\Scripts\Activate.ps1
Remove-Item checkpoints.db*, workspace\nutrishop -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force workspace\build | Out-Null; "junk" | Set-Content workspace\build\out.o
```

`MODEL`, `ANTHROPIC_API_KEY` and the three `LANGSMITH_*` variables (`LANGSMITH_TRACING=true`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT=approval-loop`) must be set at User scope. Open a fresh terminal after setting them so it sees them.

## Clip 1: kill and resume (terminal)

```powershell
python run.py --thread demo1 "delete the build directory in the workspace using bash"
```

Wait for the card. Press **Ctrl-C**. Then:

```powershell
python run.py --thread demo1 --resume
```

Same card, same fingerprint. Type `y`, Enter. The model finishes.

Optional second take for the negative: a new thread, `n`, and a reason like `keep the cache`. The final message should repeat the reason.

## Clip 2: NutriShop in Studio

```powershell
langgraph dev
```

It opens `https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024`. Pick the **nutrishop** graph (check the dropdown next to "Studio /"; the dev graph draws the same boxes). In the input panel set `profile` to `autonomous`, add a human message `restock whatever is low`, and submit. Watch `call_model → policy → execute` run for the drafts, then the graph stop at `approve`. The card's `question` reads in plain English, e.g. "Send PO-…-OPT-001 to Optimum for $528.00? Items: 12 x Whey Protein Chocolate 5lb. Once sent, the store owes the supplier." Type the answer in the "Provide a value to resume" box on the right (replace the `""`) and click **Resume**, not Submit: `yes` for Optimum, `no, Ghost raised prices last month, hold that one until I call them` for Ghost, `yes` for NOW. Read the supplier on each card before answering; the order can vary. Avoid a colon followed by a space in the reason (the box parses YAML). The structured form `{"approved": false, "reason": "..."}` still works.

The final message should be a table with two sent and one on hold, with your reason in it.

## Afterwards

Open the LangSmith project (`approval-loop`), open the `demo1` thread, and copy the trace link showing the interrupt run and the resume run. Paste it into the README's LangSmith section, and put the recording link at the top.
