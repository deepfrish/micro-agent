from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Sequence

from ...tools import (
    ToolParameter,
    _amap_url,
    _fetch_json,
    _first_dict,
    _load_amap_key,
    _normalize_location_query,
    _normalize_pois,
    _parse_lon_lat,
    _pick_location_value,
    _resolve_location,
    build_static_map_url,
    nearby_search,
    weather,
)


@dataclass(slots=True)
class MCPToolDefinition:
    name: str
    description: str
    parameters: Sequence[ToolParameter]
    handler: Callable[[Mapping[str, Any]], str]


@dataclass(slots=True)
class JsonLineMCPServer:
    name: str = "micro-agent-mcp"
    version: str = "0.1.0"
    tools: List[MCPToolDefinition] = field(default_factory=list)

    def register_tool(self, tool: MCPToolDefinition) -> None:
        self.tools.append(tool)

    def serve(self) -> None:
        if hasattr(sys.stdin, "reconfigure"):
            try:
                sys.stdin.reconfigure(encoding="utf-8", errors="strict", newline="\n")
            except Exception:
                pass
        if hasattr(sys.stdout, "reconfigure"):
            try:
                sys.stdout.reconfigure(encoding="utf-8", errors="strict", newline="\n", write_through=True)
            except Exception:
                pass
        for raw in sys.stdin:
            line = raw.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
            except json.JSONDecodeError:
                self._write_error(None, -32700, "Parse error")
                continue
            if not isinstance(request, dict):
                self._write_error(None, -32600, "Invalid request")
                continue
            request_id = request.get("id")
            method = str(request.get("method") or "")
            params = request.get("params")
            if not isinstance(params, dict):
                params = {}
            try:
                result = self._handle(method, params)
            except Exception as exc:
                self._write_error(request_id, -32000, str(exc))
                continue
            self._write_result(request_id, result)

    def _handle(self, method: str, params: Mapping[str, Any]) -> dict:
        if method == "initialize":
            return {
                "protocolVersion": str(params.get("protocolVersion") or "2024-11-05"),
                "serverInfo": {
                    "name": self.name,
                    "version": self.version,
                },
                "capabilities": {"tools": {}},
            }
        if method == "tools/list":
            return {
                "tools": [
                    {
                        "name": tool.name,
                        "description": tool.description,
                        "inputSchema": _tool_schema(tool.parameters),
                    }
                    for tool in self.tools
                ]
            }
        if method == "tools/call":
            tool_name = str(params.get("name") or "").strip()
            arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
            tool = next((item for item in self.tools if item.name.lower() == tool_name.lower()), None)
            if tool is None:
                raise ValueError(f"Unknown tool: {tool_name}")
            text = tool.handler(arguments)
            return {
                "content": [{"type": "text", "text": text}],
                "isError": False,
            }
        if method == "shutdown":
            raise SystemExit(0)
        raise ValueError(f"Unknown method: {method}")

    @staticmethod
    def _write_result(request_id: Any, result: Mapping[str, Any]) -> None:
        response = {"jsonrpc": "2.0", "id": request_id, "result": dict(result)}
        sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        sys.stdout.flush()

    @staticmethod
    def _write_error(request_id: Any, code: int, message: str) -> None:
        response = {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        }
        sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        sys.stdout.flush()


def _tool_schema(parameters: Sequence[ToolParameter]) -> dict:
    properties: Dict[str, dict] = {}
    required: List[str] = []
    for parameter in parameters:
        properties[parameter.name] = {
            "type": parameter.type,
            "description": parameter.description,
        }
        if parameter.default is not None:
            properties[parameter.name]["default"] = parameter.default
        if parameter.required:
            required.append(parameter.name)
    schema: Dict[str, Any] = {
        "type": "object",
        "properties": properties,
    }
    if required:
        schema["required"] = required
    return schema


def _error(prefix: str, message: str) -> str:
    return f"Tool error: [{prefix}] {message}. Please adjust your tool input and try again."


def _require_api_key(prefix: str) -> str:
    api_key = _load_amap_key()
    if not api_key:
        raise ValueError(_error(prefix, "missing GAODE_API_KEY."))
    return api_key


def _resolve_point(text: str, api_key: str) -> tuple[str, str]:
    query = _normalize_location_query(text)
    coordinate = _parse_lon_lat(query)
    if coordinate is not None:
        lon, lat = coordinate
        coord_text = f"{lon:.6f},{lat:.6f}"
        return coord_text, coord_text
    resolved = _resolve_location(query, api_key)
    return resolved["location"], resolved["name"]


def _first_text(values: Mapping[str, Any], keys: Sequence[str]) -> str:
    for key in keys:
        value = values.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _preview_item(item: Any) -> str:
    if not isinstance(item, dict):
        return str(item)
    for key in (
        "instruction",
        "assistant_action",
        "action",
        "name",
        "line_name",
        "busline_name",
        "road",
        "railway",
        "transit_mode",
    ):
        value = item.get(key)
        if value not in (None, ""):
            return f"{key}: {value}"
    pairs = []
    for key in ("distance", "duration", "cost", "id", "start_stop", "end_stop"):
        value = item.get(key)
        if value not in (None, ""):
            pairs.append(f"{key}={value}")
    return ", ".join(pairs) if pairs else json.dumps(item, ensure_ascii=False)[:240]


def _summarize_collection(title: str, items: Any, limit: int = 3) -> str:
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list):
        return ""
    entries = [item for item in items if isinstance(item, dict)]
    if not entries:
        return ""
    lines = [f"{title}: {len(entries)}"]
    for index, item in enumerate(entries[:limit], start=1):
        lines.append(f"{index}. {_preview_item(item)}")
    return "\n".join(lines)


def geocode(address: str, city: str = "") -> str:
    api_key = _require_api_key("Geocode")
    address = _normalize_location_query(address)
    if not address:
        return _error("Geocode", "empty address.")

    params: Dict[str, Any] = {
        "key": api_key,
        "address": address,
        "output": "JSON",
    }
    if city.strip():
        params["city"] = city.strip()

    try:
        data = _fetch_json(_amap_url("GAODE_GEOCODE_URL"), params)
    except Exception as exc:
        return _error("Geocode", str(exc))

    if data.get("status") != "1":
        return _error("Geocode", str(data.get("info") or "unknown error"))

    item = _first_dict(data.get("geocodes") or [])
    if not item:
        return "Geocode: no result."

    lines = [f"Address: {address}"]
    for label, key in (
        ("Formatted", "formatted_address"),
        ("Location", "location"),
        ("Province", "province"),
        ("City", "city"),
        ("District", "district"),
        ("Adcode", "adcode"),
        ("Level", "level"),
    ):
        value = item.get(key)
        if value not in (None, ""):
            lines.append(f"{label}: {value}")
    return "\n".join(lines)


def regeocode(location: str, radius: int = 1000, extensions: str = "base", poitype: str = "", roadlevel: str = "") -> str:
    api_key = _require_api_key("Regeocode")
    location = _normalize_location_query(location)
    if not location:
        return _error("Regeocode", "empty location.")

    try:
        resolved_location, resolved_name = _resolve_point(location, api_key)
        data = _fetch_json(
            _amap_url("GAODE_REGEOCODE_URL"),
            {
                "key": api_key,
                "location": resolved_location,
                "radius": max(0, min(int(radius), 3000)),
                "extensions": extensions or "base",
                "poitype": poitype.strip(),
                "roadlevel": roadlevel.strip(),
                "output": "JSON",
            },
        )
    except Exception as exc:
        return _error("Regeocode", str(exc))

    if data.get("status") != "1":
        return _error("Regeocode", str(data.get("info") or "unknown error"))

    regeocode_data = data.get("regeocode") if isinstance(data.get("regeocode"), dict) else {}
    if not regeocode_data:
        return "Regeocode: no result."

    component = regeocode_data.get("addressComponent") if isinstance(regeocode_data.get("addressComponent"), dict) else {}
    pois = regeocode_data.get("pois") or []
    roads = regeocode_data.get("roads") or []
    roadinters = regeocode_data.get("roadinters") or []

    lines = [
        f"Input: {resolved_name} ({resolved_location})",
        f"Formatted address: {regeocode_data.get('formatted_address', '?')}",
    ]
    for label, key in (
        ("Country", "country"),
        ("Province", "province"),
        ("City", "city"),
        ("District", "district"),
        ("Township", "township"),
        ("Adcode", "adcode"),
        ("Citycode", "citycode"),
    ):
        value = component.get(key)
        if value not in (None, ""):
            lines.append(f"{label}: {value}")

    poi_summary = _summarize_collection("Nearby POIs", pois, limit=3)
    if poi_summary:
        lines.append(poi_summary)
    road_summary = _summarize_collection("Nearby roads", roads, limit=3)
    if road_summary:
        lines.append(road_summary)
    roadinter_summary = _summarize_collection("Road intersections", roadinters, limit=3)
    if roadinter_summary:
        lines.append(roadinter_summary)

    return "\n".join(lines)


def inputtips(keywords: str, city: str = "", type: str = "", location: str = "", datatype: str = "all") -> str:  # noqa: A002
    api_key = _require_api_key("InputTips")
    keywords = _normalize_location_query(keywords)
    if not keywords:
        return _error("InputTips", "empty keywords.")

    params: Dict[str, Any] = {
        "key": api_key,
        "keywords": keywords,
        "datatype": datatype or "all",
        "output": "JSON",
    }
    if city.strip():
        params["city"] = city.strip()
    if type.strip():
        params["type"] = type.strip()
    if location.strip():
        params["location"] = location.strip()

    try:
        data = _fetch_json(_amap_url("GAODE_INPUTTIPS_URL"), params)
    except Exception as exc:
        return _error("InputTips", str(exc))

    if data.get("status") != "1":
        return _error("InputTips", str(data.get("info") or "unknown error"))

    tips = data.get("tips") or []
    if isinstance(tips, dict):
        tips = [tips]
    if not isinstance(tips, list) or not tips:
        return "InputTips: no result."

    lines = [f"Keywords: {keywords}"]
    for index, tip in enumerate([item for item in tips if isinstance(item, dict)][:10], start=1):
        lines.append(
            f"{index}. {tip.get('name', '?')} | {tip.get('district', '?')} | {tip.get('adcode', '?')} | "
            f"{tip.get('typecode', '?')} | location {tip.get('location', '?')}"
        )
    return "\n".join(lines)


def route(origin: str, destination: str, mode: str = "walking", city: str = "", strategy: str = "0", nightflag: int = 0) -> str:
    api_key = _require_api_key("Route")
    mode = (mode or "walking").strip().lower()
    if not origin.strip() or not destination.strip():
        return _error("Route", "origin and destination are required.")

    try:
        if mode == "transit" and not city.strip():
            resolved_origin = _resolve_location(origin, api_key)
            origin_coord = resolved_origin["location"]
            origin_label = resolved_origin["name"]
            city = resolved_origin["adcode"]
        else:
            origin_coord, origin_label = _resolve_point(origin, api_key)
        destination_coord, destination_label = _resolve_point(destination, api_key)
    except Exception as exc:
        return _error("Route", str(exc))

    if mode == "walking":
        url = _amap_url("GAODE_WALKING_URL")
        params = {
            "key": api_key,
            "origin": origin_coord,
            "destination": destination_coord,
            "output": "JSON",
        }
    elif mode == "driving":
        url = _amap_url("GAODE_DRIVING_URL")
        params = {
            "key": api_key,
            "origin": origin_coord,
            "destination": destination_coord,
            "extensions": "all",
            "output": "JSON",
        }
        if strategy != "":
            params["strategy"] = strategy
    elif mode == "transit":
        url = _amap_url("GAODE_TRANSIT_URL")
        params = {
            "key": api_key,
            "origin": origin_coord,
            "destination": destination_coord,
            "city": city.strip(),
            "strategy": strategy or "0",
            "nightflag": int(nightflag),
            "output": "JSON",
        }
        if not params["city"]:
            return _error("Route", "transit mode requires city.")
    else:
        return _error("Route", f"unsupported mode '{mode}'.")

    try:
        data = _fetch_json(url, params)
    except Exception as exc:
        return _error("Route", str(exc))

    if data.get("status") != "1":
        return _error("Route", str(data.get("info") or "unknown error"))

    route_data = data.get("route") if isinstance(data.get("route"), dict) else {}
    if not route_data:
        return "Route: no result."

    entries_key = "transits" if mode == "transit" else "paths"
    entries = route_data.get(entries_key) or []
    if isinstance(entries, dict):
        entries = [entries]
    first = _first_dict(entries)

    lines = [
        f"Mode: {mode}",
        f"Origin: {origin_label} ({origin_coord})",
        f"Destination: {destination_label} ({destination_coord})",
    ]
    if city.strip():
        lines.append(f"City: {city.strip()}")

    for label, key in (
        ("Distance", "distance"),
        ("Duration", "duration"),
        ("Cost", "cost"),
        ("Tolls", "tolls"),
        ("Traffic lights", "traffic_lights"),
        ("Walking distance", "walking_distance"),
    ):
        value = first.get(key)
        if value not in (None, ""):
            lines.append(f"{label}: {value}")

    preview = first.get("steps") or first.get("segments") or []
    preview_text = _summarize_collection("Preview", preview, limit=3)
    if preview_text:
        lines.append(preview_text)
    else:
        raw_preview = json.dumps(first, ensure_ascii=False)[:800]
        if raw_preview:
            lines.append(f"Preview: {raw_preview}")

    return "\n".join(lines)


def bus(keywords: str = "", city: str = "", line_id: str = "", offset: int = 10, page: int = 1, extensions: str = "base") -> str:
    api_key = _require_api_key("Bus")
    line_id = line_id.strip()
    if line_id:
        try:
            data = _fetch_json(
                _amap_url("GAODE_BUS_LINEID_URL"),
                {
                    "key": api_key,
                    "id": line_id,
                    "extensions": extensions or "base",
                    "output": "JSON",
                },
            )
        except Exception as exc:
            return _error("Bus", str(exc))
        query_label = f"line id {line_id}"
    else:
        keywords = _normalize_location_query(keywords)
        if not keywords:
            return _error("Bus", "keywords or line_id is required.")
        city = city.strip()
        if not city:
            return _error("Bus", "city is required for bus line keyword search.")
        try:
            data = _fetch_json(
                _amap_url("GAODE_BUS_LINENAME_URL"),
                {
                    "key": api_key,
                    "keywords": keywords,
                    "city": city,
                    "offset": max(1, min(int(offset), 100)),
                    "page": max(1, int(page)),
                    "extensions": extensions or "base",
                    "output": "JSON",
                },
            )
        except Exception as exc:
            return _error("Bus", str(exc))
        query_label = f"keywords '{keywords}' in {city}"

    if data.get("status") != "1":
        return _error("Bus", str(data.get("info") or "unknown error"))

    buslines = data.get("buslines") or data.get("busline") or data.get("busstops") or []
    if isinstance(buslines, dict):
        buslines = [buslines]
    entries = [item for item in buslines if isinstance(item, dict)]
    if not entries:
        return "Bus: no result."

    lines = [f"Query: {query_label}", f"Total results: {data.get('count', len(entries))}"]
    for index, item in enumerate(entries[: max(1, min(int(offset), 10))], start=1):
        lines.append(
            f"{index}. {item.get('name', '?')} | id {item.get('id', '?')} | "
            f"{item.get('start_stop', '?')} -> {item.get('end_stop', '?')} | "
            f"{item.get('cityname', item.get('citycode', '?'))}"
        )
    return "\n".join(lines)


def transit_navigation(origin: str, destination: str, strategy: str = "0", nightflag: int = 0) -> str:
    api_key = _require_api_key("TransitNavigation")
    if not origin.strip() or not destination.strip():
        return _error("TransitNavigation", "origin and destination are required.")

    try:
        resolved_origin = _resolve_location(origin, api_key)
        origin_coord = resolved_origin["location"]
        origin_label = resolved_origin["name"]
        city = resolved_origin["adcode"]

        destination_coord, destination_label = _resolve_point(destination, api_key)
    except Exception as exc:
        return _error("TransitNavigation", str(exc))

    params = {
        "key": api_key,
        "origin": origin_coord,
        "destination": destination_coord,
        "city": city.strip(),
        "strategy": strategy or "0",
        "nightflag": int(nightflag),
        "output": "JSON",
    }

    try:
        data = _fetch_json(_amap_url("GAODE_TRANSIT_URL"), params)
    except Exception as exc:
        return _error("TransitNavigation", str(exc))

    if data.get("status") != "1":
        return _error("TransitNavigation", str(data.get("info") or "unknown error"))

    route_data = data.get("route") if isinstance(data.get("route"), dict) else {}
    if not route_data:
        return "TransitNavigation: no result."

    transits = route_data.get("transits") or []
    if isinstance(transits, dict):
        transits = [transits]
    entries = [item for item in transits if isinstance(item, dict)]

    if not entries:
        return "TransitNavigation: no routes found."

    lines = [
        f"Transit Routes from {origin_label} to {destination_label}:",
    ]

    for index, transit in enumerate(entries[:5], start=1):
        cost = transit.get("cost", "?")
        duration = int(transit.get("duration", 0) or 0) // 60
        walking = transit.get("walking_distance", "?")
        
        segments = transit.get("segments") or []
        if isinstance(segments, dict):
            segments = [segments]
        
        route_instructions = []
        for segment in segments:
            if not isinstance(segment, dict):
                continue
            bus = segment.get("bus") or {}
            if isinstance(bus, dict):
                buslines = bus.get("buslines") or []
                if isinstance(buslines, dict):
                    buslines = [buslines]
                if isinstance(buslines, list) and buslines:
                    busline = buslines[0]
                    if isinstance(busline, dict):
                        dep = busline.get("departure_stop", {})
                        dep_name = dep.get("name", "") if isinstance(dep, dict) else ""
                        route_instructions.append(f"乘坐{busline.get('name', '公交')} ({dep_name}上车, 途经{busline.get('via_num', '?')}站)")
            
            railway = segment.get("railway") or {}
            if isinstance(railway, dict):
                name = railway.get("name") or railway.get("trip", "")
                dep = railway.get("departure_stop", {})
                dep_name = dep.get("name", "") if isinstance(dep, dict) else ""
                if name:
                    route_instructions.append(f"乘坐{name} ({dep_name}上站)")

        route_desc = " -> ".join(route_instructions) if route_instructions else "直达"
        lines.append(f"方案 {index}: 耗时约{duration}分钟, 花费{cost}元, 步行约{walking}米. 路线: {route_desc}")

    return "\n".join(lines)


def build_weather_server() -> JsonLineMCPServer:
    server = JsonLineMCPServer(name="micro-agent-amap-weather")
    server.register_tool(
        MCPToolDefinition(
            name="Weather",
            description="Get current weather and a short forecast for a location using Amap weather API.",
            parameters=[
                ToolParameter(
                    name="location",
                    type="string",
                    description="A city, district, address, or 'longitude,latitude' coordinate. Prefer the place name only.",
                    required=False,
                    default="",
                )
            ],
            handler=lambda arguments: weather(str(arguments.get("location", ""))),
        )
    )
    return server


def build_amap_server() -> JsonLineMCPServer:
    server = JsonLineMCPServer(name="micro-agent-amap")
    server.register_tool(
        MCPToolDefinition(
            name="Weather",
            description="Get current weather and a short forecast for a location using Amap weather API.",
            parameters=[
                ToolParameter(
                    name="location",
                    type="string",
                    description="A city, district, address, or 'longitude,latitude' coordinate. Prefer the place name only.",
                    required=False,
                    default="",
                )
            ],
            handler=lambda arguments: weather(str(arguments.get("location", ""))),
        )
    )
    server.register_tool(
        MCPToolDefinition(
            name="Geocode",
            description="Convert a text address into latitude/longitude with Amap geocoding.",
            parameters=[
                ToolParameter(name="address", type="string", description="Address to geocode.", required=True),
                ToolParameter(name="city", type="string", description="Optional city hint.", required=False, default=""),
            ],
            handler=lambda arguments: geocode(str(arguments.get("address", "")), str(arguments.get("city", ""))),
        )
    )
    server.register_tool(
        MCPToolDefinition(
            name="Regeocode",
            description="Convert a coordinate or location string into a formatted address with Amap reverse geocoding.",
            parameters=[
                ToolParameter(name="location", type="string", description="Coordinate or location string.", required=True),
                ToolParameter(name="radius", type="integer", description="POI radius in meters.", required=False, default=1000),
                ToolParameter(name="extensions", type="string", description="Return base or all data.", required=False, default="base"),
                ToolParameter(name="poitype", type="string", description="Optional POI type filter.", required=False, default=""),
                ToolParameter(name="roadlevel", type="string", description="Optional road filter.", required=False, default=""),
            ],
            handler=lambda arguments: regeocode(
                str(arguments.get("location", "")),
                int(arguments.get("radius", 1000)),
                str(arguments.get("extensions", "base")),
                str(arguments.get("poitype", "")),
                str(arguments.get("roadlevel", "")),
            ),
        )
    )
    server.register_tool(
        MCPToolDefinition(
            name="StaticMap",
            description="Build an Amap static map image URL for a city, address, or coordinate.",
            parameters=[
                ToolParameter(name="location", type="string", description="City, address, or coordinate.", required=False, default=""),
                ToolParameter(name="zoom", type="integer", description="Map zoom level from 1 to 17.", required=False, default=13),
                ToolParameter(name="size", type="string", description="Image size as width*height.", required=False, default="600*400"),
                ToolParameter(name="scale", type="integer", description="Image scale, 1 or 2.", required=False, default=1),
            ],
            handler=lambda arguments: build_static_map_url(
                str(arguments.get("location", "")),
                zoom=int(arguments.get("zoom", 13)),
                size=str(arguments.get("size", "600*400")),
                scale=int(arguments.get("scale", 1)),
            ),
        )
    )
    server.register_tool(
        MCPToolDefinition(
            name="NearbySearch",
            description="Search nearby POIs around a city, address, or coordinate using Amap around search API.",
            parameters=[
                ToolParameter(name="location", type="string", description="Search center.", required=False, default=""),
                ToolParameter(name="keywords", type="string", description="POI keyword.", required=False, default=""),
                ToolParameter(name="types", type="string", description="POI type code filter.", required=False, default=""),
                ToolParameter(name="radius", type="integer", description="Search radius in meters.", required=False, default=1000),
                ToolParameter(name="page", type="integer", description="Result page number.", required=False, default=1),
                ToolParameter(name="offset", type="integer", description="Maximum number of results.", required=False, default=10),
            ],
            handler=lambda arguments: nearby_search(
                location=str(arguments.get("location", "")),
                keywords=str(arguments.get("keywords", "")),
                types=str(arguments.get("types", "")),
                radius=int(arguments.get("radius", 1000)),
                page=int(arguments.get("page", 1)),
                offset=int(arguments.get("offset", 10)),
            ),
        )
    )
    server.register_tool(
        MCPToolDefinition(
            name="InputTips",
            description="Get suggestion tips for a keyword from Amap.",
            parameters=[
                ToolParameter(name="keywords", type="string", description="Search keyword.", required=True),
                ToolParameter(name="city", type="string", description="Optional city hint.", required=False, default=""),
                ToolParameter(name="type", type="string", description="Optional POI type code filter.", required=False, default=""),
                ToolParameter(name="location", type="string", description="Optional location bias.", required=False, default=""),
                ToolParameter(name="datatype", type="string", description="Return datatype: all, poi, bus, busline.", required=False, default="all"),
            ],
            handler=lambda arguments: inputtips(
                str(arguments.get("keywords", "")),
                str(arguments.get("city", "")),
                str(arguments.get("type", "")),
                str(arguments.get("location", "")),
                str(arguments.get("datatype", "all")),
            ),
        )
    )
    server.register_tool(
        MCPToolDefinition(
            name="Route",
            description="Plan walking, driving, or transit routes with Amap.",
            parameters=[
                ToolParameter(name="origin", type="string", description="Origin coordinate or location.", required=True),
                ToolParameter(name="destination", type="string", description="Destination coordinate or location.", required=True),
                ToolParameter(name="mode", type="string", description="walking, driving, or transit.", required=False, default="walking"),
                ToolParameter(name="city", type="string", description="Required for transit mode, but will auto-infer from origin if left empty.", required=False, default=""),
                ToolParameter(name="strategy", type="string", description="Routing strategy code.", required=False, default="0"),
                ToolParameter(name="nightflag", type="integer", description="Night bus flag for transit.", required=False, default=0),
            ],
            handler=lambda arguments: route(
                str(arguments.get("origin", "")),
                str(arguments.get("destination", "")),
                str(arguments.get("mode", "walking")),
                str(arguments.get("city", "")),
                str(arguments.get("strategy", "0")),
                int(arguments.get("nightflag", 0)),
            ),
        )
    )
    server.register_tool(
        MCPToolDefinition(
            name="TransitNavigation",
            description="A specialized composite tool to get simplified human-readable public transit (bus/subway) directions.",
            parameters=[
                ToolParameter(name="origin", type="string", description="Origin coordinate or location name.", required=True),
                ToolParameter(name="destination", type="string", description="Destination coordinate or location name.", required=True),
                ToolParameter(name="strategy", type="string", description="Routing strategy code.", required=False, default="0"),
                ToolParameter(name="nightflag", type="integer", description="Night bus flag for transit (0 or 1).", required=False, default=0),
            ],
            handler=lambda arguments: transit_navigation(
                str(arguments.get("origin", "")),
                str(arguments.get("destination", "")),
                str(arguments.get("strategy", "0")),
                int(arguments.get("nightflag", 0)),
            ),
        )
    )
    server.register_tool(
        MCPToolDefinition(
            name="Bus",
            description="Search bus lines by keyword or line id with Amap.",
            parameters=[
                ToolParameter(name="keywords", type="string", description="Bus line keyword.", required=False, default=""),
                ToolParameter(name="city", type="string", description="City or citycode for keyword search.", required=False, default=""),
                ToolParameter(name="line_id", type="string", description="Bus line id for direct lookup.", required=False, default=""),
                ToolParameter(name="offset", type="integer", description="Maximum number of results.", required=False, default=10),
                ToolParameter(name="page", type="integer", description="Page number.", required=False, default=1),
                ToolParameter(name="extensions", type="string", description="base or all.", required=False, default="base"),
            ],
            handler=lambda arguments: bus(
                str(arguments.get("keywords", "")),
                str(arguments.get("city", "")),
                str(arguments.get("line_id", "")),
                int(arguments.get("offset", 10)),
                int(arguments.get("page", 1)),
                str(arguments.get("extensions", "base")),
            ),
        )
    )
    return server


def main(argv: Sequence[str] | None = None) -> None:
    args = list(argv or sys.argv[1:])
    kind = args[0] if args else "amap"
    if kind == "weather":
        build_weather_server().serve()
        return
    if kind == "amap":
        build_amap_server().serve()
        return
    raise SystemExit(f"Unknown MCP server kind: {kind}")
