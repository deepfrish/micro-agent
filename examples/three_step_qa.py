from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Literal, TypedDict

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.langchain_core.messages import HumanMessage, SystemMessage
from src.langgraph.checkpoint.memory import InMemorySaver
from src.langgraph.graph import END, START, StateGraph

from src.core.llm_client import DeepSeekClient
from src.core.tools import weather


UNDERSTAND_PROMPT = """You are the understand node of a three-step Q&A assistant.
Rewrite the user's question into strict JSON with these fields:
{
  "intent": "weather | general",
  "user_query": "...",
  "location": "...",
  "search_query": "..."
}

- intent: weather if the user asks about weather, rain, temperature, travel planning affected by weather, or whether an activity is suitable under weather conditions; otherwise general
- user_query: concise intent summary in Chinese
- location: the most likely city or place for weather lookup; use empty string if intent is general or no location exists
- search_query: short keywords for weather and activity planning

Return JSON only."""


REFLECT_PROMPT = """You are the reflect node of a three-step Q&A assistant.
Inspect the user intent, weather lookup result, and decide the next step.

Return strict JSON only:
{
  "decision": "answer | search | understand",
  "reason": "...",
  "refined_location": "...",
  "refined_search_query": "..."
}

Rules:
- Use answer when weather information is sufficient.
- Use search when the location or weather evidence is still insufficient but can be refined.
- Use understand when the original intent is still unclear.
"""


ANSWER_PROMPT = """You are the answer node of a three-step Q&A assistant.
Answer the user's question using the understood intent, weather lookup result, and reflection note when available.

Requirements:
- Answer in Chinese.
- Be practical and concise.
- Do not repeat the same suggestion in multiple bullets.
- If weather data is incomplete, say so clearly and give a cautious recommendation.
- If the user's question is not about weather, answer directly without pretending that weather data was used.
"""


class SearchState(TypedDict):
    messages: list[Any]
    intent: str
    user_query: str
    location: str
    search_query: str
    search_results: str
    reflection: str
    reflect_decision: str
    final_answer: str
    step: str
    search_rounds: int


def _parse_json_text(text: str) -> Dict[str, str]:
    try:
        data = json.loads(text)
    except Exception:
        return {}
    return {key: str(value).strip() for key, value in data.items() if isinstance(value, (str, int, float))}


def _coalesce(*values: str) -> str:
    for value in values:
        if value and value.strip():
            return value.strip()
    return ""


@dataclass
class ThreeStepQAAssistant:
    client: DeepSeekClient = field(default_factory=DeepSeekClient)
    weather_lookup: Callable[[str], str] = field(default=weather)
    max_search_rounds: int = 2

    def __post_init__(self) -> None:
        self.graph = self._build_graph()

    def build_initial_state(self, question: str) -> SearchState:
        return {
            "messages": [HumanMessage(content=question)],
            "intent": "",
            "user_query": "",
            "location": "",
            "search_query": "",
            "search_results": "",
            "reflection": "",
            "reflect_decision": "",
            "final_answer": "",
            "step": "understand",
            "search_rounds": 0,
        }

    def run(self, question: str) -> str:
        final_state = self.graph.invoke(
            self.build_initial_state(question),
            config={"configurable": {"thread_id": "three-step-qa"}},
        )
        return final_state["final_answer"]

    def _build_graph(self):
        workflow = StateGraph(SearchState)
        workflow.add_node("understand", self._understand_node)
        workflow.add_node("search", self._search_node)
        workflow.add_node("reflect", self._reflect_node)
        workflow.add_node("answer", self._answer_node)

        workflow.add_edge(START, "understand")
        workflow.add_conditional_edges(
            "understand",
            self._route_after_understand,
            {
                "search": "search",
                "answer": "answer",
            },
        )
        workflow.add_edge("search", "reflect")
        workflow.add_conditional_edges(
            "reflect",
            self._route_after_reflect,
            {
                "answer": "answer",
                "search": "search",
                "understand": "understand",
                "end": END,
            },
        )
        workflow.add_edge("answer", END)

        memory = InMemorySaver()
        return workflow.compile(checkpointer=memory)

    def _understand_node(self, state: SearchState) -> SearchState:
        question = state["messages"][-1].content
        response = self.client.chat(
            [
                {"role": "system", "content": UNDERSTAND_PROMPT},
                {"role": "user", "content": question},
            ]
        ).strip()

        parsed = _parse_json_text(response)
        intent = (parsed.get("intent", "") or "general").lower()
        if intent not in {"weather", "general"}:
            intent = "general"
        user_query = _coalesce(parsed.get("user_query", ""), question)
        location = parsed.get("location", "").strip()
        search_query = _coalesce(parsed.get("search_query", ""), question)

        updated_messages = list(state["messages"])
        updated_messages.append(SystemMessage(content=f"Understand output: {response}"))

        return {
            **state,
            "messages": updated_messages,
            "intent": intent,
            "user_query": user_query,
            "location": location,
            "search_query": search_query,
            "step": "search" if intent == "weather" else "answer",
        }

    def _search_node(self, state: SearchState) -> SearchState:
        location = _coalesce(state["location"], state["search_query"], state["user_query"])
        results = self.weather_lookup(location)
        updated_messages = list(state["messages"])
        updated_messages.append(SystemMessage(content=f"Search output: {results}"))

        return {
            **state,
            "messages": updated_messages,
            "search_results": results,
            "search_rounds": state["search_rounds"] + 1,
            "step": "reflect",
        }

    def _reflect_node(self, state: SearchState) -> SearchState:
        response = self.client.chat(
            [
                {"role": "system", "content": REFLECT_PROMPT},
                {"role": "user", "content": f"Original question: {state['messages'][0].content}"},
                {"role": "user", "content": f"Intent summary: {state['user_query']}"},
                {"role": "user", "content": f"Location: {state['location']}"},
                {"role": "user", "content": f"Search query: {state['search_query']}"},
                {"role": "user", "content": f"Weather result: {state['search_results']}"},
            ]
        ).strip()

        parsed = _parse_json_text(response)
        decision = (parsed.get("decision", "") or "answer").lower()
        reason = parsed.get("reason", "")
        refined_location = _coalesce(parsed.get("refined_location", ""), state["location"])
        refined_search_query = _coalesce(parsed.get("refined_search_query", ""), state["search_query"])

        if "weather error" in state["search_results"].lower() and decision == "answer":
            decision = "search"

        updated_messages = list(state["messages"])
        updated_messages.append(SystemMessage(content=f"Reflection output: {response}"))

        return {
            **state,
            "messages": updated_messages,
            "reflection": reason,
            "reflect_decision": decision,
            "location": refined_location,
            "search_query": refined_search_query,
            "step": "answer" if decision == "answer" else decision,
        }

    def _answer_node(self, state: SearchState) -> SearchState:
        answer = self.client.chat(
            [
                {"role": "system", "content": ANSWER_PROMPT},
                {"role": "user", "content": f"Original question: {state['messages'][0].content}"},
                {"role": "user", "content": f"Intent type: {state['intent']}"},
                {"role": "user", "content": f"Intent summary: {state['user_query']}"},
                {"role": "user", "content": f"Weather result: {state['search_results']}"},
                {"role": "user", "content": f"Reflection note: {state['reflection']}"},
            ]
        ).strip()

        updated_messages = list(state["messages"])
        updated_messages.append(SystemMessage(content=f"Answer output: {answer}"))

        return {
            **state,
            "messages": updated_messages,
            "final_answer": answer,
            "step": "done",
        }

    def _route_after_understand(self, state: SearchState) -> Literal["search", "answer"]:
        if state["intent"] == "weather" and state["location"]:
            return "search"
        return "answer"

    def _route_after_reflect(self, state: SearchState) -> Literal["answer", "search", "understand", "end"]:
        if state["search_rounds"] >= self.max_search_rounds and state["reflect_decision"] == "search":
            return "answer"
        if state["reflect_decision"] == "search":
            return "search"
        if state["reflect_decision"] == "understand":
            return "understand"
        return "answer"


def create_three_step_assistant() -> ThreeStepQAAssistant:
    return ThreeStepQAAssistant()


if __name__ == "__main__":
    assistant = create_three_step_assistant()
    question = input("请输入问题: ").strip()
    if question:
        print("\n最终回答:")
        print(assistant.run(question))
