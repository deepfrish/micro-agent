from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence
from uuid import uuid4


def _normalize_text(text: str) -> str:
    return " ".join(text.split()).strip()


def _safe_namespace(namespace: str) -> str:
    return _normalize_text(namespace) or "default"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class WindowMemoryStore:
    """JSON-backed per-chat-window memory snapshots."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or Path(__file__).resolve().parents[1] / "data" / "window_memory.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def add_snapshot(
        self,
        namespace: str,
        *,
        summary: str,
        memories: Sequence[Mapping[str, Any]],
        message_count: int,
    ) -> Dict[str, Any]:
        namespace = _safe_namespace(namespace)
        data = self._load_all()
        snapshots = data.setdefault(namespace, [])
        record = {
            "id": uuid4().hex,
            "namespace": namespace,
            "summary": _normalize_text(summary),
            "memories": [dict(memory) for memory in memories if isinstance(memory, Mapping)],
            "message_count": max(0, int(message_count)),
            "created_at": _now_iso(),
        }
        snapshots.append(record)
        self._save_all(data)
        return record

    def list(self, namespace: str | None = None, limit: int | None = None) -> List[Dict[str, Any]]:
        data = self._load_all()
        if namespace:
            entries = list(data.get(_safe_namespace(namespace), []))
        else:
            entries = [entry for entries in data.values() for entry in entries]

        entries.sort(key=lambda item: str(item.get("created_at") or ""))
        if limit is not None:
            return entries[-max(1, int(limit)) :]
        return entries

    def latest(self, namespace: str) -> Dict[str, Any] | None:
        entries = self.list(namespace, limit=1)
        return entries[-1] if entries else None

    def namespaces(self) -> List[str]:
        return sorted(self._load_all().keys())

    def _load_all(self) -> Dict[str, List[Dict[str, Any]]]:
        if not self.path.exists():
            return {}

        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {}

        data = raw.get("windows") if isinstance(raw, dict) and isinstance(raw.get("windows"), dict) else raw
        if not isinstance(data, Mapping):
            return {}

        normalized: Dict[str, List[Dict[str, Any]]] = {}
        for namespace, entries in data.items():
            if not isinstance(entries, list):
                continue
            normalized[_safe_namespace(str(namespace))] = [dict(entry) for entry in entries if isinstance(entry, Mapping)]
        return normalized

    def _save_all(self, data: Dict[str, List[Dict[str, Any]]]) -> None:
        payload = {
            "version": 1,
            "windows": data,
        }
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
