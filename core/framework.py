from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Sequence

from .llm_client import DeepSeekClient


@dataclass(slots=True)
class Message:
    role: str
    content: str

    def to_dict(self) -> Dict[str, str]:
        return {"role": self.role, "content": self.content}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Message":
        return cls(role=str(data.get("role", "")), content=str(data.get("content", "")))


@dataclass(slots=True)
class AgentConfig:
    model: str = "deepseek-v4-pro"
    temperature: float = 0.2
    max_steps: int = 8
    max_tool_errors: int = 2
    working_memory_capacity: int = 5
    timeout: float = 120.0
    thread_id: str = "agent"
    memory_namespace: str = "default"


class Agent(ABC):
    client: Any
    config: AgentConfig
    graph: Any

    def __init__(self, client: Any | None = None, config: AgentConfig | None = None) -> None:
        self.config = config or AgentConfig()
        self.client = client or self._create_client(self.config)
        self.graph = self._build_graph()

    def _create_client(self, config: AgentConfig) -> DeepSeekClient:
        return DeepSeekClient(model=config.model, timeout=config.timeout)

    @abstractmethod
    def _build_graph(self):
        raise NotImplementedError

    @abstractmethod
    def build_initial_state(self, question: str, history_messages: List[Dict[str, str]] | None = None):
        raise NotImplementedError

    def run(self, question: str, history_messages: List[Dict[str, str]] | None = None) -> str:
        final_state = self.graph.invoke(self.build_initial_state(question, history_messages=history_messages))
        return final_state.get("final_answer") or "Stopped because the agent did not produce a final answer."

    def chat(self, messages: List[Dict[str, str]], temperature: float | None = None) -> str:
        if temperature is None:
            return self.client.chat(messages)
        try:
            return self.client.chat(messages, temperature=temperature)
        except TypeError:
            return self.client.chat(messages)

    @staticmethod
    def message(role: str, content: str) -> Dict[str, str]:
        return Message(role=role, content=content).to_dict()

    @staticmethod
    def messages_to_dicts(messages: Sequence[Message]) -> List[Dict[str, str]]:
        return [message.to_dict() for message in messages]
