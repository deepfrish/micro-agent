from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class ChatCommand:
    kind: Literal["new", "exit", "delete", "compress", "tools", "net", "switch", "rag", "noop"]
    argument: str = ""


def parse_chat_command(raw: str) -> ChatCommand:
    text = raw.strip()
    if not text.startswith("/"):
        return ChatCommand("noop")

    body = text[1:].strip()
    if not body:
        return ChatCommand("noop")

    head, _, tail = body.partition(" ")
    keyword = head.strip().lower()
    argument = tail.strip()

    if keyword == "new":
        return ChatCommand("new")
    if keyword == "exit":
        return ChatCommand("exit", argument)
    if keyword == "compress":
        return ChatCommand("compress", argument)
    if keyword == "tools":
        return ChatCommand("tools", argument)
    if keyword == "net":
        return ChatCommand("net", argument)
    if keyword == "rag":
        return ChatCommand("rag", argument)
    if keyword.startswith("rag="):
        return ChatCommand("rag", keyword.split("=", 1)[1].strip())
    if keyword in {"del", "delete", "rm", "remove"}:
        return ChatCommand("delete", argument)
    return ChatCommand("switch", body)
