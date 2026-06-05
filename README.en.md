# micro-agent

micro-agent is a learning-oriented chat agent skeleton. The goal is to make every turn easy to trace: routing, memory, RAG, tools, and exit-time consolidation are all explicit and documented so a future AI coding assistant can read the repo quickly.

## Quick Start

### 1. Clone and Install Dependencies
```bash
git clone https://github.com/deepfrish/micro-agent.git
cd micro-agent
pip install -r requirements.txt
```

### 2. Configure Environment Variables
The application reads secrets from `.env` in the project root. Please duplicate the example file and fill in your API keys:
```bash
cp .env.example .env
```

### 3. MCP Environment Initialization (Recommended)
To enable robust local filesystem operations, git integrations, and Everything search for your Agent, it is highly recommended to initialize MCP:
```bash
python scripts/setup_mcp_config.py
```
This will automatically generate a localized `mcp.json` (gitignored) in `tools/mcp_servers/` tailored to your absolute paths and create a safe sandbox workspace at `data/workspace/`.

### 4. Start the Interactive TUI Terminal
Run the following command to start the TUI application and begin chatting with the Agent:
```bash
python -m src.coder
```

## Entry Points

- `python -m src.coder` - interactive CLI
- `/new` - start a new chat namespace
- `/exit` - save the current session and quit
- `/exit -n` - save the current session and stay in the CLI
- `/compress` - compress the active chat window
- `/del <namespace>` - delete one chat window history
- `/tools` - print the current tool list
- `/rag <strategy>` - switch the RAG retrieval strategy (supports three modes: `base` basic retrieval, `mqe` multi-query expansion, `hyde` hypothetical document embeddings)
- `/net on|once|off|status` - control network preference
- `/your-namespace` - switch to a namespace
- `python -m src.coder memory-worker <job.json>` - background memory consolidation job
- `python -m src.coder mcp-server amap|weather` - local MCP tool servers

## Documentation

- [Architecture guide](./docs/MICRO_AGENT_ARCHITECTURE.md)
- [Chinese README](./README.md)
- [English architecture guide](./docs/MICRO_AGENT_ARCHITECTURE.en.md)

## Technology Stack

- Python 3.10+ for the CLI, agent runtime, memory pipeline, and local tools
- DeepSeek-compatible chat API client in `src/core/llm_client.py`, with a dedicated `MemoryLLMClient` using cost-effective Qwen models for background memory consolidation
- LangGraph-style state machine for ReAct execution
- LangChain-style message compatibility shims in `src/langchain_core/`
- MCP-style JSON-line tool protocol for local external tools
- Amap Web Service APIs for weather, geocoding, static maps, POI search, routing, and bus lookup
- FreeWeb MCP for public web search, browsing, extraction, GitHub search, parallel browsing, and screenshots
- Local JSON stores for sessions, window memory, and global long-term memory
- Local RAG over files in `data/knowledge_base/`
- Optional Qdrant vector retrieval experiment in `src/core/rag.py`

## Tooling

micro-agent has two tool layers.

Local tools are registered directly in `src/core/tools.py`:

- `Calculator` - safe arithmetic evaluator
- `Now` - current local date and time

External tools are loaded through providers and unified MCP configuration (`tools/mcp_servers/mcp.json`):

- `AmapCapabilityProvider` starts `python -m src.coder mcp-server amap`
- `FreeWebProvider` starts the local `tools/mcp_servers/freeweb/dist/index.js` when present, otherwise falls back to `npx -y freeweb-mcp@latest`
- Dynamically parses and loads standard MCP tools from `mcp.json` (e.g., `@modelcontextprotocol/server-filesystem` for full file create, read, and write capabilities).

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

## Project Structure

```text
micro-agent/
├── data/
├── docs/
├── examples/
├── scripts/
├── src/
│   ├── coder/
│   │   └── cli/
│   ├── core/
│   │   ├── providers/
│   │   ├── protocols/
│   │   └── product/
│   ├── langchain_core/
│   └── langgraph/
├── tests/
└── tools/
    ├── mcp_servers/
    │   ├── freeweb/
    │   └── mcp.json
    └── skills/
        ├── engineering-exploration/
        └── universal-location-and-transit-assistant/
```

- `src/coder/` - CLI entry point, command parsing, and background memory worker
- `src/core/` - agent runtime, memory, RAG, tools, and MCP compatibility code
- `src/core/product/` - product-facing wrappers; read these first
- `src/core/providers/` - external capability providers
- `src/core/protocols/` - MCP and other protocol-layer code
- `src/langchain_core/` - lightweight message compatibility layer
- `src/langgraph/` - local state machine compatibility implementation
- `tools/skills/` - installed local capability packs
- `tools/mcp_servers/freeweb/` - optional web tooling submodule used by the FreeWeb provider
- `scripts/` - offline smoke tests and helper scripts
- `examples/` - demos, traces, and compression logs
- `data/` - runtime session, window memory, and global memory state, along with local RAG corpus (`knowledge_base/`)
- `docs/` - system architecture documentation
- `tests/` - test cases

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
