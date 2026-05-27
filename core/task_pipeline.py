from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping

from .prompts import TASK_SPLIT_PROMPT, TASK_SYNTHESIS_PROMPT


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


@dataclass(slots=True)
class PlannedTask:
    id: str
    route: str
    text: str
    status: str = "ready"
    blocking_question: str = ""
    reason: str = ""

    def to_dict(self) -> Dict[str, str]:
        return {
            "id": self.id,
            "route": self.route,
            "status": self.status,
            "text": self.text,
            "blocking_question": self.blocking_question,
            "reason": self.reason,
        }


class TaskPlanner:
    """LLM-assisted splitter for multi-part user turns."""

    def __init__(self, client: Any, *, max_tasks: int = 3) -> None:
        self.client = client
        self.max_tasks = max(1, int(max_tasks))

    def plan(
        self,
        question: str,
        history: List[Dict[str, str]],
        memory_context: str = "",
        *,
        force_network: bool = False,
    ) -> Dict[str, Any]:
        if force_network:
            return {
                "needs_split": False,
                "reason": "network mode forced react",
                "tasks": [PlannedTask(id="1", route="react", text=question).to_dict()],
            }

        try:
            user_content = (
                f"Conversation history:\n{_history_tail(history)}\n\n"
                f"Relevant long-term memories:\n{memory_context.strip() or 'No relevant long-term memories.'}\n\n"
                f"Current question:\n{question}"
            )
            raw = self.client.chat(
                [
                    {"role": "system", "content": TASK_SPLIT_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.0,
            )
            data = _parse_json_object(raw)
            plan = self._normalize_plan(question, data)
            if plan:
                return plan
        except Exception:
            pass
        return self._fallback_plan(question)

    def _normalize_plan(self, question: str, data: Mapping[str, Any]) -> Dict[str, Any] | None:
        tasks = data.get("tasks")
        if not isinstance(tasks, list):
            return None

        normalized_tasks: List[Dict[str, str]] = []
        for index, item in enumerate(tasks[: self.max_tasks], start=1):
            task = self._normalize_task(item, index)
            if task is not None:
                normalized_tasks.append(task.to_dict())

        if not normalized_tasks:
            return None

        needs_split = bool(data.get("needs_split"))
        if len(normalized_tasks) > 1:
            needs_split = True

        return {
            "needs_split": needs_split,
            "reason": str(data.get("reason") or ""),
            "tasks": normalized_tasks,
        }

    def _normalize_task(self, item: Any, index: int) -> PlannedTask | None:
        if not isinstance(item, Mapping):
            return None

        text = str(item.get("text") or "").strip()
        if not text:
            return None

        route = str(item.get("route") or "direct").strip().lower()
        if route not in {"memory", "direct", "react"}:
            route = "direct"

        status = str(item.get("status") or "ready").strip().lower()
        if status not in {"ready", "blocked"}:
            status = "ready"

        blocking_question = str(item.get("blocking_question") or "").strip()
        reason = str(item.get("reason") or "").strip()
        task_id = str(item.get("id") or index)
        return PlannedTask(
            id=task_id,
            route=route,
            text=text,
            status=status,
            blocking_question=blocking_question,
            reason=reason,
        )

    def _fallback_plan(self, question: str) -> Dict[str, Any]:
        parts = self._split_question(question)
        if len(parts) <= 1:
            return {
                "needs_split": False,
                "reason": "fallback single task",
                "tasks": [PlannedTask(id="1", route="direct", text=question).to_dict()],
            }

        tasks: List[Dict[str, str]] = []
        for index, part in enumerate(parts[: self.max_tasks], start=1):
            route = self._guess_route(part)
            status = "ready"
            blocking_question = ""
            if "公交" in part and not any(token in part for token in ("从", "出发", "起点", "哪里")):
                status = "blocked"
                blocking_question = "你从哪里出发？我需要出发地才能查公交路线。"
            tasks.append(
                PlannedTask(
                    id=str(index),
                    route=route,
                    text=part,
                    status=status,
                    blocking_question=blocking_question,
                    reason="fallback split",
                ).to_dict()
            )

        return {"needs_split": True, "reason": "fallback split", "tasks": tasks}

    @staticmethod
    def _split_question(question: str) -> List[str]:
        raw_parts = re.split(r"[，,；;。]\s*|(?:然后|以及|并且|顺便|同时|还有)", question)
        parts = [part.strip() for part in raw_parts if part and part.strip()]
        return parts or [question.strip()]

    @staticmethod
    def _guess_route(text: str) -> str:
        lowered = text.lower()
        if any(token in lowered for token in ("记住", "以后", "称呼", "名字", "偏好", "告诉我", "改成")):
            return "memory"
        if any(
            token in lowered
            for token in ("天气", "附近", "周边", "商场", "酒店", "地图", "路线", "公交", "计算", "日期", "时间", "查查", "美食", "餐", "店", "推荐", "吃点")
        ):
            return "react"
        return "direct"


class TaskSynthesizer:
    """LLM-assisted combiner for multiple task outputs."""

    def __init__(self, client: Any) -> None:
        self.client = client

    def synthesize(
        self,
        question: str,
        history: List[Dict[str, str]],
        task_results: List[Mapping[str, Any]],
    ) -> str:
        if len(task_results) <= 1:
            return str(task_results[0].get("output") or "").strip() if task_results else ""

        try:
            raw = self.client.chat(
                [
                    {"role": "system", "content": TASK_SYNTHESIS_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            f"Conversation history:\n{_history_tail(history)}\n\n"
                            f"Original question:\n{question}\n\n"
                            f"Task results:\n{json.dumps(task_results, ensure_ascii=False, indent=2)}"
                        ),
                    },
                ],
                temperature=0.2,
            )
            answer = raw.strip()
            if answer:
                return answer
        except Exception:
            pass

        lines = []
        for item in task_results:
            task_id = str(item.get("id") or "")
            status = str(item.get("status") or "done")
            output = str(item.get("output") or "").strip()
            if not output:
                continue
            prefix = f"{task_id}. " if task_id else ""
            if status == "blocked":
                lines.append(f"{prefix}{output}")
            else:
                lines.append(f"{prefix}{output}")
        return "\n".join(lines).strip()
