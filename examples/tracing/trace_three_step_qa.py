from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from examples.three_step_qa import ThreeStepQAAssistant


class FakeClient:
    def __init__(self) -> None:
        self.n = 0
        self.is_weather_question = True

    def chat(self, messages, **kwargs):
        self.n += 1
        if self.n == 1:
            question = messages[-1]["content"]
            weather_keywords = ["天气", "下雨", "降雨", "温度", "适合去哪玩"]
            self.is_weather_question = any(keyword in question for keyword in weather_keywords)
            if not self.is_weather_question:
                return (
                    '{"intent":"general",'
                    '"user_query":"用户在询问一个普通问题",'
                    '"location":"",'
                    '"search_query":""}'
                )
            return (
                '{"intent":"weather",'
                '"user_query":"用户想了解明天北京天气不好时的游玩建议",'
                '"location":"北京",'
                '"search_query":"北京 雨天 游玩 室内景点"}'
            )
        if self.is_weather_question and self.n == 2:
            return (
                '{"decision":"answer",'
                '"reason":"天气信息已经足够，可以直接给出室内外建议",'
                '"refined_location":"北京",'
                '"refined_search_query":"北京 雨天 游玩 室内景点"}'
            )
        if self.is_weather_question:
            return "如果明天天气不好，优先考虑室内活动，比如博物馆、展览、书店和商场。"
        return "这是一个普通问题，不需要调用天气工具。我会直接基于问题本身回答。"


def fake_weather_lookup(location: str) -> str:
    return (
        f"Location: {location}\n"
        "Current: 10C, feels like 8C, weather light rain, humidity 72%, wind 15 km/h\n"
        "Today forecast: high 12C, low 7C, weather light rain, rain probability 70%\n"
        "Tomorrow forecast: high 11C, low 6C, weather heavy rain, rain probability 90%"
    )


def _last_message(state: Dict[str, Any]) -> str:
    messages = state.get("messages", [])
    if not messages:
        return ""
    last = messages[-1]
    content = getattr(last, "content", str(last))
    return f"{last.__class__.__name__}: {content}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Trace the three-step Q&A assistant.")
    parser.add_argument("question", nargs="?", default="明天我去北京，天气不好时适合去哪玩？")
    parser.add_argument("--mock", action="store_true", help="Use a fake client and skip API calls.")
    args = parser.parse_args()

    assistant = (
        ThreeStepQAAssistant(client=FakeClient(), weather_lookup=fake_weather_lookup)
        if args.mock
        else ThreeStepQAAssistant()
    )
    state = assistant.build_initial_state(args.question)

    print("Question:", args.question)
    print("\n--- trace start ---")
    print(
        "init:",
        {
            "step": state["step"],
            "intent": state["intent"],
            "user_query": state["user_query"],
            "location": state["location"],
            "search_query": state["search_query"],
        },
    )

    last_state: Dict[str, Any] | None = None
    config = {"configurable": {"thread_id": "trace-three-step-qa"}}
    for update in assistant.graph.stream(state, config=config, stream_mode="updates"):
        node_name, node_state = next(iter(update.items()))
        last_state = node_state
        print(f"\n[{node_name}]")
        print(
            "state:",
            {
                "step": node_state.get("step"),
                "intent": node_state.get("intent"),
                "user_query": node_state.get("user_query"),
                "location": node_state.get("location"),
                "search_query": node_state.get("search_query"),
                "search_rounds": node_state.get("search_rounds"),
                "search_results": node_state.get("search_results"),
                "reflection": node_state.get("reflection"),
                "reflect_decision": node_state.get("reflect_decision"),
                "final_answer": node_state.get("final_answer"),
            },
        )
        print("last_message:", _last_message(node_state))

    print("\n--- trace end ---")
    if last_state is not None:
        print("final_answer:", last_state.get("final_answer"))


if __name__ == "__main__":
    main()
