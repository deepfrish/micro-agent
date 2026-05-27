from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping

from .long_term_memory import DEFAULT_GLOBAL_NAMESPACE, LongTermMemoryStore
from .prompts import (
    GLOBAL_MEMORY_CONSOLIDATION_PROMPT,
    GLOBAL_MEMORY_ROUTE_PROMPT,
    RAG_ROUTE_PROMPT,
    TURN_ROUTE_PROMPT,
    WINDOW_MEMORY_SUMMARY_PROMPT,
)
from .rag import KnowledgeBase
from .window_memory import WindowMemoryStore


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _parse_json_object(text: str) -> Dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        data = json.loads(cleaned)
    except Exception:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            return {}
        try:
            data = json.loads(match.group(0))
        except Exception:
            return {}

    return data if isinstance(data, dict) else {}


def _history_tail(history: List[Dict[str, str]], limit: int = 6) -> str:
    tail = history[-limit:]
    lines = []
    if history:
        first = history[0]
        first_role = str(first.get("role", ""))
        first_content = str(first.get("content", "")).strip()
        if first_role == "system" and first_content.startswith("Compressed window summary:"):
            lines.append(f"{first_role}: {first_content}")
    for message in tail:
        role = message.get("role", "unknown")
        content = message.get("content", "")
        if content:
            if lines and role == "system" and str(content).strip().startswith("Compressed window summary:"):
                continue
            lines.append(f"{role}: {content}")
    return "\n".join(lines) or "No conversation history."


class RAGRouter:
    def __init__(
        self,
        client: Any,
        kb_root: Path | None = None,
        *,
        top_k: int = 3,
    ) -> None:
        self.client = client
        self.kb_root = kb_root or PROJECT_ROOT / "knowledge_base"
        self.top_k = max(1, top_k)
        self._knowledge_base: KnowledgeBase | None = None

    def retrieve_context(self, question: str, history: List[Dict[str, str]]) -> str:
        decision = self._decide(question, history)
        if not decision.get("need_rag"):
            return ""

        query = str(decision.get("query") or question).strip()
        knowledge_base = self._load_knowledge_base()
        if knowledge_base.chunk_count() == 0:
            return ""

        context = knowledge_base.format_context(query, top_k=self.top_k)
        if context == "No relevant context found.":
            return ""
        return context

    def _decide(self, question: str, history: List[Dict[str, str]]) -> Dict[str, Any]:
        try:
            raw = self.client.chat(
                [
                    {"role": "system", "content": RAG_ROUTE_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            f"Conversation history:\n{_history_tail(history)}\n\n"
                            f"Current question:\n{question}"
                        ),
                    },
                ],
                temperature=0.0,
            )
            data = _parse_json_object(raw)
        except Exception:
            data = {}

        if isinstance(data.get("need_rag"), bool):
            data["query"] = str(data.get("query") or question)
            return data

        return self._fallback_decision(question)

    def _fallback_decision(self, question: str) -> Dict[str, Any]:
        keywords = (
            "\u6587\u6863",
            "\u77e5\u8bc6\u5e93",
            "\u8d44\u6599",
            "\u6587\u7ae0",
            "\u7b2c",
            "\u7ae0",
            "chapter",
            "rag",
            "knowledge",
            "readme",
        )
        lowered = question.lower()
        need_rag = any(keyword in lowered for keyword in keywords)
        return {"need_rag": need_rag, "query": question, "reason": "fallback keyword route"}

    def _load_knowledge_base(self) -> KnowledgeBase:
        if self._knowledge_base is None:
            self._knowledge_base = KnowledgeBase.from_directory(self.kb_root)
        return self._knowledge_base


class TurnRouter:
    """LLM-assisted turn router for deciding whether to use ReAct."""

    def __init__(self, client: Any) -> None:
        self.client = client

    def route(self, question: str, history: List[Dict[str, str]]) -> Dict[str, Any]:
        try:
            raw = self.client.chat(
                [
                    {"role": "system", "content": TURN_ROUTE_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            f"Conversation history:\n{_history_tail(history)}\n\n"
                            f"Current question:\n{question}"
                        ),
                    },
                ],
                temperature=0.0,
            )
            data = _parse_json_object(raw)
        except Exception:
            data = {}

        route = str(data.get("route") or "").strip().lower()
        if route in {"memory", "direct", "react"}:
            fallback = self._fallback_route(question, route)
            fallback["reason"] = str(data.get("reason") or fallback["reason"])
            return fallback
        return self._fallback_route(question)

    def _fallback_route(self, question: str, route: str | None = None) -> Dict[str, Any]:
        lowered = question.lower()
        memory_tokens = (
            "remember",
            "\u8bb0\u4f4f",
            "\u4ee5\u540e",
            "\u79f0\u547c",
            "\u53eb\u6211",
            "\u522b\u518d",
            "\u6539\u6210",
            "\u540d\u5b57",
            "\u59d3",
            "\u56de\u590d\u98ce\u683c",
            "\u56de\u590d\u524d\u7f00",
            "\u504f\u597d",
        )
        react_tokens = (
            "weather",
            "\u5929\u6c14",
            "\u9644\u8fd1",
            "\u5468\u8fb9",
            "\u5546\u573a",
            "\u9152\u5e97",
            "\u5730\u56fe",
            "\u8def\u7ebf",
            "\u8ba1\u7b97",
            "\u7b97",
            "\u51e0\u70b9",
            "\u65e5\u671f",
            "\u65f6\u95f4",
            "now",
            "search",
            "news",
            "article",
            "link",
            "url",
            "\u641c\u7d22",
            "\u67e5\u627e",
            "\u67e5\u770b",
            "\u70ed\u70b9",
            "\u5feb\u62a5",
            "\u65b0\u95fb",
            "\u65f6\u4e8b",
            "\u8d44\u8baf",
            "\u5168\u6587",
            "\u94fe\u63a5",
            "\u6587\u7ae0",
            "\u7f51\u9875",
            "\u4e0a\u7f51",
            "\u6700\u65b0",
            "\u5b9e\u65f6",
            "\u4ea4\u901a",
            "\u8def\u51b5",
            "\u62a5\u9053",
        )
        react_hit = any(token in lowered for token in react_tokens)
        if any(token in lowered for token in memory_tokens):
            return {"route": "memory", "reason": "keyword memory route"}
        if route == "react":
            return {"route": "react", "reason": "llm route"}
        if route == "direct" and react_hit:
            return {"route": "react", "reason": "keyword tool route"}
        if route:
            return {"route": route, "reason": "llm route"}
        if react_hit:
            return {"route": "react", "reason": "keyword tool route"}
        return {"route": "direct", "reason": "default direct route"}


class GlobalMemoryRouter:
    """LLM-assisted selector for global memories to inject into a turn."""

    def __init__(self, client: Any, *, max_candidates: int = 16, fallback_limit: int = 8) -> None:
        self.client = client
        self.max_candidates = max(1, int(max_candidates))
        self.fallback_limit = max(1, int(fallback_limit))

    def select(self, question: str, memories: List[Mapping[str, Any]]) -> List[Dict[str, Any]]:
        candidates = self._rank_candidates(question, memories)
        if not candidates:
            return []

        candidates = candidates[: self.max_candidates]
        id_to_memory = {self._memory_id(index, memory): memory for index, memory in enumerate(candidates)}
        try:
            raw = self.client.chat(
                [
                    {"role": "system", "content": GLOBAL_MEMORY_ROUTE_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            f"Current question:\n{question}\n\n"
                            f"Candidate memories:\n{self._format_candidates(id_to_memory)}"
                        ),
                    },
                ],
                temperature=0.0,
            )
            data = _parse_json_object(raw)
        except Exception:
            return [dict(memory) for memory in candidates[: self.fallback_limit]]

        selected_ids = data.get("selected_ids")
        if not isinstance(selected_ids, list):
            return [dict(memory) for memory in candidates[: self.fallback_limit]]

        selected: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for value in selected_ids:
            memory_id = str(value)
            memory = id_to_memory.get(memory_id)
            if memory is None or memory_id in seen:
                continue
            seen.add(memory_id)
            selected.append(dict(memory))
        return selected

    def _rank_candidates(self, question: str, memories: List[Mapping[str, Any]]) -> List[Dict[str, Any]]:
        candidates = [dict(memory) for memory in memories if memory.get("text")]
        if not candidates:
            return []

        terms = self._build_terms(question)
        candidates.sort(key=lambda memory: (-self._candidate_score(memory, terms), str(memory.get("id") or "")))
        return candidates

    def _candidate_score(self, memory: Mapping[str, Any], terms: List[str]) -> int:
        status = str(memory.get("status") or "active").strip().lower()
        status_score = {
            "active": 300,
            "stale": 220,
            "archived": 120,
            "deleted": 0,
        }.get(status, 160)

        key = str(memory.get("memory_key") or "").strip().lower()
        text = str(memory.get("text") or "").lower()
        namespace = str(memory.get("namespace") or "").lower()
        kind = str(memory.get("kind") or "note").lower()

        match_score = 0
        for term in terms:
            if not term:
                continue
            if term in text:
                match_score += 24
            if term in key:
                match_score += 28
            if term in namespace:
                match_score += 10

        temperature = self._safe_int(memory.get("temperature"))
        access_count = self._safe_int(memory.get("access_count"))
        recency_score = self._recency_score(memory)
        pinned_bonus = 28 if key in {"user.name", "user.reply_prefix", "user.preferred_title", "user.language", "user.answer_style", "user.identity"} else 0
        kind_bonus = 12 if kind in {"profile", "preference"} else 0

        return status_score + match_score + temperature + min(30, access_count * 2) + recency_score + pinned_bonus + kind_bonus

    @staticmethod
    def _build_terms(query: str) -> List[str]:
        cleaned = str(query or "").strip()
        if not cleaned:
            return []

        terms: List[str] = []
        for token in cleaned.split():
            token = token.strip().lower()
            if token and token not in terms:
                terms.append(token)

        for char in cleaned.lower():
            if char.isalnum() or "\u4e00" <= char <= "\u9fff":
                if char not in terms:
                    terms.append(char)
        return terms

    @staticmethod
    def _memory_id(index: int, memory: Mapping[str, Any]) -> str:
        return str(memory.get("id") or f"candidate-{index}")

    @staticmethod
    def _format_candidates(id_to_memory: Mapping[str, Mapping[str, Any]]) -> str:
        lines = []
        for memory_id, memory in id_to_memory.items():
            key = str(memory.get("memory_key") or "")
            key_text = f" key={key}" if key else ""
            lines.append(
                f"- id={memory_id} [{memory.get('status', 'active')}|{memory.get('kind', 'note')}{key_text}] "
                f"{memory.get('text', '')}"
            )
        return "\n".join(lines) or "No memories."

    @staticmethod
    def _safe_int(value: Any) -> int:
        try:
            return int(value)
        except Exception:
            return 0

    @staticmethod
    def _recency_score(memory: Mapping[str, Any]) -> int:
        stamp = str(
            memory.get("last_accessed_at")
            or memory.get("updated_at")
            or memory.get("created_at")
            or ""
        ).strip()
        if not stamp:
            return 0
        try:
            parsed = datetime.fromisoformat(stamp)
        except Exception:
            return 0

        age_days = max(0.0, (datetime.now(timezone.utc) - parsed).total_seconds() / 86400.0)
        return max(0, int(24 - min(24.0, age_days * 0.8)))


class ExitMemoryConsolidator:
    """Two-stage memory consolidation that runs when leaving a chat window."""

    def __init__(
        self,
        client: Any,
        window_store: WindowMemoryStore | None = None,
        global_store: LongTermMemoryStore | None = None,
        *,
        global_namespace: str = DEFAULT_GLOBAL_NAMESPACE,
    ) -> None:
        self.client = client
        self.window_store = window_store or WindowMemoryStore()
        self.global_store = global_store or LongTermMemoryStore()
        self.global_namespace = global_namespace

    def consolidate_window(self, namespace: str, history: List[Dict[str, str]]) -> Dict[str, Any]:
        return self.consolidate_job(self.build_job(namespace, history))

    def build_job(self, namespace: str, history: List[Dict[str, str]]) -> Dict[str, Any]:
        return {
            "version": 1,
            "namespace": str(namespace or "").strip(),
            "history": [dict(message) for message in history if isinstance(message, Mapping)],
        }

    def consolidate_job(self, job: Mapping[str, Any]) -> Dict[str, Any]:
        namespace = str(job.get("namespace") or "").strip()
        history = [dict(message) for message in job.get("history") or [] if isinstance(message, Mapping)]
        if not history:
            return {"ok": True, "window_snapshot": False, "global_changes": 0, "reason": "empty history"}

        try:
            window_result = self._summarize_window(namespace, history)
        except Exception as exc:
            return {"ok": False, "window_snapshot": False, "global_changes": 0, "error": str(exc)}

        snapshot = self.window_store.add_snapshot(
            namespace,
            summary=str(window_result.get("summary") or ""),
            memories=self._normalize_memories(window_result.get("memories")),
            message_count=len(history),
        )

        try:
            operations = self._consolidate_global(snapshot)
            applied = self._apply_operations(operations)
        except Exception as exc:
            return {
                "ok": False,
                "window_snapshot": True,
                "global_changes": 0,
                "error": str(exc),
                "snapshot_id": snapshot.get("id"),
            }

        return {
            "ok": True,
            "window_snapshot": True,
            "window_memories": len(snapshot.get("memories") or []),
            "global_changes": applied,
            "snapshot_id": snapshot.get("id"),
        }

    def _summarize_window(self, namespace: str, history: List[Dict[str, str]]) -> Dict[str, Any]:
        raw = self.client.chat(
            [
                {"role": "system", "content": WINDOW_MEMORY_SUMMARY_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Namespace: {namespace}\n\n"
                        f"Conversation history:\n{self._format_history(history)}"
                    ),
                },
            ],
            temperature=0.0,
        )
        data = _parse_json_object(raw)
        if not isinstance(data.get("memories"), list):
            data["memories"] = []
        data["summary"] = str(data.get("summary") or "")
        return data

    def _consolidate_global(self, snapshot: Mapping[str, Any]) -> List[Dict[str, Any]]:
        current_entries = self.global_store.get_entries(self.global_namespace, include_archived=True)
        raw = self.client.chat(
            [
                {"role": "system", "content": GLOBAL_MEMORY_CONSOLIDATION_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Current global memories:\n{self._format_entries(current_entries)}\n\n"
                        f"New window memory snapshot:\n{json.dumps(snapshot, ensure_ascii=False, indent=2)}"
                    ),
                },
            ],
            temperature=0.0,
        )
        data = _parse_json_object(raw)
        operations = data.get("operations")
        if not isinstance(operations, list):
            return []
        return [operation for operation in (self._normalize_operation(item) for item in operations) if operation]

    def _apply_operations(self, operations: List[Dict[str, Any]]) -> int:
        applied = 0
        for operation in operations:
            action = operation["action"]
            if action == "archive":
                changed = self.global_store.archive(
                    self.global_namespace,
                    memory_key=operation["memory_key"] or None,
                    text=operation["text"] or None,
                )
                applied += changed
                continue
            if action == "append":
                record = self.global_store.add_record(
                    self.global_namespace,
                    operation["text"],
                    kind=operation["kind"],
                    confidence=operation["confidence"],
                    action="append",
                )
            else:
                record = self.global_store.upsert(
                    self.global_namespace,
                    operation["text"],
                    kind=operation["kind"],
                    confidence=operation["confidence"],
                    memory_key=operation["memory_key"] or None,
                )
            if record is not None:
                applied += 1
        return applied

    @staticmethod
    def _format_history(history: List[Dict[str, str]], limit: int = 60) -> str:
        lines = []
        for message in history[-limit:]:
            role = str(message.get("role") or "unknown")
            content = str(message.get("content") or "").strip()
            if content:
                lines.append(f"{role}: {content}")
        return "\n".join(lines) or "No conversation history."

    @staticmethod
    def _format_entries(entries: List[Mapping[str, Any]]) -> str:
        if not entries:
            return "No memories."
        lines = []
        for entry in entries:
            key = str(entry.get("memory_key") or "")
            key_text = f" key={key}" if key else ""
            lines.append(
                f"- [{entry.get('status', 'active')}|{entry.get('kind', 'note')}{key_text}] "
                f"{entry.get('text', '')}"
            )
        return "\n".join(lines)

    @classmethod
    def _normalize_memories(cls, value: Any) -> List[Dict[str, Any]]:
        if not isinstance(value, list):
            return []
        memories: List[Dict[str, Any]] = []
        for item in value:
            operation = cls._normalize_operation(item)
            if operation is not None:
                memories.append(operation)
        return memories

    @staticmethod
    def _normalize_operation(item: Any) -> Dict[str, Any] | None:
        if not isinstance(item, Mapping):
            return None
        text = str(item.get("text") or "").strip()
        if not text:
            return None
        action = str(item.get("action") or "append").strip().lower()
        if action == "delete":
            action = "archive"
        if action not in {"upsert", "append", "archive"}:
            action = "append"
        kind = str(item.get("kind") or "note").strip().lower()
        if kind not in {"profile", "preference", "goal", "project", "note"}:
            kind = "note"
        memory_key = str(item.get("memory_key") or "").strip().lower().replace(" ", "-")
        confidence = item.get("confidence")
        try:
            confidence = float(confidence) if confidence is not None else None
        except Exception:
            confidence = None
        return {
            "action": action,
            "memory_key": memory_key,
            "kind": kind,
            "text": text,
            "confidence": confidence,
        }
