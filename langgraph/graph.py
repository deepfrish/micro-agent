from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, Iterator, Mapping, MutableMapping


START = "__start__"
END = "__end__"


NodeFn = Callable[[Dict[str, Any]], Dict[str, Any]]
RouterFn = Callable[[Dict[str, Any]], str]


@dataclass
class _ConditionalEdge:
    router: RouterFn
    mapping: Dict[str, str]


class StateGraph:
    def __init__(self, state_type: Any | None = None) -> None:
        self.state_type = state_type
        self._nodes: Dict[str, NodeFn] = {}
        self._edges: Dict[str, str] = {}
        self._conditional_edges: Dict[str, _ConditionalEdge] = {}

    def add_node(self, name: str, fn: NodeFn) -> None:
        self._nodes[name] = fn

    def add_edge(self, source: str, target: str) -> None:
        self._edges[source] = target

    def add_conditional_edges(self, source: str, router: RouterFn, mapping: Dict[str, str]) -> None:
        self._conditional_edges[source] = _ConditionalEdge(router=router, mapping=dict(mapping))

    def compile(self, checkpointer: Any | None = None) -> "CompiledGraph":
        return CompiledGraph(
            nodes=dict(self._nodes),
            edges=dict(self._edges),
            conditional_edges=dict(self._conditional_edges),
            checkpointer=checkpointer,
        )


class CompiledGraph:
    def __init__(
        self,
        nodes: Dict[str, NodeFn],
        edges: Dict[str, str],
        conditional_edges: Dict[str, _ConditionalEdge],
        checkpointer: Any | None = None,
    ) -> None:
        self._nodes = nodes
        self._edges = edges
        self._conditional_edges = conditional_edges
        self._checkpointer = checkpointer

    def invoke(self, state: Dict[str, Any], config: Dict[str, Any] | None = None) -> Dict[str, Any]:
        final_state = state
        for _, node_state in self._iterate(state, config=config, stream_mode=None):
            final_state = node_state
        return final_state

    def stream(
        self,
        state: Dict[str, Any],
        config: Dict[str, Any] | None = None,
        stream_mode: str = "updates",
    ) -> Iterator[Dict[str, Dict[str, Any]]]:
        for node_name, node_state in self._iterate(state, config=config, stream_mode=stream_mode):
            yield {node_name: node_state}

    def _iterate(
        self,
        state: Dict[str, Any],
        config: Dict[str, Any] | None = None,
        stream_mode: str | None = None,
    ) -> Iterator[tuple[str, Dict[str, Any]]]:
        current_state = dict(state)
        current_node = self._edges.get(START)
        safety_limit = 1000
        hops = 0

        while current_node and current_node != END and hops < safety_limit:
            hops += 1
            node_fn = self._nodes[current_node]
            next_state = node_fn(current_state)
            if not isinstance(next_state, MutableMapping):
                raise TypeError(f"Node {current_node!r} must return a mapping.")

            current_state = dict(next_state)
            yield current_node, current_state

            next_node = self._next_node(current_node, current_state)
            if next_node == END:
                break
            current_node = next_node

    def _next_node(self, current_node: str, state: Dict[str, Any]) -> str:
        if current_node in self._conditional_edges:
            conditional = self._conditional_edges[current_node]
            route = conditional.router(state)
            return conditional.mapping.get(route, END)
        return self._edges.get(current_node, END)
