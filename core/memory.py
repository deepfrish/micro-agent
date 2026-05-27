from __future__ import annotations

from collections import deque
import re
from typing import Deque, Iterable, List


_USER_NAME = "\u7528\u6237\u59d3\u540d"
_USER_IDENTITY = "\u7528\u6237\u8eab\u4efd"
_USER_STUDYING = "\u7528\u6237\u6b63\u5728\u5b66\u4e60"
_USER_GOAL = "\u7528\u6237\u76ee\u6807"
_USER_PREFERENCE = "\u7528\u6237\u504f\u597d"
_QUESTION_WORDS = ("\u4ec0\u4e48", "\u54ea", "\u8c01", "\u5417", "\u4e48", "\u5982\u4f55", "\u600e\u4e48", "\u4e3a\u4ec0\u4e48", "\u591a\u5c11")

_FACT_PATTERNS = [
    (re.compile(r"\u6211\u53eb\s*(?P<value>[^,\uff0c\.\u3002\uFF1B;\n\u3001]+)"), _USER_NAME),
    (re.compile(r"\u6211\u7684\u540d\u5b57\u662f\s*(?P<value>[^,\uff0c\.\u3002\uFF1B;\n\u3001]+)"), _USER_NAME),
    (re.compile(r"\u6211\u662f\s*(?P<value>[^,\uff0c\.\u3002\uFF1B;\n\u3001]+)"), _USER_IDENTITY),
    (re.compile(r"\u6211\u6b63\u5728\u5b66\s*(?P<value>[^,\uff0c\.\u3002\uFF1B;\n\u3001]+)"), _USER_STUDYING),
    (re.compile(r"\u6211\u5728\u5b66\s*(?P<value>[^,\uff0c\.\u3002\uFF1B;\n\u3001]+)"), _USER_STUDYING),
    (re.compile(r"\u6211\u60f3(?:\u8981)?\s*(?P<value>[^,\uff0c\.\u3002\uFF1B;\n\u3001]+)"), _USER_GOAL),
    (re.compile(r"\u6211\u559c\u6b22\s*(?P<value>[^,\uff0c\.\u3002\uFF1B;\n\u3001]+)"), _USER_PREFERENCE),
]


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def extract_key_facts(text: str) -> List[str]:
    """Extract small, stable facts from user text."""

    cleaned = _normalize_text(text)
    if not cleaned:
        return []

    if cleaned.endswith(("?", "\uff1f")):
        cleaned = cleaned[:-1].strip()

    facts: List[str] = []
    for pattern, label in _FACT_PATTERNS:
        for match in pattern.finditer(cleaned):
            value = _normalize_text(match.group("value"))
            if not value or any(token in value for token in _QUESTION_WORDS):
                continue
            fact = f"{label}:{value}"
            if fact not in facts:
                facts.append(fact)
    return facts


class WorkingMemory:
    """A tiny short-term memory store for the current user session."""

    def __init__(self, capacity: int = 5) -> None:
        self.capacity = max(1, capacity)
        self._items: Deque[str] = deque(maxlen=self.capacity)

    def add(self, text: str) -> List[str]:
        """Add extracted facts from text and return the newly added facts."""

        added: List[str] = []
        for fact in extract_key_facts(text):
            if fact in self._items:
                continue
            self._items.append(fact)
            added.append(fact)
        return added

    def extend(self, texts: Iterable[str]) -> List[str]:
        added: List[str] = []
        for text in texts:
            added.extend(self.add(text))
        return added

    def load(self, facts: Iterable[str]) -> None:
        for fact in facts:
            cleaned = _normalize_text(fact)
            if not cleaned or cleaned in self._items:
                continue
            self._items.append(cleaned)

    def search(self, query: str) -> List[str]:
        cleaned_query = _normalize_text(query)
        keywords = [part for part in re.split(r"[\s,\.\u3002\uFF1B;\uFF01\uFF1F?]+", cleaned_query) if part]
        items = list(self._items)
        if not keywords:
            return items

        matches = [item for item in items if any(keyword in item for keyword in keywords)]
        return matches or items

    def format_context(self, query: str = "") -> str:
        items = self.search(query)
        if not items:
            return "No working memory."
        return "\n".join(f"- {item}" for item in items)

    def snapshot(self) -> List[str]:
        return list(self._items)

    def clear(self) -> None:
        self._items.clear()

    def __len__(self) -> int:
        return len(self._items)
