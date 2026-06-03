from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence
from uuid import uuid4

from .memory import extract_key_facts


STATUS_ACTIVE = "active"
STATUS_STALE = "stale"
STATUS_ARCHIVED = "archived"
STATUS_DELETED = "deleted"

DEFAULT_STALE_AFTER_DAYS = 14
DEFAULT_ARCHIVE_AFTER_DAYS = 60
DEFAULT_DELETE_AFTER_DAYS = 180
DEFAULT_GLOBAL_NAMESPACE = "global"

_FACT_KEY_MAP = {
    "\u7528\u6237\u59d3\u540d": "user.name",
    "\u7528\u6237\u8eab\u4efd": "user.identity",
    "\u7528\u6237\u6b63\u5728\u5b66\u4e60": "user.studying",
    "\u7528\u6237\u76ee\u6807": "user.goal",
}

_PINNED_MEMORY_KEYS = {
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
    return " ".join(text.split()).strip()


def _safe_namespace(namespace: str) -> str:
    cleaned = _normalize_text(namespace)
    return cleaned or "default"


def _safe_memory_key(memory_key: str | None) -> str:
    cleaned = _normalize_text(str(memory_key or ""))
    cleaned = cleaned.lower()
    cleaned = cleaned.replace(" ", "-")
    return cleaned


def _safe_kind(kind: str | None) -> str:
    cleaned = _normalize_text(str(kind or "note")).lower()
    allowed = {"profile", "preference", "goal", "project", "note"}
    return cleaned if cleaned in allowed else "note"


def _safe_status(status: str | None) -> str:
    cleaned = _normalize_text(str(status or STATUS_ACTIVE)).lower()
    allowed = {STATUS_ACTIVE, STATUS_STALE, STATUS_ARCHIVED, STATUS_DELETED}
    return cleaned if cleaned in allowed else STATUS_ACTIVE


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


def _days_since(value: str | None) -> float:
    stamp = _parse_iso(value)
    if stamp is None:
        return float("inf")
    delta = datetime.now(timezone.utc) - stamp
    return max(0.0, delta.total_seconds() / 86400.0)


def _status_rank(status: str) -> int:
    order = {
        STATUS_ACTIVE: 0,
        STATUS_STALE: 1,
        STATUS_ARCHIVED: 2,
        STATUS_DELETED: 3,
    }
    return order.get(status, 4)


def _fact_to_memory_key(fact: str) -> str:
    if ":" not in fact:
        return ""

    label, value = fact.split(":", 1)
    label = _normalize_text(label)
    value = _normalize_text(value)
    if not label or not value:
        return ""

    if label in _FACT_KEY_MAP:
        return _FACT_KEY_MAP[label]

    if label == "\u7528\u6237\u504f\u597d":
        if any(token in value for token in ("\u56de\u7b54", "\u5f00\u5934", "\u79f0\u547c", "\u8bed\u8a00", "\u9ed8\u8ba4")):
            return "user.answer_style"
    return ""


def _infer_memory_key(text: str, kind: str) -> str:
    cleaned = _normalize_text(text)
    if not cleaned:
        return ""

    lowered = cleaned.lower()
    if any(token in cleaned for token in ("\u8bf7\u4ee5\u540e", "\u4ee5\u540e", "\u4ece\u4eca\u4ee5\u540e")) and any(
        token in cleaned for token in ("\u5f00\u5934", "\u79f0\u547c", "\u53eb\u6211", "\u7528")
    ):
        return "user.reply_prefix"

    if any(token in cleaned for token in ("\u6211\u53eb", "\u6211\u7684\u540d\u5b57", "\u53eb\u6211", "\u79f0\u547c\u6211")):
        return "user.name"

    if kind == "profile" and any(token in cleaned for token in ("\u6211\u662f", "\u6211\u6b63\u5728", "\u6211\u5728\u5b66")):
        return "user.profile"

    if kind == "goal" and any(token in cleaned for token in ("\u6211\u60f3", "\u6211\u8981", "\u76ee\u6807")):
        return "user.goal"

    if kind == "preference" and any(token in lowered for token in ("prefix", "style", "language", "\u8bed\u8a00", "\u56de\u7b54", "\u79f0\u547c")):
        return "user.preference"

    return ""


def _memory_temperature(entry: Mapping[str, Any]) -> float:
    status = _safe_status(entry.get("status"))
    base = {
        STATUS_ACTIVE: 78.0,
        STATUS_STALE: 48.0,
        STATUS_ARCHIVED: 20.0,
        STATUS_DELETED: 0.0,
    }.get(status, 10.0)

    last_seen = entry.get("last_accessed_at") or entry.get("updated_at") or entry.get("created_at")
    age_days = _days_since(str(last_seen) if last_seen else None)
    recency_bonus = max(0.0, 18.0 - age_days * 0.6)

    access_count = int(entry.get("access_count") or 0)
    access_bonus = min(10.0, math.log1p(max(0, access_count)) * 3.5)

    confidence = entry.get("confidence")
    confidence_bonus = 0.0
    if isinstance(confidence, (int, float)):
        confidence_bonus = max(0.0, min(5.0, float(confidence) * 5.0))

    temperature = base + recency_bonus + access_bonus + confidence_bonus
    return round(max(0.0, min(100.0, temperature)), 1)


class LongTermMemoryStore:
    """JSON-backed persistent memory store with lifecycle states."""

    def __init__(
        self,
        path: Path | None = None,
        *,
        stale_after_days: int = DEFAULT_STALE_AFTER_DAYS,
        archive_after_days: int = DEFAULT_ARCHIVE_AFTER_DAYS,
        delete_after_days: int = DEFAULT_DELETE_AFTER_DAYS,
    ) -> None:
        self.path = path or Path(__file__).resolve().parents[2] / "data" / "global_memory.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stale_after_days = max(1, int(stale_after_days))
        self.archive_after_days = max(self.stale_after_days + 1, int(archive_after_days))
        self.delete_after_days = max(self.archive_after_days + 1, int(delete_after_days))

    def add(self, namespace: str, text: str) -> List[Dict[str, Any]]:
        namespace = _safe_namespace(namespace)
        data = self._load_all()
        entries = data.setdefault(namespace, [])
        added: List[Dict[str, Any]] = []

        extracted = extract_key_facts(text)
        candidates = extracted or [_normalize_text(text)]
        kind = "fact" if extracted else "note"
        for candidate in candidates:
            normalized = _normalize_text(candidate)
            if not normalized:
                continue
            memory_key = _fact_to_memory_key(normalized) or _infer_memory_key(normalized, kind)
            record = self.add_record(
                namespace,
                normalized,
                kind=kind,
                confidence=None,
                memory_key=memory_key or None,
                action="upsert" if memory_key else "append",
            )
            if record is not None:
                added.append(record)

        if entries is not data.get(namespace):
            self._save_all(data)
        return added

    def add_record(
        self,
        namespace: str,
        text: str,
        *,
        kind: str = "note",
        confidence: float | None = None,
        memory_key: str | None = None,
        action: str = "append",
        status: str = STATUS_ACTIVE,
    ) -> Dict[str, Any] | None:
        namespace = _safe_namespace(namespace)
        normalized = _normalize_text(text)
        if not normalized:
            return None

        data = self._load_all()
        entries = data.setdefault(namespace, [])
        now = _now_iso()
        kind = _safe_kind(kind)
        action = _normalize_text(action).lower() or ("upsert" if memory_key else "append")
        memory_key = _safe_memory_key(memory_key) or (_infer_memory_key(normalized, kind) if action != "append" else "")
        status = _safe_status(status)

        if action in {"archive", "delete"} and memory_key:
            self._set_memory_status(entries, memory_key, status=STATUS_ARCHIVED if action == "archive" else STATUS_DELETED)
            self._save_all(data)
            return None

        if memory_key:
            version = self._next_version(entries, memory_key)
            matching = [
                entry
                for entry in entries
                if _safe_memory_key(entry.get("memory_key")) == memory_key
                and _safe_status(entry.get("status")) != STATUS_DELETED
            ]
            latest = matching[-1] if matching else None
            if latest and latest.get("text") == normalized and _safe_status(latest.get("status")) == STATUS_ACTIVE:
                latest["updated_at"] = now
                if confidence is not None:
                    latest["confidence"] = float(confidence)
                self._save_all(data)
                return None

            record = self._build_record(
                namespace,
                text=normalized,
                kind=kind,
                confidence=confidence,
                memory_key=memory_key,
                status=STATUS_ACTIVE,
                version=version,
                created_at=now,
                updated_at=now,
            )
            for entry in matching:
                entry["status"] = STATUS_ARCHIVED
                entry["archived_at"] = now
                entry["updated_at"] = now
                entry["replaced_by"] = record["id"]
            entries.append(record)
            self._save_all(data)
            return record

        duplicate = self._find_exact_text(entries, normalized)
        if duplicate:
            duplicate["updated_at"] = now
            if confidence is not None:
                duplicate["confidence"] = float(confidence)
            self._save_all(data)
            return None

        record = self._build_record(
            namespace,
            text=normalized,
            kind=kind,
            confidence=confidence,
            memory_key="",
            status=status,
            version=1,
            created_at=now,
            updated_at=now,
        )
        entries.append(record)
        self._save_all(data)
        return record

    def update(
        self,
        namespace: str,
        memory_key: str,
        text: str,
        *,
        kind: str = "note",
        confidence: float | None = None,
    ) -> Dict[str, Any] | None:
        return self.add_record(
            namespace,
            text,
            kind=kind,
            confidence=confidence,
            memory_key=memory_key,
            action="upsert",
        )

    def upsert(
        self,
        namespace: str,
        text: str,
        *,
        kind: str = "note",
        confidence: float | None = None,
        memory_key: str | None = None,
    ) -> Dict[str, Any] | None:
        inferred_key = _safe_memory_key(memory_key) or self.suggest_memory_key(text, kind=kind)
        action = "upsert" if inferred_key else "append"
        return self.add_record(
            namespace,
            text,
            kind=kind,
            confidence=confidence,
            memory_key=inferred_key or None,
            action=action,
        )

    def archive(self, namespace: str, memory_key: str | None = None, text: str | None = None) -> int:
        return self._mutate_status(namespace, memory_key=memory_key, text=text, target_status=STATUS_ARCHIVED)

    def delete(self, namespace: str, memory_key: str | None = None, text: str | None = None) -> int:
        return self._mutate_status(namespace, memory_key=memory_key, text=text, target_status=STATUS_DELETED)

    def refresh_lifecycle(
        self,
        namespace: str,
        *,
        stale_after_days: int | None = None,
        archive_after_days: int | None = None,
        delete_after_days: int | None = None,
    ) -> Dict[str, int]:
        namespace = _safe_namespace(namespace)
        data = self._load_all()
        entries = data.get(namespace, [])
        now = _now_iso()
        stale_after_days = max(1, int(stale_after_days or self.stale_after_days))
        archive_after_days = max(stale_after_days + 1, int(archive_after_days or self.archive_after_days))
        delete_after_days = max(archive_after_days + 1, int(delete_after_days or self.delete_after_days))

        changes = {"staled": 0, "archived": 0, "deleted": 0}
        for entry in entries:
            status = _safe_status(entry.get("status"))
            if status == STATUS_DELETED:
                continue

            last_seen = entry.get("last_accessed_at") or entry.get("updated_at") or entry.get("created_at")
            age_days = _days_since(str(last_seen) if last_seen else None)
            if status == STATUS_ACTIVE and age_days >= stale_after_days:
                entry["status"] = STATUS_STALE
                entry["staled_at"] = now
                changes["staled"] += 1
            elif status == STATUS_STALE and age_days >= archive_after_days:
                entry["status"] = STATUS_ARCHIVED
                entry["archived_at"] = now
                changes["archived"] += 1
            elif status == STATUS_ARCHIVED and age_days >= delete_after_days:
                entry["status"] = STATUS_DELETED
                entry["deleted_at"] = now
                changes["deleted"] += 1

        self._save_all(data)
        return changes

    def search(
        self,
        namespace: str,
        query: str,
        limit: int = 5,
        *,
        statuses: Sequence[str] | None = None,
    ) -> List[Dict[str, Any]]:
        namespace = _safe_namespace(namespace)
        limit = max(1, limit)
        data = self._load_all()
        entries = data.get(namespace, [])
        allowed_statuses = {_safe_status(status) for status in statuses} if statuses else {STATUS_ACTIVE, STATUS_STALE}
        terms = self._build_terms(query)

        if not terms:
            hits = [entry for entry in entries if _safe_status(entry.get("status")) in allowed_statuses]
            hits = sorted(hits, key=self._sort_key)[:limit]
            self._touch(data, hits)
            return hits

        scored: List[tuple[int, Dict[str, Any]]] = []
        for entry in entries:
            status = _safe_status(entry.get("status"))
            if status not in allowed_statuses:
                continue

            text = str(entry.get("text", ""))
            memory_key = str(entry.get("memory_key", ""))
            score = sum(1 for term in terms if term and (term in text or term in memory_key))
            if score:
                scored.append((score, entry))

        scored.sort(key=lambda item: (-item[0], *self._sort_key(item[1])))
        hits = [entry for _, entry in scored[:limit]]
        self._touch(data, hits)
        return hits

    def search_all(
        self,
        query: str,
        limit: int = 5,
        *,
        statuses: Sequence[str] | None = None,
    ) -> List[Dict[str, Any]]:
        data = self._load_all()
        allowed_statuses = {_safe_status(status) for status in statuses} if statuses else {STATUS_ACTIVE, STATUS_STALE}
        terms = self._build_terms(query)
        entries = [entry for namespace_entries in data.values() for entry in namespace_entries]

        if not terms:
            hits = [entry for entry in entries if _safe_status(entry.get("status")) in allowed_statuses]
            hits.sort(key=self._sort_key)
            hits = hits[: max(1, limit)]
            self._touch(data, hits)
            return hits

        scored: List[tuple[int, Dict[str, Any]]] = []
        for entry in entries:
            status = _safe_status(entry.get("status"))
            if status not in allowed_statuses:
                continue

            text = str(entry.get("text", ""))
            memory_key = str(entry.get("memory_key", ""))
            namespace = str(entry.get("namespace", ""))
            score = sum(1 for term in terms if term and (term in text or term in memory_key or term in namespace))
            if score:
                scored.append((score, entry))

        scored.sort(key=lambda item: (-item[0], *self._sort_key(item[1])))
        hits = [entry for _, entry in scored[: max(1, limit)]]
        self._touch(data, hits)
        return hits

    def pinned(self, limit: int = 5) -> List[Dict[str, Any]]:
        data = self._load_all()
        entries = [entry for namespace_entries in data.values() for entry in namespace_entries]
        allowed_statuses = {STATUS_ACTIVE, STATUS_STALE}
        candidates = []
        for entry in entries:
            key = _safe_memory_key(entry.get("memory_key"))
            if not key:
                continue
            if _safe_status(entry.get("status")) not in allowed_statuses:
                continue
            if key not in _PINNED_MEMORY_KEYS and _safe_kind(entry.get("kind")) not in {"profile", "preference"}:
                continue
            candidates.append(entry)

        seen: set[str] = set()
        ordered: List[Dict[str, Any]] = []
        for entry in sorted(candidates, key=self._pinned_sort_key):
            key = _safe_memory_key(entry.get("memory_key"))
            dedupe_key = key or str(entry.get("text") or "").strip().lower()
            if not dedupe_key or dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            ordered.append(entry)
            if len(ordered) >= max(1, limit):
                break

        self._touch(data, ordered)
        return ordered

    def rank_for_context(
        self,
        query: str,
        memories: Sequence[Mapping[str, Any]],
        *,
        limit: int | None = None,
    ) -> List[Dict[str, Any]]:
        terms = self._build_terms(query)
        scored: List[tuple[int, Dict[str, Any]]] = []
        for memory in memories:
            if not isinstance(memory, Mapping):
                continue
            status = _safe_status(memory.get("status"))
            if status == STATUS_DELETED:
                continue
            scored.append((self._context_score(memory, terms), dict(memory)))

        scored.sort(key=lambda item: (-item[0], *self._sort_key(item[1])))
        ranked = [memory for _, memory in scored]
        if limit is not None:
            ranked = ranked[: max(1, int(limit))]
        return ranked

    def list(
        self,
        namespace: str,
        limit: int = 20,
        *,
        include_archived: bool = False,
    ) -> List[Dict[str, Any]]:
        namespace = _safe_namespace(namespace)
        limit = max(1, limit)
        entries = self._load_all().get(namespace, [])
        statuses = {STATUS_ACTIVE, STATUS_STALE}
        if include_archived:
            statuses.update({STATUS_ARCHIVED, STATUS_DELETED})
        filtered = [entry for entry in entries if _safe_status(entry.get("status")) in statuses]
        filtered.sort(key=self._sort_key)
        return filtered[:limit]

    def clear(self, namespace: str) -> int:
        namespace = _safe_namespace(namespace)
        data = self._load_all()
        removed = len(data.get(namespace, []))
        data[namespace] = []
        self._save_all(data)
        return removed

    def stats(self, namespace: str) -> Dict[str, Any]:
        namespace = _safe_namespace(namespace)
        entries = self._load_all().get(namespace, [])
        counts = {
            STATUS_ACTIVE: 0,
            STATUS_STALE: 0,
            STATUS_ARCHIVED: 0,
            STATUS_DELETED: 0,
        }
        latest = None
        latest_rank: tuple[str, int, int] | None = None
        temperature_sum = 0.0
        temperature_count = 0
        for entry in entries:
            status = _safe_status(entry.get("status"))
            counts[status] = counts.get(status, 0) + 1
            temp = _memory_temperature(entry)
            temperature_sum += temp
            temperature_count += 1
            current_rank = (
                str(entry.get("updated_at") or entry.get("created_at") or ""),
                int(entry.get("version") or 1),
                -_status_rank(status),
            )
            if latest is None or latest_rank is None or current_rank > latest_rank:
                latest = entry
                latest_rank = current_rank

        return {
            "namespace": namespace,
            "count": len(entries),
            "active": counts[STATUS_ACTIVE],
            "stale": counts[STATUS_STALE],
            "archived": counts[STATUS_ARCHIVED],
            "deleted": counts[STATUS_DELETED],
            "average_temperature": round(temperature_sum / temperature_count, 1) if temperature_count else 0.0,
            "latest": latest,
        }

    def namespaces(self) -> List[str]:
        data = self._load_all()
        return sorted(data.keys())

    def get_entries(
        self,
        namespace: str,
        *,
        include_archived: bool = True,
    ) -> List[Dict[str, Any]]:
        namespace = _safe_namespace(namespace)
        entries = self._load_all().get(namespace, [])
        if include_archived:
            return list(entries)
        return [entry for entry in entries if _safe_status(entry.get("status")) in {STATUS_ACTIVE, STATUS_STALE}]

    def replace_namespace(self, namespace: str, entries: Sequence[Mapping[str, Any]]) -> None:
        namespace = _safe_namespace(namespace)
        data = self._load_all()
        data[namespace] = [self._normalize_entry(namespace, entry) for entry in entries]
        self._save_all(data)

    def export_records(
        self,
        *,
        statuses: Sequence[str] = (STATUS_ACTIVE, STATUS_STALE),
    ) -> Dict[str, List[Dict[str, Any]]]:
        data = self._load_all()
        allowed = {_safe_status(status) for status in statuses}
        exported: Dict[str, List[Dict[str, Any]]] = {}
        for namespace, entries in data.items():
            filtered = [entry for entry in entries if _safe_status(entry.get("status")) in allowed]
            if filtered:
                exported[namespace] = filtered
        return exported

    def suggest_memory_key(self, text: str, kind: str = "note") -> str:
        normalized = _normalize_text(text)
        kind = _safe_kind(kind)
        for fact in extract_key_facts(normalized):
            key = _fact_to_memory_key(fact)
            if key:
                return key
        return _infer_memory_key(normalized, kind)

    def _load_all(self) -> Dict[str, List[Dict[str, Any]]]:
        if not self.path.exists():
            return {}

        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {}

        if not isinstance(data, dict):
            return {}

        if isinstance(data.get("namespaces"), dict):
            data = data["namespaces"]

        normalized: Dict[str, List[Dict[str, Any]]] = {}
        for namespace, entries in data.items():
            if not isinstance(entries, list):
                continue
            namespace_name = _safe_namespace(str(namespace))
            normalized[namespace_name] = [self._normalize_entry(namespace_name, entry) for entry in entries if isinstance(entry, dict)]
        return normalized

    def _save_all(self, data: Dict[str, List[Dict[str, Any]]]) -> None:
        payload = {
            "version": 1,
            "namespaces": data,
        }
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _normalize_entry(self, namespace: str, entry: Mapping[str, Any]) -> Dict[str, Any]:
        now = _now_iso()
        normalized = dict(entry)
        normalized["id"] = str(normalized.get("id") or uuid4().hex)
        normalized["namespace"] = namespace
        normalized["kind"] = _safe_kind(normalized.get("kind"))
        normalized["text"] = _normalize_text(str(normalized.get("text", "")))
        normalized["memory_key"] = _safe_memory_key(normalized.get("memory_key")) or _infer_memory_key(
            normalized["text"],
            normalized["kind"],
        )
        normalized["status"] = _safe_status(normalized.get("status"))
        normalized["version"] = max(1, int(normalized.get("version") or 1))
        confidence = normalized.get("confidence")
        try:
            normalized["confidence"] = float(confidence) if confidence is not None else None
        except Exception:
            normalized["confidence"] = None
        normalized["created_at"] = str(normalized.get("created_at") or normalized.get("updated_at") or now)
        normalized["updated_at"] = str(normalized.get("updated_at") or normalized["created_at"])
        normalized["last_accessed_at"] = str(normalized.get("last_accessed_at") or "") or None
        normalized["access_count"] = max(0, int(normalized.get("access_count") or 0))
        normalized["temperature"] = _memory_temperature(normalized)
        return normalized

    def _build_record(
        self,
        namespace: str,
        *,
        text: str,
        kind: str,
        confidence: float | None,
        memory_key: str,
        status: str,
        version: int,
        created_at: str,
        updated_at: str,
    ) -> Dict[str, Any]:
        record = {
            "id": uuid4().hex,
            "namespace": namespace,
            "kind": _safe_kind(kind),
            "text": _normalize_text(text),
            "memory_key": _safe_memory_key(memory_key),
            "status": _safe_status(status),
            "version": max(1, int(version)),
            "confidence": float(confidence) if confidence is not None else None,
            "created_at": created_at,
            "updated_at": updated_at,
            "last_accessed_at": None,
            "access_count": 0,
            "temperature": 0.0,
        }
        record["temperature"] = _memory_temperature(record)
        return record

    def _find_exact_text(self, entries: Sequence[Mapping[str, Any]], text: str) -> Dict[str, Any] | None:
        for entry in entries:
            if _safe_status(entry.get("status")) == STATUS_DELETED:
                continue
            if _normalize_text(str(entry.get("text", ""))) == text:
                return dict(entry)
        return None

    def _latest_active_by_key(self, entries: Sequence[Mapping[str, Any]], memory_key: str) -> Dict[str, Any] | None:
        matches = [
            entry
            for entry in entries
            if _safe_memory_key(entry.get("memory_key")) == memory_key and _safe_status(entry.get("status")) != STATUS_DELETED
        ]
        if not matches:
            return None
        matches.sort(key=self._sort_key)
        return matches[-1]

    def _next_version(self, entries: Sequence[Mapping[str, Any]], memory_key: str) -> int:
        versions = [
            int(entry.get("version") or 1)
            for entry in entries
            if _safe_memory_key(entry.get("memory_key")) == memory_key
        ]
        return (max(versions) if versions else 0) + 1

    def _set_memory_status(self, entries: Sequence[Dict[str, Any]], memory_key: str, *, status: str) -> int:
        count = 0
        now = _now_iso()
        for entry in entries:
            if _safe_memory_key(entry.get("memory_key")) != memory_key:
                continue
            if _safe_status(entry.get("status")) == status:
                continue
            entry["status"] = status
            if status == STATUS_ARCHIVED:
                entry["archived_at"] = now
            elif status == STATUS_DELETED:
                entry["deleted_at"] = now
            entry["updated_at"] = now
            count += 1
        return count

    def _mutate_status(
        self,
        namespace: str,
        *,
        memory_key: str | None,
        text: str | None,
        target_status: str,
    ) -> int:
        namespace = _safe_namespace(namespace)
        data = self._load_all()
        entries = data.get(namespace, [])
        now = _now_iso()
        targets: List[Dict[str, Any]] = []
        cleaned_key = _safe_memory_key(memory_key)
        cleaned_text = _normalize_text(str(text or ""))
        for entry in entries:
            if cleaned_key and _safe_memory_key(entry.get("memory_key")) == cleaned_key:
                targets.append(entry)
                continue
            if cleaned_text and _normalize_text(str(entry.get("text", ""))) == cleaned_text:
                targets.append(entry)

        count = 0
        for entry in targets:
            if _safe_status(entry.get("status")) == target_status:
                continue
            entry["status"] = target_status
            if target_status == STATUS_ARCHIVED:
                entry["archived_at"] = now
            elif target_status == STATUS_DELETED:
                entry["deleted_at"] = now
            entry["updated_at"] = now
            count += 1

        if count:
            self._save_all(data)
        return count

    def _touch(self, data: Dict[str, List[Dict[str, Any]]], hits: List[Dict[str, Any]]) -> None:
        if not hits:
            return

        now = _now_iso()
        for entry in hits:
            entry["last_accessed_at"] = now
            entry["access_count"] = int(entry.get("access_count") or 0) + 1
            if _safe_status(entry.get("status")) == STATUS_STALE:
                entry["status"] = STATUS_ACTIVE
                entry["updated_at"] = now
            entry["temperature"] = _memory_temperature(entry)
        self._save_all(data)

    def _sort_key(self, entry: Mapping[str, Any]) -> tuple[Any, ...]:
        return (
            _status_rank(_safe_status(entry.get("status"))),
            -_memory_temperature(entry),
            -(int(entry.get("access_count") or 0)),
            str(entry.get("updated_at") or entry.get("created_at") or ""),
            str(entry.get("id") or ""),
        )

    def _pinned_sort_key(self, entry: Mapping[str, Any]) -> tuple[Any, ...]:
        key = _safe_memory_key(entry.get("memory_key"))
        return (
            0 if key in _PINNED_MEMORY_KEYS else 1,
            *self._sort_key(entry),
        )

    def _context_score(self, entry: Mapping[str, Any], terms: Sequence[str]) -> int:
        status = _safe_status(entry.get("status"))
        if status == STATUS_DELETED:
            return 0

        status_score = {
            STATUS_ACTIVE: 300,
            STATUS_STALE: 220,
            STATUS_ARCHIVED: 120,
        }.get(status, 100)

        text = str(entry.get("text") or "").lower()
        key = _safe_memory_key(entry.get("memory_key"))
        namespace = str(entry.get("namespace") or "").lower()
        kind = _safe_kind(entry.get("kind"))

        match_score = 0
        for term in terms:
            if not term:
                continue
            lowered = term.lower()
            if lowered in text:
                match_score += 24
            if lowered in key:
                match_score += 28
            if lowered in namespace:
                match_score += 10

        pinned_bonus = 28 if key in _PINNED_MEMORY_KEYS else 0
        kind_bonus = 12 if kind in {"profile", "preference"} else 0
        access_bonus = min(30, int(entry.get("access_count") or 0) * 2)
        recency_bonus = max(0, int(24 - min(24.0, _days_since(str(entry.get("last_accessed_at") or entry.get("updated_at") or entry.get("created_at") or "")) * 0.8)))
        temperature_bonus = int(_memory_temperature(entry))

        return status_score + match_score + pinned_bonus + kind_bonus + access_bonus + recency_bonus + temperature_bonus

    @staticmethod
    def _build_terms(query: str) -> List[str]:
        cleaned = _normalize_text(query)
        if not cleaned:
            return []

        terms: List[str] = []
        for token in cleaned.split():
            if token not in terms:
                terms.append(token)

        for char in cleaned:
            if char.isalnum() or "\u4e00" <= char <= "\u9fff":
                if char not in terms:
                    terms.append(char)
        return terms
