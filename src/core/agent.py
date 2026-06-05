from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Tuple, TypedDict

from src.langgraph.graph import END, START, StateGraph

from .framework import Agent, AgentConfig
from .memory import WorkingMemory
from .prompts import REFLECT_PROMPT, SYSTEM_PROMPT
from .tools import ToolRegistry, create_default_registry


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TOOL_CALL_LOG = PROJECT_ROOT / "examples" / "tool_call_log.jsonl"
REACT_TRACE_LOG = PROJECT_ROOT / "examples" / "react_trace_log.jsonl"


class AgentState(TypedDict):
    messages: List[Dict[str, Any]]
    question: str
    working_memory: List[str]
    steps: int
    final_answer: str | None
    next_action: List[Tuple[str, str, str]] | None
    last_action: Tuple[str, str] | None
    observation: str
    reflection: str
    reflect_decision: str


@dataclass
class ReActAgent(Agent):
    config: AgentConfig | None = None
    client: object | None = None
    working_memory: WorkingMemory = field(init=False, repr=False)
    tool_registry: ToolRegistry = field(init=False, repr=False)

    def __post_init__(self) -> None:
        Agent.__init__(self, client=self.client, config=self.config)
        self.tool_registry = create_default_registry(memory_namespace=self.config.memory_namespace)
        self.working_memory = WorkingMemory(capacity=self.config.working_memory_capacity)
        self.last_tool_name: str | None = None
        self.last_tool_source: str | None = None
        self.last_tool_label: str | None = None
        self.tool_call_trace: List[str] = []

    def reset_turn_metadata(self) -> None:
        self.last_tool_name = None
        self.last_tool_source = None
        self.last_tool_label = None
        self.tool_call_trace = []

    def build_initial_state(
        self,
        question: str,
        history_messages: List[Dict[str, Any]] | None = None,
    ) -> AgentState:
        self.working_memory.add(question)
        history = list(history_messages or [])
        return {
            "messages": [
                self.message(
                    "system",
                    SYSTEM_PROMPT.format(
                        tool_list=self.tool_registry.get_tools_description(),
                        memory_namespace=self.config.memory_namespace,
                    ),
                ),
                *history,
                self.message("user", question),
            ],
            "question": question,
            "working_memory": self.working_memory.snapshot(),
            "steps": 0,
            "final_answer": None,
            "next_action": None,
            "last_action": None,
            "observation": "",
            "reflection": "",
            "reflect_decision": "",
        }

    def run(
        self,
        question: str,
        history_messages: List[Dict[str, Any]] | None = None,
        *,
        reset_tool_trace: bool = True,
    ) -> str:
        if reset_tool_trace:
            self.reset_turn_metadata()
        final_state = self.graph.invoke(self.build_initial_state(question, history_messages=history_messages))
        return final_state.get("final_answer") or "Stopped because the agent did not produce a final answer."

    def _build_graph(self):
        graph = StateGraph(AgentState)
        graph.add_node("think", self._think_node)
        graph.add_node("act", self._act_node)
        graph.add_node("reflect", self._reflect_node)
        graph.add_node("repair", self._repair_node)
        graph.add_node("stop", self._stop_node)

        graph.add_edge(START, "think")
        graph.add_conditional_edges(
            "think",
            self._route_after_think,
            {
                "act": "act",
                "repair": "repair",
                "stop": "stop",
                "end": END,
            },
        )
        graph.add_edge("act", "reflect")
        graph.add_conditional_edges(
            "reflect",
            self._route_after_reflect,
            {
                "think": "think",
                "repair": "repair",
                "stop": "stop",
                "end": END,
            },
        )
        graph.add_edge("repair", "think")
        graph.add_edge("stop", END)
        return graph.compile()

    def _think_node(self, state: AgentState) -> AgentState:
        tools_schema = self.tool_registry.to_openai_schema()
        reply_msg = self.chat(
            self._messages_with_working_memory(state),
            temperature=self.config.temperature,
            tools=tools_schema
        )
        content = str(reply_msg.get("content") or "").strip()
        tool_calls = reply_msg.get("tool_calls")
        
        final_answer = None
        next_action = None
        
        if tool_calls and isinstance(tool_calls, list) and len(tool_calls) > 0:
            next_action = []
            for call in tool_calls:
                call_id = call.get("id", "")
                func = call.get("function", {})
                tool_name = func.get("name", "")
                tool_input = func.get("arguments", "")
                next_action.append((tool_name, tool_input, call_id))
        else:
            final_answer = content

        self._write_react_trace_log(
            {
                "stage": "think",
                "namespace": self.config.memory_namespace,
                "question": state["question"],
                "step": state["steps"] + 1,
                "parsed_action": [list(a) for a in next_action] if next_action else None,
                "parsed_finish": bool(final_answer),
                "reply_preview": content[:1200] if content else "Tool Call",
            }
        )

        return {
            **state,
            "messages": state["messages"] + [reply_msg],
            "steps": state["steps"] + 1,
            "final_answer": final_answer,
            "next_action": next_action,
            "last_action": (next_action[-1][0], next_action[-1][1]) if next_action else state["last_action"],
            "observation": state["observation"],
            "reflection": state["reflection"],
            "reflect_decision": state["reflect_decision"],
        }

    def _act_node(self, state: AgentState) -> AgentState:
        if not state["next_action"]:
            return state

        tool_msgs = []
        observations = []
        for tool_name, tool_input, tool_call_id in state["next_action"]:
            obs = self._execute_tool(tool_name, tool_input)
            observations.append(f"[{tool_name}]: {obs}")
            tool_msgs.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "name": tool_name,
                "content": obs,
            })
        
        combined_obs = "\n\n".join(observations)
        
        return {
            **state,
            "messages": state["messages"] + tool_msgs,
            "observation": combined_obs,
            "last_action": (state["next_action"][-1][0], state["next_action"][-1][1]),
            "next_action": None,
        }

    def _reflect_node(self, state: AgentState) -> AgentState:
        if state["final_answer"] is not None:
            return {
                **state,
                "reflect_decision": "end",
                "reflection": "Already finished.",
            }

        # Circuit Breaker for consecutive tool errors
        error_count = 0
        for msg in reversed(state["messages"]):
            content = str(msg.get("content", ""))
            if msg["role"] == "tool" and content.startswith("Tool error:"):
                error_count += 1
            elif msg["role"] == "tool":
                break
        
        if error_count >= 3:
             return {
                **state,
                "messages": state["messages"] + [{"role": "assistant", "content": "Reflection: Circuit breaker triggered due to consecutive tool errors."}],
                "reflection": "Circuit breaker triggered.",
                "reflect_decision": "finish",
                "final_answer": "抱歉，我在调用工具查询信息时遇到了连续错误。可能是您提供的地点/名称不准确，或者服务暂时不可用。请您核实后重试。",
                "last_action": state["last_action"],
             }

        response = self.chat(
            [
                {"role": "system", "content": REFLECT_PROMPT},
                {
                    "role": "user",
                    "content": f"Relevant memory/style context:\n{self._format_reflection_context(state)}",
                },
                {
                    "role": "user",
                    "content": f"Working memory: {self._format_working_memory(state, state['question'])}",
                },
                {"role": "user", "content": f"Question: {state['question']}"},
                {"role": "user", "content": f"Latest action: {state['last_action']}"},
                {"role": "user", "content": f"Observation: {state['observation']}"},
                {"role": "user", "content": f"Steps: {state['steps']}"},
            ],
            temperature=self.config.temperature,
        ).strip()

        parsed = self._parse_json_text(response)
        decision = (parsed.get("decision", "") or "continue").lower()
        reason = parsed.get("reason", "")
        final_answer = parsed.get("final_answer", "").strip() or state["final_answer"]
        self._write_react_trace_log(
            {
                "stage": "reflect",
                "namespace": self.config.memory_namespace,
                "question": state["question"],
                "last_action": list(state["last_action"]) if state["last_action"] else None,
                "observation_preview": state["observation"][:1200],
                "decision": decision,
                "reason": reason,
                "response_preview": response[:1200],
            }
        )

        if "tool error" in state["observation"].lower() and decision == "finish":
            decision = "repair"

        if state["steps"] >= self.config.max_steps and decision == "continue":
            decision = "finish"

        if decision == "finish" and not final_answer:
            final_answer = self._infer_final_answer_from_observation(state["observation"])

        return {
            **state,
            "messages": state["messages"] + [{"role": "assistant", "content": f"Reflection: {response}"}],
            "reflection": reason,
            "reflect_decision": decision,
            "final_answer": final_answer,
            "last_action": state["last_action"],
        }

    def _repair_node(self, state: AgentState) -> AgentState:
        return {
            **state,
            "messages": state["messages"]
            + [
                {
                    "role": "user",
                    "content": "Your last action failed or was invalid. Please reconsider and try again.",
                }
            ],
            "next_action": None,
            "last_action": state["last_action"],
        }

    def _stop_node(self, state: AgentState) -> AgentState:
        return {
            **state,
            "final_answer": state["final_answer"] or "Stopped because max_steps was reached.",
        }

    def _route_after_think(self, state: AgentState) -> Literal["act", "repair", "stop", "end"]:
        if state["final_answer"] is not None:
            return "end"
        if state["steps"] >= self.config.max_steps:
            return "stop"
        if not state["next_action"]:
            return "repair"
        return "act"

    def _route_after_reflect(self, state: AgentState) -> Literal["think", "repair", "stop", "end"]:
        if state["reflect_decision"] == "repair":
            return "repair"
        if state["reflect_decision"] == "finish":
            return "end"
        if state["steps"] >= self.config.max_steps:
            return "stop"
        return "think"

    def _parse_json_text(self, text: str) -> Dict[str, str]:
        try:
            data = json.loads(text)
        except Exception:
            return {}
        return {key: str(value).strip() for key, value in data.items() if isinstance(value, (str, int, float))}

    def _infer_final_answer_from_observation(self, observation: str) -> str:
        lines = [line.strip() for line in observation.splitlines() if line.strip()]
        return lines[0] if lines else "No final answer available."

    def _messages_with_working_memory(self, state: AgentState) -> List[Dict[str, Any]]:
        messages = list(state["messages"])
        if len(messages) < 2:
            return messages

        memory_context = self._format_working_memory(state, state["question"])
        if memory_context == "No working memory.":
            return messages

        memory_message = self.message("system", f"Working memory:\n{memory_context}")
        return [messages[0], *messages[1:-1], memory_message, messages[-1]]

    def _format_working_memory(self, state: AgentState, query: str) -> str:
        if not state["working_memory"]:
            return "No working memory."

        temporary_memory = WorkingMemory(capacity=self.config.working_memory_capacity)
        temporary_memory.load(state["working_memory"])
        return temporary_memory.format_context(query)

    @staticmethod
    def _format_reflection_context(state: AgentState) -> str:
        snippets: List[str] = []
        markers = (
            "Relevant long-term user memories",
            "Window state snapshot",
            "Working memory:",
        )
        for message in state["messages"]:
            if message.get("role") != "system":
                continue
            content = str(message.get("content") or "").strip()
            if not content:
                continue
            if any(marker in content for marker in markers):
                snippets.append(content)
        if not snippets:
            return "No relevant memory/style context."
        text = "\n\n".join(snippets)
        return text[:2000]

    def _execute_tool(self, name: str, tool_input: str) -> str:
        event: Dict[str, object] = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "namespace": self.config.memory_namespace,
            "requested_tool": name,
            "tool_input": tool_input,
            "ok": False,
        }
        try:
            tool = self.tool_registry.find_tool(name)
            self.last_tool_name = tool.name
            self.last_tool_source = tool.source_label()
            self.last_tool_label = f"{tool.name} [{tool.source_label()}]"
            self.tool_call_trace.append(self.last_tool_label)
            event.update(
                {
                    "tool": tool.name,
                    "source": tool.source_label(),
                    "trace_label": self.last_tool_label,
                }
            )
            result = tool.run(tool_input)
            event["ok"] = not str(result).lower().startswith(("tool error:", "mcp tool error:"))
            event["output_preview"] = str(result)[:1200]
            return result
        except Exception as exc:
            event["error"] = f"{type(exc).__name__}: {exc}"
            return f"Tool error: {exc}"
        finally:
            self._write_tool_call_log(event)

    @staticmethod
    def _write_tool_call_log(event: Dict[str, object]) -> None:
        try:
            TOOL_CALL_LOG.parent.mkdir(parents=True, exist_ok=True)
            with TOOL_CALL_LOG.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        except Exception:
            pass

    @staticmethod
    def _write_react_trace_log(event: Dict[str, object]) -> None:
        try:
            event.setdefault("timestamp", datetime.now(timezone.utc).isoformat(timespec="seconds"))
            REACT_TRACE_LOG.parent.mkdir(parents=True, exist_ok=True)
            with REACT_TRACE_LOG.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        except Exception:
            pass
