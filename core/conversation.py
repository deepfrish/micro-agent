from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping

from .agent import ReActAgent
from .context_builder import ContextBuilder
from .framework import AgentConfig
from .llm_client import DeepSeekClient
from .long_term_memory import LongTermMemoryStore
from .compression import WindowCompressor
from .memory_pipeline import ExitMemoryConsolidator, GlobalMemoryRouter, RAGRouter, TurnRouter
from .prompts import DIRECT_REPLY_PROMPT, NAMESPACE_PROMPT
from .skills import SkillRegistry, SkillResolution, SkillRouter
from .task_pipeline import TaskPlanner, TaskSynthesizer

ROUTE_LOG = Path(__file__).resolve().parents[1] / "examples" / "route_log.jsonl"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _normalize_namespace(text: str) -> str:
    cleaned = " ".join(text.split()).strip().strip('"').strip("'")
    cleaned = cleaned.splitlines()[0].strip() if cleaned else ""
    cleaned = re.sub(r"[\/\\:;,*?\"<>|]+", "-", cleaned)
    cleaned = re.sub(r"\s+", "-", cleaned)
    cleaned = re.sub(r"[^\w\u4e00-\u9fff\-]+", "", cleaned)
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-_")
    return cleaned.lower()[:48]


def _fallback_namespace(question: str) -> str:
    tokens = [part for part in re.split(r"[^\w\u4e00-\u9fff]+", question) if part]
    if tokens:
        candidate = "-".join(tokens[:3])
    else:
        candidate = question[:12]

    cleaned = _normalize_namespace(candidate)
    if cleaned:
        return cleaned
    return f"chat-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"


class NamespacePlanner:
    def __init__(self, client: DeepSeekClient) -> None:
        self.client = client

    def derive(self, question: str) -> str:
        try:
            raw = self.client.chat(
                [
                    {"role": "system", "content": NAMESPACE_PROMPT},
                    {"role": "user", "content": question},
                ],
                temperature=0.1,
            ).strip()
        except Exception:
            raw = ""

        candidate = _normalize_namespace(raw)
        return candidate or _fallback_namespace(question)


@dataclass
class ConversationSession:
    namespace: str
    history: List[Dict[str, str]] = field(default_factory=list)
    compression_state: Dict[str, Any] = field(default_factory=dict)
    skill_state: Dict[str, Any] = field(default_factory=dict)
    network_mode: str = "off"
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)
    agent: ReActAgent | None = field(default=None, repr=False, compare=False)

    def ensure_agent(self, base_config: AgentConfig, client: DeepSeekClient) -> ReActAgent:
        if self.agent is None:
            config = replace(base_config, memory_namespace=self.namespace)
            self.agent = ReActAgent(client=client, config=config)
            for message in self.history:
                if message.get("role") == "user":
                    self.agent.working_memory.add(message.get("content", ""))
        return self.agent

    def to_record(self) -> Dict[str, Any]:
        return {
            "namespace": self.namespace,
            "history": self.history,
            "compression_state": self.compression_state,
            "skill_state": self.skill_state,
            "network_mode": self.network_mode,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class ConversationStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or Path(__file__).resolve().parents[1] / "data" / "chat_sessions.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> Dict[str, ConversationSession]:
        if not self.path.exists():
            return {}

        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {}

        if not isinstance(raw, dict):
            return {}

        data = raw.get("sessions") if isinstance(raw.get("sessions"), dict) else raw
        if not isinstance(data, Mapping):
            return {}

        sessions: Dict[str, ConversationSession] = {}
        for namespace, entry in data.items():
            if not isinstance(entry, Mapping):
                continue

            history = entry.get("history") or []
            normalized_history = [
                {"role": str(message.get("role", "")), "content": str(message.get("content", ""))}
                for message in history
                if isinstance(message, Mapping)
            ]

            session_namespace = _normalize_namespace(str(entry.get("namespace") or namespace)) or str(
                entry.get("namespace") or namespace
            ).strip()
            if not session_namespace:
                continue

            sessions[session_namespace] = ConversationSession(
                namespace=session_namespace,
                history=normalized_history,
                compression_state=dict(entry.get("compression_state") or {}) if isinstance(entry.get("compression_state"), Mapping) else {},
                skill_state=dict(entry.get("skill_state") or {}) if isinstance(entry.get("skill_state"), Mapping) else {},
                network_mode=self._normalize_network_mode(str(entry.get("network_mode") or "off")),
                created_at=str(entry.get("created_at") or _now_iso()),
                updated_at=str(entry.get("updated_at") or _now_iso()),
            )
        return sessions

    @staticmethod
    def _normalize_network_mode(value: str) -> str:
        mode = str(value or "off").strip().lower()
        return mode if mode in {"off", "on", "once"} else "off"

    def save(self, sessions: Mapping[str, ConversationSession]) -> None:
        payload = {
            "version": 1,
            "sessions": {namespace: session.to_record() for namespace, session in sessions.items()},
        }
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


class ConversationManager:
    def __init__(
        self,
        config: AgentConfig | None = None,
        client: DeepSeekClient | None = None,
        session_store: ConversationStore | None = None,
        memory_store: LongTermMemoryStore | None = None,
        namespace_planner: NamespacePlanner | None = None,
        rag_router: RAGRouter | None = None,
        memory_router: GlobalMemoryRouter | None = None,
        memory_consolidator: ExitMemoryConsolidator | None = None,
        turn_router: TurnRouter | None = None,
        skill_registry: SkillRegistry | None = None,
        skill_router: SkillRouter | None = None,
        task_planner: TaskPlanner | None = None,
        task_synthesizer: TaskSynthesizer | None = None,
        window_compressor: WindowCompressor | None = None,
    ) -> None:
        self.config = config or AgentConfig()
        self.client = client or DeepSeekClient(model=self.config.model, timeout=self.config.timeout)
        self.session_store = session_store or ConversationStore()
        self.memory_store = memory_store or LongTermMemoryStore()
        self.namespace_planner = namespace_planner or NamespacePlanner(self.client)
        self.rag_router = rag_router or RAGRouter(self.client)
        self.memory_router = memory_router or GlobalMemoryRouter(self.client)
        self.turn_router = turn_router or TurnRouter(self.client)
        self.skill_registry = skill_registry or SkillRegistry.default()
        self.skill_router = skill_router or SkillRouter(self.skill_registry, self.client)
        self.task_planner = task_planner or TaskPlanner(self.client)
        self.task_synthesizer = task_synthesizer or TaskSynthesizer(self.client)
        self.window_compressor = window_compressor or WindowCompressor(self.client)
        self.context_builder = ContextBuilder()
        self.memory_consolidator = memory_consolidator or ExitMemoryConsolidator(
            self.client,
            global_store=self.memory_store,
        )
        self.sessions = self.session_store.load()
        self.active_namespace: str | None = None
        self.pending_new = False

    def known_namespaces(self) -> List[str]:
        return sorted(self.sessions.keys())

    def _namespace_lookup(self) -> Dict[str, str]:
        lookup: Dict[str, str] = {}
        for namespace in self.known_namespaces():
            lookup.setdefault(_normalize_namespace(namespace), namespace)
        return lookup

    def active_session(self) -> ConversationSession | None:
        if self.active_namespace is None:
            return None
        return self.sessions.get(self.active_namespace)

    def get_network_mode(self) -> str:
        session = self.active_session()
        if session is None:
            return "off"
        return self._normalize_network_mode(session.network_mode)

    def set_network_mode(self, mode: str) -> str:
        session = self.active_session()
        if session is None:
            raise ValueError("No active chat window.")

        normalized = self._normalize_network_mode(mode)
        session.network_mode = normalized
        session.updated_at = _now_iso()
        self.session_store.save(self.sessions)
        return normalized

    def start_new_conversation(self) -> None:
        self.pending_new = True
        self.active_namespace = None

    def exit_current_conversation(self, *, background: bool = False) -> Dict[str, Any]:
        result: Dict[str, Any] = {"ok": True, "window_snapshot": False, "global_changes": 0}
        session = self.active_session()
        if session is not None:
            if background:
                job = self.memory_consolidator.build_job(session.namespace, session.history)
                result["window_snapshot"] = bool(job.get("history"))
                result["job"] = job
            else:
                result = self.memory_consolidator.consolidate_window(session.namespace, session.history)
        self.pending_new = False
        self.active_namespace = None
        self.session_store.save(self.sessions)
        return result

    def compress_current_window(self) -> Dict[str, Any]:
        session = self.active_session()
        if session is None:
            return {"ok": False, "error": "No active chat window to compress."}

        result = self.window_compressor.compress(session.namespace, session.history)
        if not result.get("ok"):
            return result
        if result.get("skipped"):
            return result

        compressed_history = result.get("compressed_history")
        if isinstance(compressed_history, list) and compressed_history:
            session.history = [
                {"role": str(message.get("role", "")), "content": str(message.get("content", ""))}
                for message in compressed_history
                if isinstance(message, Mapping)
            ]
            session.compression_state = {
                "compressed": True,
                "last_compressed_at": _now_iso(),
                "last_compressed_message_count": int(result.get("original_message_count", len(session.history))),
                "compressed_message_count": int(result.get("compressed_message_count", len(session.history))),
                "keep_recent_messages": int(result.get("keep_recent_messages", 4)),
                "summary": str(result.get("summary") or ""),
                "important_facts": list(result.get("important_facts") or []),
                "user_memory_candidates": list(result.get("user_memory_candidates") or []),
                "session_state": list(result.get("session_state") or []),
                "assistant_capabilities": list(result.get("assistant_capabilities") or []),
                "ephemeral_facts": list(result.get("ephemeral_facts") or []),
                "open_items": list(result.get("open_items") or []),
                "style_notes": list(result.get("style_notes") or []),
                "potential_missing_context": list(result.get("potential_missing_context") or []),
                "scores": dict(result.get("scores") or {}),
                "recall_rate": result.get("recall_rate"),
                "rule_recall_rate": result.get("rule_recall_rate"),
                "llm_recall": dict(result.get("llm_recall") or {}),
            }
            session.updated_at = _now_iso()
            self.session_store.save(self.sessions)
        return result

    def delete_session(self, namespace: str | None = None) -> ConversationSession:
        target = _normalize_namespace(namespace or self.active_namespace or "")
        if not target:
            raise ValueError("Namespace cannot be empty.")

        actual_namespace = next(
            (name for name in self.sessions if _normalize_namespace(name) == target),
            None,
        )
        if actual_namespace is None:
            raise KeyError(f"Unknown namespace: {target}")

        session = self.sessions.pop(actual_namespace)
        if self.active_namespace == actual_namespace:
            self.active_namespace = None
        self.pending_new = False
        self.session_store.save(self.sessions)
        return session

    def switch(self, namespace: str) -> ConversationSession:
        normalized = _normalize_namespace(namespace)
        if not normalized:
            raise ValueError("Namespace cannot be empty.")

        lookup = self._namespace_lookup()
        actual_namespace = lookup.get(normalized)
        if actual_namespace is None:
            raise KeyError(f"Unknown namespace: {normalized}")

        session = self.sessions.get(actual_namespace)
        if session is None:
            session = ConversationSession(namespace=actual_namespace)
            self.sessions[actual_namespace] = session

        self.active_namespace = actual_namespace
        self.pending_new = False
        self.session_store.save(self.sessions)
        return session

    def ask(self, question: str) -> tuple[ConversationSession, str, bool]:
        question = question.strip()
        if not question:
            raise ValueError("Question cannot be empty.")

        created_new = False
        session: ConversationSession

        if self.pending_new or self.active_namespace is None:
            namespace = self._unique_namespace(self.namespace_planner.derive(question))
            session = self.sessions.get(namespace) or ConversationSession(namespace=namespace)
            self.sessions[namespace] = session
            self.active_namespace = namespace
            self.pending_new = False
            created_new = True
        else:
            session = self.sessions.get(self.active_namespace)
            if session is None:
                session = ConversationSession(namespace=self.active_namespace)
                self.sessions[self.active_namespace] = session

        agent = session.ensure_agent(self.config, self.client)
        agent.reset_turn_metadata()
        agent.working_memory.add(question)
        skill_resolution = self.skill_router.resolve(question, session.history)
        session.skill_state = skill_resolution.to_dict()
        skill_context = skill_resolution.render_context()
        network_mode = self._normalize_network_mode(session.network_mode)
        network_active = network_mode in {"on", "once"}
        core_memories = self.memory_store.pinned(limit=8)
        memory_candidates = self._merge_memories(
            core_memories,
            self.memory_store.search_all(question, limit=8),
        )
        long_term_memories = self._merge_memories(core_memories, self.memory_router.select(question, memory_candidates))
        if long_term_memories:
            long_term_memories = self.memory_store.rank_for_context(question, long_term_memories)
        task_plan = self.task_planner.plan(
            question,
            session.history,
            memory_context=self._format_memory_context(long_term_memories),
            skill_context=skill_context,
            force_network=network_active,
        )
        self._write_route_log(
            {
                "stage": "task_plan",
                "namespace": session.namespace,
                "question": question,
                "network_mode": network_mode,
                "skill": skill_resolution.to_dict(),
                "needs_split": bool(task_plan.get("needs_split")),
                "tasks": task_plan.get("tasks") or [],
                "long_term_memory_count": len(long_term_memories),
            }
        )
        if task_plan.get("needs_split") and len(task_plan.get("tasks") or []) > 1:
            task_results = [
                self._execute_planned_task(session, agent, question, task, skill_resolution)
                for task in task_plan.get("tasks") or []
            ]
            answer = self.task_synthesizer.synthesize(question, session.history, task_results).strip()
            if not answer:
                answer = "我把问题拆开处理了，但暂时没能生成完整回答。"
        else:
            route = (
                {"route": "react", "reason": "network mode forced react"}
                if network_active
                else self.turn_router.route(question, session.history, skill_context=skill_context)
            )
            self._write_route_log(
                {
                    "stage": "turn_route",
                    "namespace": session.namespace,
                    "question": question,
                    "network_mode": network_mode,
                    "skill": skill_resolution.to_dict(),
                    "route": route,
                    "long_term_memory_count": len(long_term_memories),
                }
            )
            rag_context = "" if route.get("route") == "memory" else self.rag_router.retrieve_context(question, session.history)
            include_tool_list = route.get("route") != "react" and self._should_include_tool_list(question)
            context_bundle = self.context_builder.build(
                question=question,
                history=session.history,
                working_memory=agent.working_memory.format_context(question),
                compression_state=session.compression_state,
                long_term_memories=long_term_memories,
                skill_context=skill_context,
                rag_context=rag_context,
                tool_list=agent.tool_registry.get_tools_description(),
                include_tool_list=include_tool_list,
                route=str(route.get("route") or "direct"),
            )

            if route.get("route") == "memory":
                answer = self._direct_answer(
                    question,
                    agent=agent,
                    memory_mode=True,
                    context_messages=self._with_network_context(context_bundle.messages, network_active),
                )
            elif route.get("route") == "react":
                answer = agent.run(
                    question,
                    history_messages=self._with_network_context(context_bundle.messages, network_active),
                    reset_tool_trace=False,
                )
            else:
                answer = self._direct_answer(
                    question,
                    agent=agent,
                    memory_mode=False,
                    context_messages=self._with_network_context(context_bundle.messages, network_active),
                )

        answer = self._prefix_tool_sources(answer, agent)
        if network_mode == "once":
            session.network_mode = "off"

        session.history.extend(
            [
                {"role": "user", "content": question},
                {"role": "assistant", "content": answer},
            ]
        )
        session.updated_at = _now_iso()
        self.session_store.save(self.sessions)
        return session, answer, created_new

    def _direct_answer(
        self,
        question: str,
        *,
        agent: ReActAgent,
        memory_mode: bool,
        context_messages: List[Dict[str, str]] | None = None,
    ) -> str:
        prompt = DIRECT_REPLY_PROMPT
        if memory_mode:
            prompt += (
                "\nThe latest user message is a memory or preference update. "
                "Acknowledge it briefly and naturally."
            )
        messages: List[Dict[str, str]] = [{"role": "system", "content": prompt}]
        if context_messages:
            messages.extend(context_messages)
        messages.append({"role": "user", "content": question})
        return self.client.chat(messages, temperature=self.config.temperature).strip()

    def _execute_planned_task(
        self,
        session: ConversationSession,
        agent: ReActAgent,
        original_question: str,
        task: Mapping[str, Any],
        skill_resolution: SkillResolution,
    ) -> Dict[str, str]:
        task_id = str(task.get("id") or "")
        route = str(task.get("route") or "direct").strip().lower()
        text = str(task.get("text") or "").strip()
        status = str(task.get("status") or "ready").strip().lower()
        blocking_question = str(task.get("blocking_question") or "").strip()
        skill_context = skill_resolution.render_context()

        if status == "blocked":
            self._write_route_log(
                {
                    "stage": "subtask_blocked",
                    "namespace": session.namespace,
                    "original_question": original_question,
                    "task": dict(task),
                }
            )
            return {
                "id": task_id,
                "route": route or "direct",
                "status": "blocked",
                "task": text,
                "output": blocking_question or str(task.get("reason") or "This subtask needs more information."),
            }

        if route not in {"memory", "direct", "react"}:
            route = self.turn_router.route(
                text or original_question,
                session.history,
                skill_context=skill_context,
            ).get("route", "direct")
        self._write_route_log(
            {
                "stage": "subtask_route",
                "namespace": session.namespace,
                "original_question": original_question,
                "task_id": task_id,
                "task_text": text,
                "route": route,
            }
        )

        core_memories = self.memory_store.pinned(limit=8)
        memory_candidates = self._merge_memories(
            core_memories,
            self.memory_store.search_all(text or original_question, limit=8),
        )
        long_term_memories = self._merge_memories(
            core_memories,
            self.memory_router.select(text or original_question, memory_candidates),
        )
        if long_term_memories:
            long_term_memories = self.memory_store.rank_for_context(text or original_question, long_term_memories)
        rag_context = self.rag_router.retrieve_context(text or original_question, session.history)
        include_tool_list = route != "react" and self._should_include_tool_list(text or original_question)
        context_bundle = self.context_builder.build(
            question=text or original_question,
            history=session.history,
            working_memory=agent.working_memory.format_context(text or original_question),
            compression_state=session.compression_state,
            long_term_memories=long_term_memories,
            skill_context=skill_context,
            rag_context=rag_context,
            tool_list=agent.tool_registry.get_tools_description(),
            include_tool_list=include_tool_list,
            route=route,
        )

        if route == "react":
            output = agent.run(text or original_question, history_messages=context_bundle.messages, reset_tool_trace=False)
        else:
            output = self._direct_answer(
                text or original_question,
                agent=agent,
                memory_mode=route == "memory",
                context_messages=context_bundle.messages,
            )

        return {
            "id": task_id,
            "route": route,
            "status": "done",
            "task": text or original_question,
            "output": output,
        }

    @staticmethod
    def _should_include_tool_list(question: str) -> bool:
        text = question.strip().lower()
        if not text:
            return False

        keywords = (
            "你能做什么",
            "你会什么",
            "你有什么工具",
            "有什么工具",
            "可以调用什么",
            "能调用什么",
            "能做什么",
            "你的能力",
            "工具列表",
            "功能列表",
            "available tools",
            "what can you do",
            "tools",
            "capabilities",
        )
        return any(keyword in text for keyword in keywords)

    def _build_context_messages(
        self,
        long_term_memories: List[Mapping[str, Any]],
        rag_context: str,
    ) -> List[Dict[str, str]]:
        messages: List[Dict[str, str]] = []
        if long_term_memories:
            memory_lines = [
                f"- [{memory.get('namespace', 'default')}|{memory.get('kind', 'note')}] {memory.get('text', '')}"
                for memory in long_term_memories
                if memory.get("text")
            ]
            if memory_lines:
                messages.append(
                    {
                        "role": "system",
                        "content": "Relevant long-term user memories:\n" + "\n".join(memory_lines),
                    }
                )

        if rag_context:
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "Relevant knowledge-base context. Use it when it helps answer the user, "
                        "and do not invent facts beyond it:\n"
                        f"{rag_context}"
                    ),
                }
            )
        return messages

    @staticmethod
    def _format_memory_context(memories: List[Mapping[str, Any]]) -> str:
        if not memories:
            return "No relevant long-term memories."

        lines: List[str] = []
        for memory in memories[:8]:
            text = str(memory.get("text") or "").strip()
            if not text:
                continue
            key = str(memory.get("memory_key") or "").strip()
            key_text = f" | {key}" if key else ""
            namespace = str(memory.get("namespace") or "global").strip()
            kind = str(memory.get("kind") or "note").strip()
            lines.append(f"- [{namespace}|{kind}{key_text}] {text}")
        return "\n".join(lines) or "No relevant long-term memories."

    @staticmethod
    def _with_network_context(
        messages: List[Dict[str, str]],
        network_active: bool,
    ) -> List[Dict[str, str]]:
        if not network_active:
            return messages
        hint = {
            "role": "system",
            "content": (
                "Network mode is active for this chat window. Prefer ReAct tool use for this turn, "
                "especially freeweb MCP tools such as web_search, search_and_browse, browse_page, "
                "smart_browse, and deep_search when the user asks for public web content, current news, "
                "article links, traffic updates, or recent information. If a browser-backed tool fails "
                "or returns unreadable pages, fall back to web_search and use the best reliable snippets "
                "instead of claiming that web access is unavailable."
            ),
        }
        return [*messages, hint]

    @staticmethod
    def _prefix_tool_sources(answer: str, agent: ReActAgent) -> str:
        trace = list(getattr(agent, "tool_call_trace", []) or [])
        if not trace:
            return answer
        if answer.lstrip().startswith("工具调用:"):
            return answer
        seen: set[str] = set()
        labels: List[str] = []
        for label in trace:
            if not label or label in seen:
                continue
            seen.add(label)
            labels.append(label)
        if not labels:
            return answer
        tool_lines = "\n".join(f"- {label}" for label in labels)
        return f"工具调用:\n{tool_lines}\n\n{answer}"

    @staticmethod
    def _merge_memories(*groups: List[Mapping[str, Any]]) -> List[Dict[str, Any]]:
        merged: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for group in groups:
            for memory in group:
                text = str(memory.get("text") or "").strip()
                if not text:
                    continue
                memory_key = str(memory.get("memory_key") or "").strip().lower()
                memory_id = str(memory.get("id") or "").strip()
                dedupe_key = memory_key or memory_id or text.lower()
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                merged.append(dict(memory))
        return merged

    @staticmethod
    def _normalize_network_mode(mode: str) -> str:
        normalized = str(mode or "off").strip().lower()
        return normalized if normalized in {"off", "on", "once"} else "off"

    @staticmethod
    def _write_route_log(event: Mapping[str, Any]) -> None:
        try:
            payload = dict(event)
            payload.setdefault("timestamp", _now_iso())
            ROUTE_LOG.parent.mkdir(parents=True, exist_ok=True)
            with ROUTE_LOG.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def _unique_namespace(self, base: str) -> str:
        candidate = _normalize_namespace(base)
        if not candidate:
            candidate = _fallback_namespace(base)

        existing = set(self._namespace_lookup().keys())
        if candidate not in existing:
            return candidate

        index = 2
        while True:
            next_candidate = f"{candidate}-{index}"
            if next_candidate not in existing:
                return next_candidate
            index += 1
