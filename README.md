# micro-agent

micro-agent is a learning-oriented chat agent skeleton. The goal is to make every turn easy to trace: routing, memory, RAG, tools, and exit-time consolidation are all explicit and documented so a future Codex can read the repo quickly.

## Quick Start

```bash
pip install -r requirements.txt
python -m coder
```

The app reads secrets from `.env` in the project root. `.env` is ignored and will not be pushed.

## Entry Points

- `python -m coder` - interactive CLI
- `/new` - start a new chat namespace
- `/exit` - save the current session and quit
- `/exit -n` - save the current session and stay in the CLI
- `/compress` - compress the active chat window
- `/del <namespace>` - delete one chat window history
- `/tools` - print the current tool list
- `/net on|once|off|status` - control network preference
- `/your-namespace` - switch to a namespace
- `python -m coder memory-worker <job.json>` - background memory consolidation job
- `python -m coder mcp-server amap|weather` - local MCP tool servers

## Documentation

- [Architecture guide](./MICRO_AGENT_ARCHITECTURE.md)

## Core Layout

- `coder/` - CLI entry point, command parsing, background memory worker
- `core/product/` - product-facing wrappers; read these first
- `core/` - low-level agent, memory, RAG, tools, and MCP compatibility code
- `freeweb/` - optional web tooling submodule used by the FreeWeb provider
- `knowledge_base/` - local RAG corpus
- `examples/` - demos, traces, and compression logs

If the submodule is missing after clone, run:

```bash
git submodule update --init --recursive
```

## Runtime Model

- Decide whether the turn is a memory update, a direct answer, or a ReAct tool turn
- Inject working memory, long-term memory, and local RAG only when useful
- Run the agent through LangGraph: `think -> act -> reflect -> repair/stop`
- On exit, summarize the active window and merge it into long-term memory

## Data State

The `data/` directory has been cleared. Runtime files will be recreated automatically the next time the app runs.
