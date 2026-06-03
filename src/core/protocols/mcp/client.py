from __future__ import annotations

import atexit
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from ...tools import ParameterInput, Tool, ToolParameter

PROJECT_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True, slots=True)
class MCPServerConfig:
    command: Sequence[str]
    cwd: str | None = None
    env: Mapping[str, str] | None = None
    startup_timeout: float = 10.0
    name: str = "mcp-server"


@dataclass(frozen=True, slots=True)
class MCPToolDescriptor:
    name: str
    description: str
    parameters: List[ToolParameter]


class MCPClientSession:
    def __init__(self, config: MCPServerConfig) -> None:
        self.config = config
        self._process = self._spawn_process()
        self._lock = Lock()
        self._next_id = 1
        self._closed = False
        atexit.register(self.close)
        self.initialize()

    def initialize(self) -> dict:
        return self._request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "clientInfo": {
                    "name": "micro-agent",
                    "version": "0.1.0",
                },
                "capabilities": {"tools": {}},
            },
        )

    def list_tools(self) -> List[MCPToolDescriptor]:
        response = self._request("tools/list", {})
        tools = response.get("tools") or []
        return [self._parse_tool_descriptor(tool) for tool in tools if isinstance(tool, dict)]

    def call_tool(self, name: str, arguments: Mapping[str, Any] | None = None) -> str:
        response = self._request(
            "tools/call",
            {
                "name": name,
                "arguments": dict(arguments or {}),
            },
        )
        content = response.get("content") or []
        texts: List[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text" and isinstance(block.get("text"), str):
                texts.append(block["text"])
        if texts:
            return "\n".join(texts)
        if response.get("isError"):
            return f"MCP tool error: {response.get('message', 'unknown error')}"
        return json.dumps(response, ensure_ascii=False)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self._process.poll() is None:
                try:
                    self._request("shutdown", {}, allow_dead_process=True)
                except Exception:
                    pass
                self._process.terminate()
                try:
                    self._process.wait(timeout=2)
                except Exception:
                    self._process.kill()
        finally:
            for stream_name in ("stdin", "stdout"):
                stream = getattr(self._process, stream_name, None)
                if stream:
                    try:
                        stream.close()
                    except Exception:
                        pass

    def _spawn_process(self) -> subprocess.Popen[str]:
        env = os.environ.copy()
        if self.config.env:
            env.update(dict(self.config.env))
        return subprocess.Popen(
            list(self.config.command),
            cwd=self.config.cwd or str(PROJECT_ROOT),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=False,
            bufsize=0,
            env=env,
        )

    def _request(self, method: str, params: Mapping[str, Any], allow_dead_process: bool = False) -> dict:
        if self._process.poll() is not None and not allow_dead_process:
            raise RuntimeError(f"MCP server exited with code {self._process.returncode}")

        with self._lock:
            request_id = self._next_id
            self._next_id += 1
            payload = {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": dict(params),
            }
            if self._process.stdin is None or self._process.stdout is None:
                raise RuntimeError("MCP transport is not available.")
            self._process.stdin.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
            self._process.stdin.flush()

            while True:
                raw = self._process.stdout.readline()
                if not raw:
                    if self._process.poll() is not None:
                        raise RuntimeError(f"MCP server exited with code {self._process.returncode}")
                    continue
                try:
                    response = json.loads(raw.decode("utf-8"))
                except json.JSONDecodeError:
                    continue
                if not isinstance(response, dict):
                    continue
                if response.get("id") != request_id:
                    continue
                if "error" in response and isinstance(response["error"], dict):
                    error = response["error"]
                    raise RuntimeError(error.get("message", "MCP request failed"))
                return response.get("result") if isinstance(response.get("result"), dict) else {}

    @staticmethod
    def _parse_tool_descriptor(tool: Mapping[str, Any]) -> MCPToolDescriptor:
        schema = tool.get("inputSchema")
        parameters = _schema_to_parameters(schema if isinstance(schema, dict) else {})
        return MCPToolDescriptor(
            name=str(tool.get("name") or "").strip(),
            description=str(tool.get("description") or "").strip(),
            parameters=parameters,
        )


class MCPTool(Tool):
    def __init__(
        self,
        client: MCPClientSession,
        name: str,
        description: str,
        parameters: Sequence[ToolParameter],
        *,
        source_label: str = "mcp",
    ) -> None:
        super().__init__(name=name, description=description, source_label=source_label)
        self.client = client
        self._parameters = list(parameters)

    def run(self, parameters: ParameterInput) -> str:
        normalized = self.normalize_parameters(parameters)
        try:
            return self.client.call_tool(self.name, normalized)
        except Exception as exc:
            return f"MCP tool error: {exc}"

    def get_parameters(self) -> Sequence[ToolParameter]:
        return self._parameters


def load_mcp_tools(config: MCPServerConfig, *, provider_name: str = "mcp") -> List[MCPTool]:
    client: MCPClientSession | None = None
    try:
        client = MCPClientSession(config)
        descriptors = client.list_tools()
    except Exception:
        if client is not None:
            client.close()
        return []

    tools: List[MCPTool] = []
    source_label = f"{provider_name}/mcp" if provider_name else "mcp"
    for descriptor in descriptors:
        if not descriptor.name:
            continue
        tools.append(
            MCPTool(
                client,
                descriptor.name,
                descriptor.description,
                descriptor.parameters,
                source_label=source_label,
            )
        )
    if not tools:
        client.close()
    return tools


def load_default_weather_tools() -> List[MCPTool]:
    config = MCPServerConfig(
        command=[sys.executable, "-m", "coder", "mcp-server", "weather"],
        cwd=str(PROJECT_ROOT),
    )
    return load_mcp_tools(config, provider_name="amap")


def _schema_to_parameters(schema: Mapping[str, Any]) -> List[ToolParameter]:
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    required = set(schema.get("required") or [])
    parameters: List[ToolParameter] = []
    for name, definition in properties.items():
        if not isinstance(name, str) or not isinstance(definition, dict):
            continue
        parameters.append(
            ToolParameter(
                name=name,
                type=str(definition.get("type") or "string"),
                description=str(definition.get("description") or ""),
                required=name in required,
                default=definition.get("default"),
            )
        )
    return parameters
