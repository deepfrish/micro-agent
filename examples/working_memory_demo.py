from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.agent import ReActAgent


class FakeClient:
    def chat(self, messages, **kwargs):
        current_question = messages[-1]["content"]
        memory_block = next(
            (
                message["content"]
                for message in messages
                if message.get("role") == "system" and message.get("content", "").startswith("Working memory:")
            ),
            "",
        )

        if "\u521a\u624d" in current_question and "\u7528\u6237\u6b63\u5728\u5b66\u4e60:Agent" in memory_block:
            return "Finish[\u4f60\u521a\u624d\u8bf4\u4f60\u5728\u5b66 Agent\u3002]"
        if "\u6211\u53eb" in current_question or "\u6211\u5728\u5b66" in current_question:
            return "Finish[\u6211\u8bb0\u4f4f\u4e86\u8fd9\u4e9b\u4fe1\u606f\u3002]"
        return "Finish[\u6211\u4f1a\u57fa\u4e8e\u5df2\u6709\u8bb0\u5fc6\u6765\u56de\u7b54\u3002]"


def main() -> None:
    agent = ReActAgent(client=FakeClient())

    first_question = "\u6211\u53eb\u5c0f\u660e\uff0c\u6211\u5728\u5b66Agent\u3002"
    second_question = "\u6211\u521a\u624d\u8bf4\u6211\u5728\u5b66\u4ec0\u4e48\uff1f"

    print("Turn 1 question:", first_question)
    print("Turn 1 answer:", agent.run(first_question))
    print("Memory after turn 1:", agent.working_memory.snapshot())

    print()
    print("Turn 2 question:", second_question)
    print("Turn 2 answer:", agent.run(second_question))
    print("Memory after turn 2:", agent.working_memory.snapshot())


if __name__ == "__main__":
    main()
