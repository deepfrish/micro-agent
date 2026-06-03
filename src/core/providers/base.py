from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Sequence

from ..tools import Tool


class ToolProvider(ABC):
    """Groups a family of tools that come from the same capability source."""

    name: str = "provider"

    @abstractmethod
    def load_tools(self) -> Sequence[Tool]:
        raise NotImplementedError

