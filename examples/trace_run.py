from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.agent import ReActAgent


class FakeClient:
    def __init__(self) -> None:
        self.n = 0

    def chat(self, messages, **kwargs):
        self.n += 1
        if self.n == 1:
            return "Thought: I should calculate first\nAction: Calculator[2 + 3]"
        if self.n == 2:
            return '{"decision":"continue","reason":"Need one more check before finishing","final_answer":""}'
        if self.n == 3:
            return "Thought: The result is enough now\nFinish[2 + 3 = 5]"
        return "Finish[2 + 3 = 5]"


def _last_message(state: Dict[str, Any]) -> str:
    messages = state.get("messages", [])
    if not messages:
        return ""
    last = messages[-1]
    return f"{last.get('role', '?')}: {last.get('content', '')}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Trace a LangGraph ReAct run.")
    parser.add_argument("question", nargs="?", default="2 + 3 equals what?")
    parser.add_argument("--mock", action="store_true", help="Use a fake client and skip API calls.")
    args = parser.parse_args()

    agent = ReActAgent(client=FakeClient()) if args.mock else ReActAgent()
    state = agent.build_initial_state(args.question)

    print("Question:", args.question)
    print("\n--- trace start ---")
    print(
        "init:",
        {
            "steps": state["steps"],
            "final_answer": state["final_answer"],
            "next_action": state["next_action"],
            "last_action": state["last_action"],
            "observation": state["observation"],
            "working_memory": state.get("working_memory", []),
        },
    )

    last_state: Dict[str, Any] | None = None
    for update in agent.graph.stream(state, stream_mode="updates"):
        node_name, node_state = next(iter(update.items()))
        last_state = node_state
        print(f"\n[{node_name}]")
        print(
            "state:",
            {
                "steps": node_state.get("steps"),
                "final_answer": node_state.get("final_answer"),
                "next_action": node_state.get("next_action"),
                "last_action": node_state.get("last_action"),
                "observation": node_state.get("observation"),
                "reflection": node_state.get("reflection"),
                "reflect_decision": node_state.get("reflect_decision"),
                "working_memory": node_state.get("working_memory"),
            },
        )
        print("last_message:", _last_message(node_state))

    print("\n--- trace end ---")
    if last_state is not None:
        print("final_answer:", last_state.get("final_answer"))


if __name__ == "__main__":
    main()
