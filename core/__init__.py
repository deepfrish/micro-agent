from __future__ import annotations

from .framework import Agent, AgentConfig, Message
from .memory import WorkingMemory, extract_key_facts
from .long_term_memory import LongTermMemoryStore
from .memory_pipeline import ExitMemoryConsolidator, GlobalMemoryRouter, RAGRouter, TurnRouter
from .compression import WindowCompressor
from .context_builder import ContextBuildResult, ContextBuilder, ContextBuilderConfig
from .prompts import TASK_SPLIT_PROMPT, TASK_SYNTHESIS_PROMPT, WINDOW_FACT_RECALL_PROMPT, WINDOW_MISSING_POINT_VERIFICATION_PROMPT
from .window_memory import WindowMemoryStore
from .task_pipeline import TaskPlanner, TaskSynthesizer
from .rag import (
    HashEmbeddingModel,
    KnowledgeBase,
    KnowledgeChunk,
    QdrantKnowledgeBase,
    QdrantVectorStore,
    SearchHit,
    chunk_text,
    read_document,
)
from .tools import (
    CalculatorTool,
    FunctionTool,
    NearbySearchTool,
    NowTool,
    StaticMapTool,
    Tool,
    ToolParameter,
    ToolRegistry,
    WeatherTool,
    execute_tool,
    find_tool,
    tool_list_text,
    tool_schemas,
)

__all__ = [
    "Agent",
    "AgentConfig",
    "CalculatorTool",
    "ExitMemoryConsolidator",
    "FunctionTool",
    "GlobalMemoryRouter",
    "Message",
    "NearbySearchTool",
    "NowTool",
    "ReActAgent",
    "StaticMapTool",
    "Tool",
    "ToolParameter",
    "ToolRegistry",
    "TaskPlanner",
    "TaskSynthesizer",
    "WindowCompressor",
    "ContextBuildResult",
    "ContextBuilder",
    "ContextBuilderConfig",
    "TASK_SPLIT_PROMPT",
    "TASK_SYNTHESIS_PROMPT",
    "WINDOW_FACT_RECALL_PROMPT",
    "WINDOW_MISSING_POINT_VERIFICATION_PROMPT",
    "WeatherTool",
    "execute_tool",
    "find_tool",
    "LongTermMemoryStore",
    "RAGRouter",
    "TurnRouter",
    "WindowMemoryStore",
    "HashEmbeddingModel",
    "KnowledgeBase",
    "KnowledgeChunk",
    "QdrantKnowledgeBase",
    "QdrantVectorStore",
    "SearchHit",
    "chunk_text",
    "read_document",
    "WorkingMemory",
    "extract_key_facts",
    "tool_list_text",
    "tool_schemas",
]


def __getattr__(name: str):
    if name == "ReActAgent":
        from .agent import ReActAgent

        return ReActAgent
    raise AttributeError(f"module 'core' has no attribute {name!r}")
