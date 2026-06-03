from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from .prompts import SKILL_ROUTE_PROMPT


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _normalize_key(text: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", str(text or "").strip().lower())


def _normalize_text(text: str) -> str:
    return " ".join(str(text or "").split()).strip()


def _strip_quotes(value: str) -> str:
    cleaned = value.strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {'"', "'"}:
        return cleaned[1:-1]
    return cleaned


def _parse_scalar(value: str) -> Any:
    cleaned = _strip_quotes(value)
    lowered = cleaned.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered == "null":
        return None
    if re.fullmatch(r"-?\d+", cleaned):
        try:
            return int(cleaned)
        except Exception:
            return cleaned
    if re.fullmatch(r"-?\d+\.\d+", cleaned):
        try:
            return float(cleaned)
        except Exception:
            return cleaned
    return cleaned


def _parse_simple_yaml(text: str) -> Dict[str, Any]:
    root: Dict[str, Any] = {}
    stack: List[tuple[int, Dict[str, Any]]] = [(0, root)]

    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#") or ":" not in stripped:
            continue

        indent = len(raw_line) - len(raw_line.lstrip(" "))
        while len(stack) > 1 and indent < stack[-1][0]:
            stack.pop()

        container = stack[-1][1]
        key, value = stripped.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue

        if not value:
            nested: Dict[str, Any] = {}
            container[key] = nested
            stack.append((indent + 2, nested))
        else:
            container[key] = _parse_scalar(value)

    return root


def _split_frontmatter(text: str) -> tuple[Dict[str, Any], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text

    for index in range(1, len(lines)):
        if lines[index].strip() != "---":
            continue
        meta = _parse_simple_yaml("\n".join(lines[1:index]))
        body = "\n".join(lines[index + 1 :]).lstrip("\n")
        return meta, body
    return {}, text


def _history_tail(history: Sequence[Dict[str, str]], limit: int = 6) -> str:
    tail = list(history)[-limit:]
    lines: List[str] = []
    if history:
        first = history[0]
        first_role = str(first.get("role", ""))
        first_content = str(first.get("content", "")).strip()
        if first_role == "system" and first_content:
            lines.append(f"{first_role}: {first_content}")
    for message in tail:
        role = str(message.get("role", "unknown"))
        content = str(message.get("content", "")).strip()
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines) or "No conversation history."


def _truncate(text: str, limit: int) -> str:
    cleaned = str(text or "").strip()
    if limit <= 0 or len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(0, limit - 3)].rstrip() + "..."


def _parse_json_object(text: str) -> Dict[str, Any]:
    cleaned = str(text or "").strip()
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


@dataclass(slots=True)
class SkillDefinition:
    skill_id: str
    name: str
    description: str
    root: Path
    skill_path: Path
    body: str
    display_name: str = ""
    short_description: str = ""
    default_prompt: str = ""
    aliases: tuple[str, ...] = ()
    reference_paths: tuple[Path, ...] = ()
    agent_metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_directory(cls, root: Path) -> "SkillDefinition" | None:
        skill_path = root / "SKILL.md"
        if not skill_path.exists():
            return None

        raw_skill = skill_path.read_text(encoding="utf-8")
        frontmatter, body = _split_frontmatter(raw_skill)

        agents_path = root / "agents" / "openai.yaml"
        agent_metadata: Dict[str, Any] = {}
        if agents_path.exists():
            agent_metadata = _parse_simple_yaml(agents_path.read_text(encoding="utf-8"))

        interface = agent_metadata.get("interface")
        if not isinstance(interface, Mapping):
            interface = agent_metadata

        skill_id = str(frontmatter.get("name") or root.name).strip() or root.name
        display_name = str(interface.get("display_name") or frontmatter.get("display_name") or skill_id).strip()
        description = str(frontmatter.get("description") or interface.get("short_description") or "").strip()
        short_description = str(interface.get("short_description") or description).strip()
        default_prompt = str(interface.get("default_prompt") or "").strip()

        aliases = cls._build_aliases(skill_id, display_name, root.name)
        reference_paths = tuple(
            sorted(
                path
                for path in (root / "references").glob("*")
                if path.is_file() and path.suffix.lower() in {".md", ".txt", ".rst"}
            )
        )

        return cls(
            skill_id=skill_id,
            name=skill_id,
            description=description,
            root=root,
            skill_path=skill_path,
            body=body.strip(),
            display_name=display_name,
            short_description=short_description,
            default_prompt=default_prompt,
            aliases=aliases,
            reference_paths=reference_paths,
            agent_metadata=agent_metadata,
        )

    @staticmethod
    def _build_aliases(*values: str) -> tuple[str, ...]:
        aliases: List[str] = []
        for value in values:
            normalized = _normalize_key(value)
            if normalized and normalized not in aliases:
                aliases.append(normalized)
            skill_suffix = _normalize_key(f"{value} skill")
            if skill_suffix and skill_suffix not in aliases:
                aliases.append(skill_suffix)
            if normalized.endswith("skill"):
                trimmed = normalized[:-5].rstrip("s")
                if trimmed and trimmed not in aliases:
                    aliases.append(trimmed)
        return tuple(aliases)

    @property
    def search_blob(self) -> str:
        pieces = [
            self.skill_id,
            self.display_name,
            self.description,
            self.short_description,
            self.default_prompt,
            self.body,
        ]
        pieces.extend(path.stem for path in self.reference_paths)
        return _normalize_text(" ".join(part for part in pieces if part))

    def matches(self, query: str) -> bool:
        normalized = _normalize_key(query)
        if not normalized:
            return False
        if normalized in self.aliases:
            return True
        return any(alias and alias in normalized for alias in self.aliases)

    def render_context(self, *, max_chars: int = 2400, include_references: bool = True) -> str:
        sections: List[str] = [
            f"Skill: {self.display_name} ({self.skill_id})",
        ]
        if self.description:
            sections.append(f"Purpose: {self.description}")
        if self.default_prompt:
            sections.append(f"Platform prompt: {self.default_prompt}")

        if self.body:
            sections.append("Instructions:")
            sections.append(_truncate(self.body, min(max_chars, 1800)))

        if include_references and self.reference_paths:
            reference_lines: List[str] = []
            for path in self.reference_paths:
                excerpt = self._reference_excerpt(path, limit=360)
                if excerpt:
                    reference_lines.append(f"[{path.name}]\n{excerpt}")
            if reference_lines:
                sections.append("Reference notes:")
                sections.extend(reference_lines)

        return _truncate("\n".join(sections), max_chars)

    @staticmethod
    def _reference_excerpt(path: Path, *, limit: int = 360) -> str:
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            return ""
        return _truncate(text, limit)


@dataclass(slots=True)
class SkillResolution:
    mode: str
    selected_skill: SkillDefinition | None = None
    confidence: float = 0.0
    reason: str = ""
    trigger: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "selected_skill": self.selected_skill.skill_id if self.selected_skill else "",
            "display_name": self.selected_skill.display_name if self.selected_skill else "",
            "confidence": round(float(self.confidence), 3),
            "reason": self.reason,
            "trigger": self.trigger,
        }

    def render_context(self, *, max_chars: int = 2400) -> str:
        if self.selected_skill is None:
            return ""
        return self.selected_skill.render_context(max_chars=max_chars)


class SkillRegistry:
    def __init__(self, roots: Sequence[Path] | None = None) -> None:
        self.roots = [Path(root) for root in (roots or self.default_roots())]
        self._skills = self._load()

    @classmethod
    def default(cls) -> "SkillRegistry":
        return cls()

    @staticmethod
    def default_roots() -> List[Path]:
        roots = [PROJECT_ROOT / "skills"]
        env_value = os.getenv("MICRO_AGENT_SKILL_PATHS", "").strip()
        if env_value:
            for raw_path in env_value.split(os.pathsep):
                raw_path = raw_path.strip()
                if raw_path:
                    roots.append(Path(raw_path))
        codex_root = Path.home() / ".codex" / "skills"
        if codex_root.exists():
            roots.append(codex_root)
        return roots

    def list_skills(self) -> List[SkillDefinition]:
        return list(self._skills)

    def describe(self, *, include_aliases: bool = False) -> str:
        if not self._skills:
            return "No skills installed."
        lines: List[str] = []
        for skill in self._skills:
            summary = skill.short_description or skill.description or "No description."
            line = f"- {skill.skill_id}: {skill.display_name} - {summary}"
            if include_aliases and skill.aliases:
                line += f" | aliases: {', '.join(skill.aliases)}"
            lines.append(line)
        return "\n".join(lines)

    def find_skill(self, query: str) -> SkillDefinition | None:
        normalized = _normalize_key(query)
        if not normalized:
            return None

        skills = sorted(self._skills, key=lambda skill: len(skill.skill_id), reverse=True)
        for skill in skills:
            if skill.matches(normalized):
                return skill
        for skill in skills:
            if normalized in _normalize_key(skill.search_blob):
                return skill
        return None

    def _load(self) -> List[SkillDefinition]:
        skills: List[SkillDefinition] = []
        seen: set[str] = set()
        for root in self.roots:
            if not root.exists() or not root.is_dir():
                continue
            for child in sorted(root.iterdir(), key=lambda path: path.name.lower()):
                if not child.is_dir():
                    continue
                skill = SkillDefinition.from_directory(child)
                if skill is None:
                    continue
                resolved = str(skill.root.resolve())
                if resolved in seen:
                    continue
                seen.add(resolved)
                skills.append(skill)
        return skills


class SkillRouter:
    def __init__(
        self,
        registry: SkillRegistry,
        client: Any | None = None,
        *,
        confidence_threshold: float = 0.55,
        max_candidates: int = 8,
    ) -> None:
        self.registry = registry
        self.client = client
        self.confidence_threshold = float(confidence_threshold)
        self.max_candidates = max(1, int(max_candidates))

    def resolve(self, question: str, history: Sequence[Dict[str, str]] | None = None) -> SkillResolution:
        explicit = self._resolve_explicit(question)
        if explicit is not None:
            return explicit

        implicit = self._resolve_implicit(question, history or [])
        if implicit.selected_skill is not None and implicit.confidence >= self.confidence_threshold:
            return implicit

        fallback = self._heuristic_resolution(question)
        if fallback.selected_skill is not None:
            return fallback
        return SkillResolution(mode="none", reason="no skill matched")

    def _resolve_explicit(self, question: str) -> SkillResolution | None:
        text = str(question or "").strip()
        if not text:
            return None

        lowered = text.lower()
        explicit_markers = ("使用", "用", "请用", "启用", "调用", "切换到", "switch to", "use", "apply", "activate", "$")
        if not any(marker in lowered for marker in explicit_markers) and "$" not in text:
            return None

        normalized = _normalize_key(text)
        for skill in sorted(self.registry.list_skills(), key=lambda item: len(item.skill_id), reverse=True):
            if skill.matches(normalized):
                return SkillResolution(
                    mode="explicit",
                    selected_skill=skill,
                    confidence=1.0,
                    reason="explicit skill request",
                    trigger=text,
                )
        return SkillResolution(
            mode="explicit",
            selected_skill=None,
            confidence=0.0,
            reason="explicit skill request but no installed skill matched",
            trigger=text,
        )

    def _resolve_implicit(self, question: str, history: Sequence[Dict[str, str]]) -> SkillResolution:
        skills = self.registry.list_skills()
        if not skills:
            return SkillResolution(mode="none", reason="no installed skills")

        candidate_text = self._format_candidates(skills)
        try:
            raw = self.client.chat(
                [
                    {"role": "system", "content": SKILL_ROUTE_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            f"Conversation history:\n{_history_tail(history)}\n\n"
                            f"Available skills:\n{candidate_text}\n\n"
                            f"Current question:\n{question}"
                        ),
                    },
                ],
                temperature=0.0,
            )
            data = _parse_json_object(raw)
        except Exception:
            data = {}

        if not isinstance(data, dict):
            data = {}

        if not bool(data.get("use_skill")):
            return SkillResolution(mode="none", reason=str(data.get("reason") or "model chose no skill"))

        selected = self._resolve_skill_name(str(data.get("selected_skill") or ""))
        confidence = self._parse_confidence(data.get("confidence"))
        if selected is None:
            selected = self._heuristic_resolution(question).selected_skill
        if selected is None:
            return SkillResolution(mode="none", reason=str(data.get("reason") or "no matching skill"))
        return SkillResolution(
            mode="implicit",
            selected_skill=selected,
            confidence=confidence if confidence > 0 else 0.7,
            reason=str(data.get("reason") or "skill selected implicitly"),
            trigger=question,
        )

    def _heuristic_resolution(self, question: str) -> SkillResolution:
        normalized_question = _normalize_text(question).lower()
        if not normalized_question:
            return SkillResolution(mode="none", reason="empty question")

        best_skill: SkillDefinition | None = None
        best_score = 0
        for skill in self.registry.list_skills():
            score = self._skill_score(skill, normalized_question)
            if score > best_score:
                best_skill = skill
                best_score = score

        if best_skill is None or best_score <= 0:
            return SkillResolution(mode="none", reason="no heuristic skill match")

        return SkillResolution(
            mode="implicit",
            selected_skill=best_skill,
            confidence=min(0.95, 0.35 + best_score / 20.0),
            reason="heuristic skill match",
            trigger=question,
        )

    def _resolve_skill_name(self, value: str) -> SkillDefinition | None:
        value = value.strip()
        if not value:
            return None
        return self.registry.find_skill(value)

    def _skill_score(self, skill: SkillDefinition, normalized_question: str) -> int:
        normalized_blob = _normalize_text(skill.search_blob).lower()
        score = 0

        for token in self._query_terms(normalized_question):
            if token and token in normalized_blob:
                score += max(1, len(token))

        if any(marker in normalized_question for marker in ("先不写", "先不要写", "先聊", "先讨论", "先设计", "先探索", "不要修改", "不要创建", "架构", "设计", "探索", "方案", "规划", "技术选型", "落地")):
            score += 4

        return score

    @staticmethod
    def _query_terms(text: str) -> List[str]:
        pieces = [part.strip() for part in re.split(r"[\s,，。；;、/|]+", text) if part.strip()]
        if pieces:
            return pieces
        return [text.strip()] if text.strip() else []

    @staticmethod
    def _format_candidates(skills: Sequence[SkillDefinition]) -> str:
        selected = list(skills)[:8]
        lines = []
        for skill in selected:
            lines.append(
                f"- {skill.skill_id}: {skill.display_name} | {skill.short_description or skill.description}"
            )
        return "\n".join(lines) or "No skills installed."

    @staticmethod
    def _parse_confidence(value: Any) -> float:
        try:
            return max(0.0, min(1.0, float(value)))
        except Exception:
            return 0.0
