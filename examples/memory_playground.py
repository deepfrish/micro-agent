from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.tools import execute_tool


NAMESPACE = "memory-playground"


def run_tool(operation: str, **kwargs: str | int) -> str:
    payload = {"operation": operation, "namespace": NAMESPACE}
    payload.update(kwargs)
    return execute_tool("Memory", payload)


def main() -> None:
    print(run_tool("clear"))
    print(run_tool("add", content="我是小明，我在学Agent。"))
    print(run_tool("add", content="我喜欢写代码，想继续学习RAG。"))
    print()
    print(run_tool("stats"))
    print()
    print(run_tool("search", query="我在学什么"))
    print()
    print(run_tool("list", limit=10))


if __name__ == "__main__":
    main()
