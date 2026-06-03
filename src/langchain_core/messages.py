from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class _BaseMessage:
    content: str


@dataclass(slots=True)
class HumanMessage(_BaseMessage):
    pass


@dataclass(slots=True)
class SystemMessage(_BaseMessage):
    pass
