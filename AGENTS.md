# Instructions for AI Agents (AGENTS.md)

This file contains technical instructions, architecture guidelines, and conventions for AI Agents interacting with or contributing to the `micro-agent` project. 

## Project Overview
Micro-Agent is an AI Agent framework that supports RAG, multi-turn conversations, memory extraction, and MCP (Model Context Protocol) tool integration.

## Architecture
- `src/core/`: Contains the central orchestrator logic (Agents, Memory management, Prompts, Protocols).
- `src/coder/`: Contains the CLI application and interaction entry points.
- `src/langchain_core/` & `src/langgraph/`: Light-weight mocked/wrapped logic mimicking LangChain/LangGraph.
- `tools/`: All callable external capabilities. MCP servers go in `tools/mcp_servers/`, and custom skills go in `tools/skills/`.
- `data/`: Contains static datasets (e.g., knowledge base files).
- `docs/`: System architecture documentation.
- `tests/`: Test cases. 
- `scripts/`: Various utility scripts (e.g., KB indexing, DB clearing).

## Conventions & Rules
1. **Tool Independence**: When writing new tools, place them in `tools/`. Do not pollute the `src/core` with ad-hoc tool logic. Use MCP wherever applicable.
2. **Imports**: Since the code was refactored to an Agent-Native structure, always use absolute imports via `src.` and `tools.` (e.g., `from src.core.agent import ReActAgent`).
3. **Memory Management**: The system relies on short-term window memory and long-term vector memory. Be careful when altering `src/core/memory.py` or `src/core/rag.py`. Always run tests in `tests/` after modifying memory logic.
4. **Environment Variables**: Use `.env` file for API keys. See `.env.example` for required variables.

## Running Tests
Run test files using standard Python from the project root:
```bash
python tests/test_everything_agent.py
python tests/test_ragtool.py
```
