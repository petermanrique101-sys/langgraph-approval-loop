# Recording the demo

Two clips, about thirty seconds each. Terminal first, Studio second.

## Before you start

```powershell
cd C:\Users\peter\langgraph-approval-loop
.venv\Scripts\Activate.ps1
Remove-Item checkpoints.db*, workspace\nutrishop -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force workspace\build | Out-Null; "junk" | Set-Content workspace\build\out.o
```

`MODEL`, `ANTHROPIC_API_KEY` and the three `LANGSMITH_*` variables must be set at User scope (they are). Open a fresh terminal so it sees them.

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

It opens `https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024`. Pick the **nutrishop** graph. In the input panel set `profile` to `autonomous`, add a human message `restock whatever is low`, and submit. Watch `call_model → policy → execute` run for the drafts, then the graph stop at `approve` with the card in the state panel. Answer the interrupt in the panel with `{"approved": true}` for the first, `{"approved": false, "reason": "Ghost raised prices last month, hold that one until I call them"}` for the second, `{"approved": true}` for the third.

The final message should be a table with two sent and one on hold, with your reason in it.

## Afterwards

Open the LangSmith project (`approval-loop`), open the `demo1` thread, and copy the trace link showing the interrupt run and the resume run. Paste it into the README's LangSmith section, and put the recording link at the top.
