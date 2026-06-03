from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.conversation import ConversationManager, ConversationSession, ConversationStore
from src.core.long_term_memory import LongTermMemoryStore
from src.core.memory import WorkingMemory
from src.core.memory_pipeline import RAGRouter, TurnRouter
from src.core.skills import SkillRegistry, SkillRouter
from src.core.tools import create_default_registry


class ScriptedChatClient:
    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.calls: List[Dict[str, Any]] = []

    def chat(self, messages: List[Dict[str, str]], temperature: float | None = None) -> str:
        self.calls.append({"messages": messages, "temperature": temperature})
        system_text = "\n".join(str(message.get("content", "")) for message in messages if message.get("role") == "system")
        user_text = "\n".join(str(message.get("content", "")) for message in messages if message.get("role") == "user")

        if "You decide whether a user turn should activate one of the available skills." in system_text:
            return json.dumps(
                {
                    "use_skill": True,
                    "selected_skill": "engineering-exploration",
                    "confidence": 0.95,
                    "reason": "the turn is about planning and should stay in exploration mode",
                },
                ensure_ascii=False,
            )

        if "You decide how a user turn should be handled in a lightweight assistant." in system_text:
            return json.dumps(
                {
                    "route": "direct",
                    "reason": "skill-guided planning should stay in direct answer mode",
                },
                ensure_ascii=False,
            )

        if "You are a lightweight assistant that replies without tool use." in system_text:
            if "Active skill context:" in system_text:
                return f"{self.mode} skill answer with injected skill context"
            return f"{self.mode} skill answer"

        if "You decide whether one user message should be split into smaller tasks." in system_text:
            return json.dumps(
                {
                    "needs_split": False,
                    "reason": "single task",
                    "tasks": [
                        {
                            "id": "1",
                            "route": "direct",
                            "status": "ready",
                            "text": user_text or "task",
                            "reason": "single task",
                        }
                    ],
                },
                ensure_ascii=False,
            )

        return "{}"


class StubAgent:
    def __init__(self) -> None:
        self.working_memory = WorkingMemory()
        self.tool_registry = create_default_registry(include_external=False)
        self.tool_call_trace: List[str] = []
        self.last_tool_name: str | None = None
        self.last_tool_source: str | None = None
        self.last_tool_label: str | None = None

    def reset_turn_metadata(self) -> None:
        self.tool_call_trace = []
        self.last_tool_name = None
        self.last_tool_source = None
        self.last_tool_label = None

    def run(self, question: str, history_messages: List[Dict[str, str]] | None = None, *, reset_tool_trace: bool = True) -> str:
        return "react fallback answer"


class StubRAGRouter:
    def retrieve_context(self, question: str, history: List[Dict[str, str]]) -> str:
        return ""


class StubTaskPlanner:
    def plan(
        self,
        question: str,
        history: List[Dict[str, str]],
        memory_context: str = "",
        *,
        skill_context: str = "",
        force_network: bool = False,
    ) -> Dict[str, Any]:
        return {
            "needs_split": False,
            "reason": "stub",
            "tasks": [
                {
                    "id": "1",
                    "route": "direct",
                    "status": "ready",
                    "text": question,
                    "reason": "stub",
                }
            ],
        }


class StubTaskSynthesizer:
    def synthesize(self, question: str, history: List[Dict[str, str]], task_results: List[Dict[str, Any]]) -> str:
        return ""


def build_manager(client: ScriptedChatClient) -> ConversationManager:
    temp_root = TemporaryDirectory()
    temp_path = Path(temp_root.name)
    # Keep the temporary directory alive by attaching it to the manager.
    manager = ConversationManager(
        client=client,
        session_store=ConversationStore(temp_path / "chat_sessions.json"),
        memory_store=LongTermMemoryStore(temp_path / "global_memory.json"),
        rag_router=StubRAGRouter(),
        turn_router=TurnRouter(client),
        task_planner=StubTaskPlanner(),
        task_synthesizer=StubTaskSynthesizer(),
        skill_registry=SkillRegistry([ROOT / "skills"]),
        skill_router=SkillRouter(SkillRegistry([ROOT / "skills"]), client),
    )
    manager._skill_smoke_tempdir = temp_root  # type: ignore[attr-defined]
    manager.sessions["demo"] = ConversationSession(namespace="demo", agent=StubAgent())
    manager.active_namespace = "demo"
    return manager


def run_case(mode: str, question: str) -> Dict[str, Any]:
    client = ScriptedChatClient(mode=mode)
    manager = build_manager(client)
    session, answer, _ = manager.ask(question)
    skill_state = dict(session.skill_state or {})
    turn_prompt_seen = any(
        "Active skill guidance:" in str(message.get("content", ""))
        for call in client.calls
        for message in call["messages"]
    )
    skill_prompt_calls = sum(
        1
        for call in client.calls
        if "You decide whether a user turn should activate one of the available skills." in "\n".join(
            str(message.get("content", "")) for message in call["messages"] if message.get("role") == "system"
        )
    )
    return {
        "mode": mode,
        "question": question,
        "answer": answer,
        "skill_state": skill_state,
        "turn_prompt_seen": turn_prompt_seen,
        "skill_prompt_calls": skill_prompt_calls,
        "call_count": len(client.calls),
    }


def assert_case(result: Dict[str, Any], expected_route_mode: str) -> None:
    skill_state = result["skill_state"]
    if skill_state.get("mode") != expected_route_mode:
        raise AssertionError(f"expected skill mode {expected_route_mode}, got {skill_state}")
    if skill_state.get("selected_skill") != "engineering-exploration":
        raise AssertionError(f"expected engineering-exploration skill, got {skill_state}")
    if "skill answer" not in result["answer"]:
        raise AssertionError(f"expected skill-aware answer, got {result['answer']!r}")
    if not result["turn_prompt_seen"]:
        raise AssertionError("skill context was not injected into the turn prompt")


def main() -> int:
    explicit = run_case(
        "explicit",
        "使用engineering-exploration skill帮我设计一个文件上传模块，先不要写代码。",
    )
    implicit = run_case(
        "implicit",
        "我想设计一个文件上传模块，先不要写代码，帮我梳理方案。",
    )

    assert_case(explicit, "explicit")
    assert_case(implicit, "implicit")
    if implicit["skill_prompt_calls"] != 1:
        raise AssertionError(f"implicit path should call the skill router once, got {implicit['skill_prompt_calls']}")
    if explicit["skill_prompt_calls"] != 0:
        raise AssertionError(f"explicit path should bypass the skill router prompt, got {explicit['skill_prompt_calls']}")

    print("Explicit skill test: ok")
    print("Implicit skill test: ok")
    print("Skill smoke test: passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
