from __future__ import annotations

import sys
from pathlib import Path
from typing import Sequence

from ..protocols.mcp.client import MCPServerConfig, load_mcp_tools
from ..tools import Tool
from .base import ToolProvider

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FREEWEB_ROOT = PROJECT_ROOT / "mcp_servers" / "freeweb"
FREEWEB_DIST = FREEWEB_ROOT / "dist" / "index.js"


class FreeWebProvider(ToolProvider):
    """Web browsing and extraction capability source."""

    name = "freeweb"

    def load_tools(self) -> Sequence[Tool]:
        config = self._build_config()
        return load_mcp_tools(config, provider_name=self.name)

    def _build_config(self) -> MCPServerConfig:
        if FREEWEB_DIST.exists():
            return MCPServerConfig(
                command=["node", str(FREEWEB_DIST)],
                cwd=str(FREEWEB_ROOT),
                env={"FREEWEB_ENGINES": "chromium"},
            )

        cmd = "npx.cmd" if sys.platform == "win32" else "npx"
        return MCPServerConfig(
            command=[cmd, "-y", "freeweb-mcp@latest"],
            cwd=str(PROJECT_ROOT),
            env={"FREEWEB_ENGINES": "chromium"},
        )

