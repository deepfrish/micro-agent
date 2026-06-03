from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Sequence

from ..tools import Tool
from ..protocols.mcp.client import MCPServerConfig, load_mcp_tools
from .base import ToolProvider

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class AmapCapabilityProvider(ToolProvider):
    """External geospatial capability source backed by Amap APIs."""

    name = "amap"

    def load_tools(self) -> Sequence[Tool]:
        config = MCPServerConfig(
            command=[sys.executable, "-m", "coder", "mcp-server", "amap"],
            cwd=str(PROJECT_ROOT),
        )
        return load_mcp_tools(config, provider_name=self.name)
