from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping

from .memory import extract_key_facts
from .prompts import (
    WINDOW_COMPRESSION_EVALUATION_PROMPT,
    WINDOW_FACT_RECALL_PROMPT,
    WINDOW_COMPRESSION_PROMPT,
    WINDOW_MISSING_POINT_VERIFICATION_PROMPT,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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


def _format_history(history: List[Dict[str, str]], limit: int | None = None) -> str:
    selected = history if limit is None else history[-max(1, limit) :]
    lines = []
    for message in selected:
        role = str(message.get("role") or "unknown")
        content = str(message.get("content") or "").strip()
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines) or "No conversation history."


def _normalize_text(text: str) -> str:
    return " ".join(str(text).split()).strip()


def _safe_score(value: Any) -> int:
    try:
        score = int(value)
    except Exception:
        return 1
    return max(1, min(5, score))


class WindowCompressor:
    def __init__(
        self,
        client: Any,
        *,
        log_path: Path | None = None,
        min_window_messages_to_compress: int = 20,
        min_keep_messages: int = 4,
        max_keep_messages: int = 8,
    ) -> None:
        self.client = client
        self.log_path = log_path or Path(__file__).resolve().parents[2] / "examples" / "compress_log.jsonl"
        self.min_window_messages_to_compress = max(1, int(min_window_messages_to_compress))
        self.min_keep_messages = max(2, int(min_keep_messages))
        self.max_keep_messages = max(self.min_keep_messages, int(max_keep_messages))
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def compress(self, namespace: str, history: List[Dict[str, str]]) -> Dict[str, Any]:
        if not history:
            return {"ok": False, "reason": "empty history"}

        original_history = [dict(message) for message in history if isinstance(message, Mapping)]
        if len(original_history) < self.min_window_messages_to_compress:
            return {
                "ok": True,
                "skipped": True,
                "reason": (
                    f"Window too short to compress. Need at least {self.min_window_messages_to_compress} messages, "
                    f"got {len(original_history)}."
                ),
                "current_message_count": len(original_history),
                "threshold": self.min_window_messages_to_compress,
            }

        original_text = _format_history(original_history)
        original_facts = self._extract_facts(original_text)

        try:
            raw = self.client.chat(
                [
                    {"role": "system", "content": WINDOW_COMPRESSION_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            f"Namespace: {namespace}\n\n"
                            f"Conversation history:\n{original_text}"
                        ),
                    },
                ],
                temperature=0.0,
            )
            data = _parse_json_object(raw)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        summary = _normalize_text(str(data.get("summary") or ""))
        important_facts = [str(item).strip() for item in data.get("important_facts") or [] if str(item).strip()]
        open_items = [str(item).strip() for item in data.get("open_items") or [] if str(item).strip()]
        style_notes = [str(item).strip() for item in data.get("style_notes") or [] if str(item).strip()]
        keep_recent_messages = self._normalize_keep_count(data.get("keep_recent_messages"))
        if not summary:
            summary = "窗口压缩摘要为空。"

        user_memory_candidates = [str(item).strip() for item in data.get("user_memory_candidates") or [] if str(item).strip()]
        session_state = [str(item).strip() for item in data.get("session_state") or [] if str(item).strip()]
        assistant_capabilities = [str(item).strip() for item in data.get("assistant_capabilities") or [] if str(item).strip()]
        ephemeral_facts = [str(item).strip() for item in data.get("ephemeral_facts") or [] if str(item).strip()]

        compressed_text_for_eval = self._build_summary_message(
            summary,
            important_facts,
            open_items,
            style_notes,
            potential_missing_context=[],
            user_memory_candidates=user_memory_candidates,
            session_state=session_state,
            assistant_capabilities=assistant_capabilities,
            ephemeral_facts=ephemeral_facts,
        )
        evaluation = self._evaluate_compression(namespace, original_text, summary, compressed_text_for_eval)
        missing_repair = self._verify_missing_points(
            namespace,
            original_text,
            summary,
            important_facts,
            open_items,
            style_notes,
            evaluation.get("missing_points") or [],
        )
        important_facts = self._extend_unique(important_facts, missing_repair["verified_important_facts"])
        open_items = self._extend_unique(open_items, missing_repair["verified_open_items"])
        style_notes = self._extend_unique(style_notes, missing_repair["verified_style_notes"])
        potential_missing_context = missing_repair["potential_missing_context"]

        recent_tail = original_history[-keep_recent_messages:] if keep_recent_messages else []
        compressed_history = [
            {
                "role": "system",
                "content": self._build_summary_message(
                    summary,
                    important_facts,
                    open_items,
                    style_notes,
                    potential_missing_context=potential_missing_context,
                    user_memory_candidates=user_memory_candidates,
                    session_state=session_state,
                    assistant_capabilities=assistant_capabilities,
                    ephemeral_facts=ephemeral_facts,
                ),
            },
            *recent_tail,
        ]

        compressed_text = _format_history(compressed_history)
        compressed_facts = self._extract_facts(
            "\n".join(
                [
                    summary,
                    "\n".join(important_facts),
                    "\n".join(user_memory_candidates),
                    "\n".join(session_state),
                    "\n".join(assistant_capabilities),
                    "\n".join(ephemeral_facts),
                    "\n".join(open_items),
                    "\n".join(style_notes),
                    "\n".join(potential_missing_context),
                    compressed_text,
                ]
            )
        )

        rule_recall_rate = self._compute_recall(original_facts, compressed_facts)
        llm_recall = self._evaluate_fact_recall(namespace, original_text, compressed_text)
        recall_rate = self._normalize_recall_rate(llm_recall.get("recall_rate"), rule_recall_rate)

        log_entry = {
            "timestamp": _now_iso(),
            "namespace": namespace,
            "original_message_count": len(original_history),
            "compressed_message_count": len(compressed_history),
            "keep_recent_messages": keep_recent_messages,
            "original_fact_count": len(original_facts),
            "compressed_fact_count": len(compressed_facts),
            "recall_rate": round(recall_rate, 3),
            "rule_recall_rate": round(rule_recall_rate, 3),
            "llm_recall": llm_recall,
            "summary": summary,
            "important_facts": important_facts,
            "user_memory_candidates": user_memory_candidates,
            "session_state": session_state,
            "assistant_capabilities": assistant_capabilities,
            "ephemeral_facts": ephemeral_facts,
            "open_items": open_items,
            "style_notes": style_notes,
            "potential_missing_context": potential_missing_context,
            "missing_repair": missing_repair,
            "scores": evaluation,
        }
        self._append_log(log_entry)

        return {
            "ok": True,
            "namespace": namespace,
            "summary": summary,
            "important_facts": important_facts,
            "user_memory_candidates": user_memory_candidates,
            "session_state": session_state,
            "assistant_capabilities": assistant_capabilities,
            "ephemeral_facts": ephemeral_facts,
            "open_items": open_items,
            "style_notes": style_notes,
            "potential_missing_context": potential_missing_context,
            "missing_repair": missing_repair,
            "keep_recent_messages": keep_recent_messages,
            "compressed_history": compressed_history,
            "original_message_count": len(original_history),
            "compressed_message_count": len(compressed_history),
            "recall_rate": round(recall_rate, 3),
            "rule_recall_rate": round(rule_recall_rate, 3),
            "llm_recall": llm_recall,
            "scores": evaluation,
            "log_path": str(self.log_path),
        }

    def _evaluate_compression(
        self,
        namespace: str,
        original_text: str,
        summary: str,
        compressed_text: str,
    ) -> Dict[str, Any]:
        try:
            raw = self.client.chat(
                [
                    {"role": "system", "content": WINDOW_COMPRESSION_EVALUATION_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            f"Namespace: {namespace}\n\n"
                            f"Original conversation:\n{original_text}\n\n"
                            f"Compressed summary:\n{summary}\n\n"
                            f"Compressed window:\n{compressed_text}"
                        ),
                    },
                ],
                temperature=0.0,
            )
            data = _parse_json_object(raw)
        except Exception:
            data = {}

        return {
            "coverage": _safe_score(data.get("coverage")),
            "fidelity": _safe_score(data.get("fidelity")),
            "conciseness": _safe_score(data.get("conciseness")),
            "continuity": _safe_score(data.get("continuity")),
            "missing_points": [
                str(item).strip()
                for item in (data.get("missing_points") or [])
                if str(item).strip()
            ],
            "comment": _normalize_text(str(data.get("comment") or "")),
        }

    def _evaluate_fact_recall(
        self,
        namespace: str,
        original_text: str,
        compressed_text: str,
    ) -> Dict[str, Any]:
        try:
            raw = self.client.chat(
                [
                    {"role": "system", "content": WINDOW_FACT_RECALL_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            f"Namespace: {namespace}\n\n"
                            f"Original conversation:\n{original_text}\n\n"
                            f"Compressed window:\n{compressed_text}"
                        ),
                    },
                ],
                temperature=0.0,
            )
            data = _parse_json_object(raw)
        except Exception:
            data = {}

        original_key_facts = self._string_list(data.get("original_key_facts"))
        compressed_key_facts = self._string_list(data.get("compressed_key_facts"))
        matched_facts = self._string_list(data.get("matched_facts"))
        missing_facts = self._string_list(data.get("missing_facts"))
        incorrect_facts = self._string_list(data.get("incorrect_facts"))

        recall_rate = data.get("recall_rate")
        if not isinstance(recall_rate, (int, float)):
            recall_rate = len(matched_facts) / len(original_key_facts) if original_key_facts else None

        return {
            "original_key_facts": original_key_facts,
            "compressed_key_facts": compressed_key_facts,
            "matched_facts": matched_facts,
            "missing_facts": missing_facts,
            "incorrect_facts": incorrect_facts,
            "recall_rate": self._clamp_recall(recall_rate) if recall_rate is not None else None,
            "comment": _normalize_text(str(data.get("comment") or "")),
        }

    def _verify_missing_points(
        self,
        namespace: str,
        original_text: str,
        summary: str,
        important_facts: List[str],
        open_items: List[str],
        style_notes: List[str],
        missing_points: List[str],
    ) -> Dict[str, Any]:
        result = {
            "verified_important_facts": [],
            "verified_open_items": [],
            "verified_style_notes": [],
            "potential_missing_context": [],
            "rejected_missing_points": [],
            "raw_items": [],
        }
        clean_missing = [point for point in missing_points if str(point).strip()]
        if not clean_missing:
            return result

        try:
            raw = self.client.chat(
                [
                    {"role": "system", "content": WINDOW_MISSING_POINT_VERIFICATION_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            f"Namespace: {namespace}\n\n"
                            f"Original conversation:\n{original_text}\n\n"
                            f"Current compression:\n"
                            f"Summary: {summary}\n"
                            f"Important facts: {json.dumps(important_facts, ensure_ascii=False)}\n"
                            f"Open items: {json.dumps(open_items, ensure_ascii=False)}\n"
                            f"Style notes: {json.dumps(style_notes, ensure_ascii=False)}\n\n"
                            f"Missing points to verify:\n{json.dumps(clean_missing, ensure_ascii=False, indent=2)}"
                        ),
                    },
                ],
                temperature=0.0,
            )
            data = _parse_json_object(raw)
        except Exception:
            data = {}

        items = data.get("items")
        if not isinstance(items, list):
            result["potential_missing_context"] = [
                f"Compression evaluator flagged but did not verify: {point}" for point in clean_missing
            ]
            return result

        for item in items:
            normalized = self._normalize_repair_item(item)
            if normalized is None:
                continue
            result["raw_items"].append(normalized)
            status = normalized["status"]
            category = normalized["category"]
            text = normalized["text"]
            if status == "verified" and category == "important_fact":
                result["verified_important_facts"].append(text)
            elif status == "verified" and category == "open_item":
                result["verified_open_items"].append(text)
            elif status == "verified" and category == "style_note":
                result["verified_style_notes"].append(text)
            elif status == "verified":
                result["potential_missing_context"].append(f"Verified context: {text}")
            elif status == "potential":
                result["potential_missing_context"].append(f"Potential context: {text}")
            else:
                result["rejected_missing_points"].append(normalized["source"] or text)
        return result

    @staticmethod
    def _normalize_repair_item(item: Any) -> Dict[str, str] | None:
        if not isinstance(item, Mapping):
            return None
        text = _normalize_text(str(item.get("text") or ""))
        if not text:
            return None
        status = str(item.get("status") or "potential").strip().lower()
        if status not in {"verified", "potential", "rejected"}:
            status = "potential"
        category = str(item.get("category") or "potential_context").strip().lower()
        if category not in {"important_fact", "open_item", "style_note", "potential_context"}:
            category = "potential_context"
        return {
            "source": _normalize_text(str(item.get("source") or "")),
            "status": status,
            "category": category,
            "text": text,
            "reason": _normalize_text(str(item.get("reason") or "")),
        }

    def _extract_facts(self, text: str) -> List[str]:
        facts: List[str] = []
        for fact in extract_key_facts(text):
            if fact not in facts:
                facts.append(fact)
        return facts

    def _compute_recall(self, original_facts: List[str], compressed_facts: List[str]) -> float:
        if not original_facts:
            return 1.0
        preserved = len(set(original_facts) & set(compressed_facts))
        return preserved / len(set(original_facts))

    def _normalize_keep_count(self, value: Any) -> int:
        try:
            count = int(value)
        except Exception:
            count = self.min_keep_messages
        return max(self.min_keep_messages, min(self.max_keep_messages, count))

    @staticmethod
    def _build_summary_message(
        summary: str,
        important_facts: List[str],
        open_items: List[str],
        style_notes: List[str],
        potential_missing_context: List[str] | None = None,
        *,
        user_memory_candidates: List[str] | None = None,
        session_state: List[str] | None = None,
        assistant_capabilities: List[str] | None = None,
        ephemeral_facts: List[str] | None = None,
    ) -> str:
        lines = ["Compressed window summary:", summary]
        if important_facts:
            lines.append("Important facts:")
            lines.extend(f"- {item}" for item in important_facts)
        if user_memory_candidates:
            lines.append("User memory candidates:")
            lines.extend(f"- {item}" for item in user_memory_candidates)
        if session_state:
            lines.append("Session state:")
            lines.extend(f"- {item}" for item in session_state)
        if assistant_capabilities:
            lines.append("Assistant capabilities:")
            lines.extend(f"- {item}" for item in assistant_capabilities)
        if ephemeral_facts:
            lines.append("Ephemeral facts:")
            lines.extend(f"- {item}" for item in ephemeral_facts)
        if open_items:
            lines.append("Open items:")
            lines.extend(f"- {item}" for item in open_items)
        if style_notes:
            lines.append("Style notes:")
            lines.extend(f"- {item}" for item in style_notes)
        if potential_missing_context:
            lines.append("Potential missing context:")
            lines.extend(f"- {item}" for item in potential_missing_context)
        return "\n".join(line for line in lines if line)

    @staticmethod
    def _string_list(value: Any) -> List[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    @staticmethod
    def _clamp_recall(value: Any) -> float:
        try:
            score = float(value)
        except Exception:
            return 0.0
        return max(0.0, min(1.0, score))

    @staticmethod
    def _normalize_recall_rate(llm_recall: Any, rule_recall: float) -> float:
        if isinstance(llm_recall, (int, float)):
            return max(0.0, min(1.0, float(llm_recall)))
        return max(0.0, min(1.0, float(rule_recall)))

    @staticmethod
    def _extend_unique(base: List[str], additions: List[str]) -> List[str]:
        result = list(base)
        seen = {_normalize_text(item).lower() for item in result}
        for item in additions:
            normalized = _normalize_text(item)
            key = normalized.lower()
            if not normalized or key in seen:
                continue
            seen.add(key)
            result.append(normalized)
        return result

    def _append_log(self, entry: Dict[str, Any]) -> None:
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
