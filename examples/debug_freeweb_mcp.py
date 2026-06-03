from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.core.memory_pipeline import TurnRouter
from src.core.tools import create_default_registry

LOG_PATH = PROJECT_ROOT / "examples" / "freeweb_debug_log.jsonl"
DEFAULT_QUESTION = "给我搜索一下今日的交通信息热点快报，附上文章链接，给我3条就好了"


if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


class DirectRouteClient:
    def chat(self, *_: Any, **__: Any) -> str:
        return json.dumps({"route": "direct", "reason": "forced direct for fallback test"}, ensure_ascii=False)


def log_event(event: Dict[str, Any]) -> None:
    event.setdefault("timestamp", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Debug FreeWeb MCP routing and tool execution.")
    parser.add_argument("question", nargs="?", default=DEFAULT_QUESTION)
    parser.add_argument("--tool", default="search_and_browse", choices=["web_search", "search_and_browse"])
    args = parser.parse_args()

    question = args.question
    print(f"Question: {question}")

    router = TurnRouter(DirectRouteClient())
    route = router.route(question, [])
    print(f"Forced-direct route result: {route}")
    log_event({"stage": "route_forced_direct", "question": question, "route": route})

    registry = create_default_registry(include_external=True)
    tools = registry.list_tools()
    freeweb_tools = [f"{tool.name} [{tool.source_label()}]" for tool in tools if tool.source_label().startswith("freeweb/")]
    print(f"FreeWeb tools ({len(freeweb_tools)}):")
    for item in freeweb_tools:
        print(f"- {item}")
    log_event({"stage": "registry", "freeweb_tools": freeweb_tools, "tool_count": len(tools)})

    try:
        tool = registry.find_tool(args.tool)
        if args.tool == "web_search":
            payload = {"query": question, "maxResults": 3, "engine": "auto", "maxAgeMonths": 1}
        else:
            payload = {
                "query": question,
                "maxResults": 3,
                "browseTop": 3,
                "engine": "auto",
                "maxAgeMonths": 1,
                "excerptChars": 1200,
            }
        print(f"Calling {tool.name} [{tool.source_label()}] with {payload}")
        result = tool.run(payload)
        print("Result preview:")
        print(result[:4000])
        log_event(
            {
                "stage": "tool_call",
                "tool": tool.name,
                "source": tool.source_label(),
                "payload": payload,
                "ok": not result.lower().startswith(("tool error:", "mcp tool error:")),
                "result_preview": result[:4000],
            }
        )
    except Exception as exc:
        print(f"Error: {type(exc).__name__}: {exc}")
        log_event({"stage": "tool_call", "tool": args.tool, "ok": False, "error": f"{type(exc).__name__}: {exc}"})

    print(f"Debug log: {LOG_PATH}")


if __name__ == "__main__":
    main()
