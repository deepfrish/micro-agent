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

## Technology Stack

- Python 3.10+ for the CLI, agent runtime, memory pipeline, and local tools
- DeepSeek-compatible chat API client in `core/llm_client.py`
- LangGraph-style state machine for ReAct execution
- LangChain-style message compatibility shims in `langchain_core/`
- MCP-style JSON-line tool protocol for local external tools
- Amap Web Service APIs for weather, geocoding, static maps, POI search, routing, and bus lookup
- FreeWeb MCP for public web search, browsing, extraction, GitHub search, parallel browsing, and screenshots
- Local JSON stores for sessions, window memory, and global long-term memory
- Local RAG over files in `knowledge_base/`
- Optional Qdrant vector retrieval experiment in `core/rag.py`

## Tooling

micro-agent has two tool layers.

Local tools are registered directly in `core/tools.py`:

- `Calculator` - safe arithmetic evaluator
- `Now` - current local date and time

External tools are loaded through providers and MCP:

- `AmapCapabilityProvider` starts `python -m coder mcp-server amap`
- `FreeWebProvider` starts the local `freeweb/dist/index.js` when present, otherwise falls back to `npx -y freeweb-mcp@latest`

Amap MCP tools:

- `Weather`
- `Geocode`
- `Regeocode`
- `StaticMap`
- `NearbySearch`
- `InputTips`
- `Route`
- `Bus`

FreeWeb MCP tools include:

- `web_search`
- `search_and_browse`
- `browse_page`
- `smart_browse`
- `deep_search`
- `github_search`
- `github_repo_files`
- `parallel_browse`
- `get_page_links`
- `screenshot`
- `inspect_llms_txt`

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
