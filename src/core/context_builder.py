from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Sequence


_CORE_MEMORY_KEYS = {
    "user.name",
    "user.home_address",
    "user.preferred_name",
    "user.reply_prefix",
    "user.preferred_title",
    "user.reply_style",
    "user.language",
    "user.answer_style",
    "user.identity",
    "user.assistant_name",
    "assistant.persona",
}


def _normalize_text(text: str) -> str:
    return " ".join(str(text).split()).strip()


def _approx_chars(text: str) -> int:
    return max(1, len(_normalize_text(text)))


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _status_weight(status: str) -> int:
    value = str(status or "").strip().lower()
    if value == "active":
        return 3
    if value == "stale":
        return 2
    if value == "archived":
        return 1
    return 0


@dataclass(slots=True)
class ContextBlock:
    name: str
    role: str
    content: str
    priority: int
    order: int
    mandatory: bool = False
    original_chars: int = 0
    estimated_chars: int = field(init=False)

    def __post_init__(self) -> None:
        self.role = str(self.role or "system")
        self.content = str(self.content or "").strip()
        self.priority = int(self.priority)
        self.order = int(self.order)
        self.mandatory = bool(self.mandatory)
        self.estimated_chars = _approx_chars(self.content)
        if self.original_chars <= 0:
            self.original_chars = self.estimated_chars


@dataclass(slots=True)
class ContextBuildResult:
    messages: List[Dict[str, str]]
    selected_sections: List[str]
    dropped_sections: List[str]
    estimated_chars: int
    budget_chars: int
    truncated: bool
    should_compress: bool


@dataclass(slots=True)
class ContextBuilderConfig:
    max_total_chars: int = 9000
    max_history_messages: int = 8
    max_memory_items: int = 6
    max_window_summary_chars: int = 1600
    max_working_memory_chars: int = 500
    max_skill_chars: int = 2400
    max_memory_chars: int = 1600
    max_rag_chars: int = 2200
    max_tool_chars: int = 1200
    max_history_chars: int = 3200
    max_tool_list_chars: int = 1200
    min_recent_messages: int = 4


class ContextBuilder:
    """Assemble context blocks with a lightweight budget and priority policy."""

    def __init__(self, config: ContextBuilderConfig | None = None) -> None:
        self.config = config or ContextBuilderConfig()

    def build(
        self,
        *,
        question: str,
        history: List[Dict[str, str]],
        working_memory: str = "",
        compression_state: Mapping[str, Any] | None = None,
        long_term_memories: Sequence[Mapping[str, Any]] | None = None,
        skill_context: str = "",
        rag_context: str = "",
        tool_list: str = "",
        include_tool_list: bool = False,
        route: str = "direct",
    ) -> ContextBuildResult:
        blocks = self._assemble_blocks(
            history=history,
            working_memory=working_memory,
            compression_state=compression_state or {},
            long_term_memories=long_term_memories or [],
            skill_context=skill_context,
            rag_context=rag_context,
            tool_list=tool_list,
            include_tool_list=include_tool_list,
            route=route,
        )
        selected = self._select_blocks(blocks)
        selected.sort(key=lambda block: block.order)

        messages = [{"role": block.role, "content": block.content} for block in selected]
        selected_sections = [block.name for block in selected]
        dropped_sections = [block.name for block in blocks if block.name not in selected_sections]
        estimated_chars = sum(block.estimated_chars for block in selected)
        truncated = any(block.original_chars > block.estimated_chars for block in selected)
        should_compress = len(history) >= max(self.config.max_history_messages * 2, 20) and len(dropped_sections) > 0

        return ContextBuildResult(
            messages=messages,
            selected_sections=selected_sections,
            dropped_sections=dropped_sections,
            estimated_chars=estimated_chars,
            budget_chars=self.config.max_total_chars,
            truncated=truncated,
            should_compress=should_compress,
        )

    def _assemble_blocks(
        self,
        *,
        history: List[Dict[str, str]],
        working_memory: str,
        compression_state: Mapping[str, Any],
        long_term_memories: Sequence[Mapping[str, Any]],
        skill_context: str,
        rag_context: str,
        tool_list: str,
        include_tool_list: bool,
        route: str,
    ) -> List[ContextBlock]:
        blocks: List[ContextBlock] = []
        order = 0

        window_state = self._format_window_state(compression_state)
        if window_state:
            blocks.append(
                ContextBlock(
                    name="window_state",
                    role="system",
                    content=window_state,
                    priority=100,
                    order=order,
                    mandatory=True,
                )
            )
            order += 1

        working_memory_text = self._format_working_memory(working_memory)
        if working_memory_text:
            blocks.append(
                ContextBlock(
                    name="working_memory",
                    role="system",
                    content=working_memory_text,
                    priority=92,
                    order=order,
                    mandatory=True,
                )
            )
            order += 1

        memory_text = self._format_long_term_memories(long_term_memories)
        if memory_text:
            blocks.append(
                ContextBlock(
                    name="global_memory",
                    role="system",
                    content=memory_text,
                    priority=88,
                    order=order,
                )
            )
            order += 1

        skill_text = self._format_skill_context(skill_context)
        if skill_text:
            blocks.append(
                ContextBlock(
                    name="skill_context",
                    role="system",
                    content=skill_text,
                    priority=90,
                    order=order,
                    mandatory=True,
                )
            )
            order += 1

        rag_text = self._format_rag_context(rag_context)
        if rag_text and route != "memory":
            blocks.append(
                ContextBlock(
                    name="rag_context",
                    role="system",
                    content=rag_text,
                    priority=80,
                    order=order,
                )
            )
            order += 1

        if include_tool_list and tool_list.strip():
            blocks.append(
                ContextBlock(
                    name="tool_list",
                    role="system",
                    content=self._truncate_text(
                        "Current tools available in this session:\n" + tool_list.strip(),
                        self.config.max_tool_list_chars,
                    ),
                    priority=76,
                    order=order,
                )
            )
            order += 1

        for index, message in enumerate(self._select_history(history, compression_state), start=order):
            role = str(message.get("role") or "unknown")
            content = _normalize_text(str(message.get("content") or ""))
            if not content:
                continue
            blocks.append(
                ContextBlock(
                    name=f"history_{index}",
                    role=role,
                    content=content,
                    priority=40 + index,
                    order=index,
                )
            )

        return blocks

    def _select_blocks(self, blocks: List[ContextBlock]) -> List[ContextBlock]:
        if not blocks:
            return []

        budget = max(1, int(self.config.max_total_chars))
        ordered = sorted(blocks, key=lambda block: (-block.priority, block.order))
        selected: List[ContextBlock] = []
        used = 0

        for block in ordered:
            cost = block.estimated_chars
            if block.name == "working_memory":
                cost = min(cost, self.config.max_working_memory_chars)
            elif block.name == "window_state":
                cost = min(cost, self.config.max_window_summary_chars)
            elif block.name == "global_memory":
                cost = min(cost, self.config.max_memory_chars)
            elif block.name == "skill_context":
                cost = min(cost, self.config.max_skill_chars)
            elif block.name == "rag_context":
                cost = min(cost, self.config.max_rag_chars)
            elif block.name == "tool_list":
                cost = min(cost, self.config.max_tool_list_chars, self.config.max_tool_chars)
            elif block.name.startswith("history_"):
                cost = min(cost, self.config.max_history_chars)

            if used + cost > budget and not block.mandatory:
                continue

            selected_block = ContextBlock(
                name=block.name,
                role=block.role,
                content=self._truncate_text(block.content, cost),
                priority=block.priority,
                order=block.order,
                mandatory=block.mandatory,
                original_chars=block.estimated_chars,
            )
            selected.append(selected_block)
            used += min(cost, _approx_chars(block.content))

        if not selected:
            return blocks[:1]
        return selected

    def _select_history(
        self,
        history: List[Dict[str, str]],
        compression_state: Mapping[str, Any],
    ) -> List[Dict[str, str]]:
        if not history:
            return []

        compressed = bool(compression_state.get("compressed"))
        start_index = 1 if compressed and history and str(history[0].get("role") or "") == "system" else 0
        recent = history[start_index:]
        if not recent:
            return []

        max_messages = max(self.config.min_recent_messages, int(self.config.max_history_messages))
        return recent[-max_messages:]

    def _format_window_state(self, compression_state: Mapping[str, Any]) -> str:
        if not compression_state:
            return ""

        lines = ["Window state snapshot:"]
        summary = _normalize_text(str(compression_state.get("summary") or ""))
        if summary:
            lines.append(f"- summary: {summary}")

        for key, title in (
            ("important_facts", "important facts"),
            ("user_memory_candidates", "user memory candidates"),
            ("session_state", "session state"),
            ("assistant_capabilities", "assistant capabilities"),
            ("ephemeral_facts", "ephemeral facts"),
            ("open_items", "open items"),
            ("style_notes", "style notes"),
            ("potential_missing_context", "potential missing context"),
        ):
            values = [str(item).strip() for item in compression_state.get(key) or [] if str(item).strip()]
            if not values:
                continue
            lines.append(f"- {title}:")
            lines.extend(f"  - {value}" for value in values)

        scores = compression_state.get("scores")
        if isinstance(scores, Mapping):
            score_bits = []
            for key in ("coverage", "fidelity", "conciseness", "continuity"):
                if key in scores:
                    score_bits.append(f"{key}={scores.get(key)}")
            if score_bits:
                lines.append("- compression scores: " + ", ".join(score_bits))

        recall_rate = compression_state.get("recall_rate")
        if recall_rate is not None:
            lines.append(f"- recall_rate: {recall_rate}")

        return "\n".join(lines)

    def _format_working_memory(self, working_memory: str) -> str:
        cleaned = _normalize_text(working_memory)
        if not cleaned or cleaned == "No working memory.":
            return ""
        return self._truncate_text("Working memory:\n" + cleaned, self.config.max_working_memory_chars)

    def _format_long_term_memories(self, memories: Sequence[Mapping[str, Any]]) -> str:
        if not memories:
            return ""

        seen: set[str] = set()
        rows: List[str] = []
        ranked = sorted(
            (dict(memory) for memory in memories if str(memory.get("text") or "").strip()),
            key=self._memory_score,
            reverse=True,
        )
        for memory in ranked[: max(1, self.config.max_memory_items)]:
            text = _normalize_text(str(memory.get("text") or ""))
            if not text:
                continue
            dedupe_key = (
                str(memory.get("memory_key") or "").strip().lower()
                or text.lower()
            )
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            namespace = str(memory.get("namespace") or "global")
            kind = str(memory.get("kind") or "note")
            status = str(memory.get("status") or "active")
            memory_key = str(memory.get("memory_key") or "")
            key_text = f"|{memory_key}" if memory_key else ""
            rows.append(f"- [{namespace}|{kind}|{status}{key_text}] {text}")

        if not rows:
            return ""
        return self._truncate_text("Relevant long-term user memories:\n" + "\n".join(rows), self.config.max_memory_chars)

    def _format_rag_context(self, rag_context: str) -> str:
        cleaned = _normalize_text(rag_context)
        if not cleaned or cleaned == "No relevant context found.":
            return ""
        return self._truncate_text(
            "Relevant knowledge-base context. You MUST strictly adhere to the information provided here. "
            "If the context contains specific numbers, dates, or policies, use them exactly as written "
            "and DO NOT override them with your pre-trained knowledge or general laws:\n"
            + cleaned,
            self.config.max_rag_chars,
        )

    @staticmethod
    def _format_skill_context(skill_context: str) -> str:
        cleaned = _normalize_text(skill_context)
        if not cleaned:
            return ""
        return ContextBuilder._truncate_text("Active skill context:\n" + cleaned, 2400)

    @staticmethod
    def _truncate_text(text: str, limit: int) -> str:
        cleaned = str(text or "").strip()
        if limit <= 0 or len(cleaned) <= limit:
            return cleaned
        return cleaned[: max(0, limit - 1)].rstrip() + "…"

    @staticmethod
    def _memory_score(memory: Mapping[str, Any]) -> int:
        status_score = _status_weight(str(memory.get("status") or ""))
        temperature = _safe_int(memory.get("temperature"), 0)
        access_count = _safe_int(memory.get("access_count"), 0)
        key = str(memory.get("memory_key") or "").strip().lower()
        pinned_bonus = 120 if key in _CORE_MEMORY_KEYS else 12 if key else 0
        return status_score * 100 + temperature + min(30, access_count * 2) + pinned_bonus
