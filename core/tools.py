from __future__ import annotations

import ast
import json
import math
import operator as op
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _strip_surrogates(text: str) -> str:
    return "".join(ch for ch in text if not 0xD800 <= ord(ch) <= 0xDFFF)


def _load_dotenv() -> None:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


ParameterInput = Mapping[str, Any] | str | None


@dataclass(frozen=True, slots=True)
class ToolParameter:
    name: str
    type: str
    description: str
    required: bool = True
    default: Any = None


class Tool(ABC):
    """Base abstraction shared by all tools."""

    def __init__(self, name: str, description: str, source_label: str = "local tool") -> None:
        self.name = name
        self.description = description
        self._source_label = source_label

    @abstractmethod
    def run(self, parameters: ParameterInput) -> str:
        """Execute the tool and return a text observation."""
        raise NotImplementedError

    @abstractmethod
    def get_parameters(self) -> Sequence[ToolParameter]:
        """Return the parameter schema used for prompts and function calling."""
        raise NotImplementedError

    def source_label(self) -> str:
        return self._source_label

    def normalize_parameters(self, parameters: ParameterInput) -> Dict[str, Any]:
        if isinstance(parameters, Mapping):
            normalized: Dict[str, Any] = dict(parameters)
        elif parameters is None:
            normalized = {}
        else:
            normalized = self._parse_text_input(str(parameters).strip())

        for parameter in self.get_parameters():
            missing = parameter.name not in normalized or normalized[parameter.name] in (None, "")
            if missing:
                if parameter.default is not None:
                    normalized[parameter.name] = parameter.default
                elif parameter.required:
                    raise ValueError(f"Missing required parameter: {parameter.name}")
                else:
                    continue

            normalized[parameter.name] = self._coerce_value(normalized[parameter.name], parameter)

        return normalized

    def to_openai_schema(self) -> Dict[str, Any]:
        properties: Dict[str, Dict[str, Any]] = {}
        required: List[str] = []

        for parameter in self.get_parameters():
            property_schema: Dict[str, Any] = {
                "type": parameter.type,
                "description": parameter.description,
            }
            if parameter.default is not None:
                property_schema["description"] = (
                    f"{parameter.description} (default: {parameter.default})"
                )
            if parameter.type == "array":
                property_schema["items"] = {"type": "string"}

            properties[parameter.name] = property_schema
            if parameter.required:
                required.append(parameter.name)

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }

    def _parse_text_input(self, text: str) -> Dict[str, Any]:
        if text.startswith("{"):
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                data = None
            if isinstance(data, dict):
                return data

        parameters = list(self.get_parameters())
        if not parameters:
            return {}

        target = next((parameter for parameter in parameters if parameter.required), parameters[0])
        return {target.name: text}

    def _coerce_value(self, value: Any, parameter: ToolParameter) -> Any:
        if parameter.type == "string":
            return str(value)
        if parameter.type == "integer":
            return int(value)
        if parameter.type == "number":
            return float(value)
        if parameter.type == "boolean":
            if isinstance(value, bool):
                return value
            return str(value).strip().lower() in {"1", "true", "yes", "y"}
        return value


class FunctionTool(Tool):
    """Adapter that lets a plain string function act like a Tool object."""

    def __init__(
        self,
        name: str,
        description: str,
        func: Callable[[str], str],
        parameter_name: str = "input",
        parameter_description: str = "Tool input.",
        source_label: str = "local tool",
    ) -> None:
        super().__init__(name=name, description=description, source_label=source_label)
        self.func = func
        self._parameters = [
            ToolParameter(
                name=parameter_name,
                type="string",
                description=parameter_description,
            )
        ]

    def run(self, parameters: ParameterInput) -> str:
        normalized = self.normalize_parameters(parameters)
        parameter = self._parameters[0]
        return self.func(normalized[parameter.name])

    def get_parameters(self) -> Sequence[ToolParameter]:
        return self._parameters


class ToolRegistry:
    """Registry for tool registration, discovery, schema export, and execution."""

    def __init__(self) -> None:
        self._tools: Dict[str, Tool] = {}

    def register_tool(self, tool: Tool) -> None:
        self._tools[self._key(tool.name)] = tool

    def register_tools(self, tools: Sequence[Tool]) -> None:
        for tool in tools:
            self.register_tool(tool)

    def register_provider(self, provider: Any) -> int:
        tools = list(provider.load_tools() or [])
        if tools:
            self.register_tools(tools)
        return len(tools)

    def register_function(
        self,
        name: str,
        description: str,
        func: Callable[[str], str],
        parameter_name: str = "input",
        parameter_description: str = "Tool input.",
    ) -> None:
        self.register_tool(
            FunctionTool(
                name=name,
                description=description,
                func=func,
                parameter_name=parameter_name,
                parameter_description=parameter_description,
            )
        )

    def find_tool(self, name: str) -> Tool:
        key = self._key(name)
        if key not in self._tools:
            raise KeyError(f"Unknown tool: {name}")
        return self._tools[key]

    def execute_tool(self, name: str, parameters: ParameterInput) -> str:
        tool = self.find_tool(name)
        return tool.run(parameters)

    def register_default_external_tools(self) -> bool:
        try:
            from .providers import AmapCapabilityProvider, FreeWebProvider

            tool_count = 0
            tool_count += self.register_provider(AmapCapabilityProvider())
            tool_count += self.register_provider(FreeWebProvider())
        except Exception:
            tool_count = 0
        if not tool_count:
            return False
        return True

    def register_default_mcp_tools(self) -> bool:
        return self.register_default_external_tools()

    def get_tools_description(self, include_source: bool = False) -> str:
        if not self._tools:
            return "No tools available."

        descriptions = []
        for tool in self._tools.values():
            parameters = ", ".join(self._format_parameter(parameter) for parameter in tool.get_parameters())
            suffix = f" Parameters: {parameters}" if parameters else " Parameters: none"
            source = f" [{tool.source_label()}]" if include_source else ""
            descriptions.append(f"- {tool.name}{source}: {tool.description}{suffix}")
        return "\n".join(descriptions)

    def to_openai_schema(self) -> List[Dict[str, Any]]:
        return [tool.to_openai_schema() for tool in self._tools.values()]

    def list_tools(self) -> List[Tool]:
        return list(self._tools.values())

    @staticmethod
    def _key(name: str) -> str:
        return name.strip().lower()

    @staticmethod
    def _format_parameter(parameter: ToolParameter) -> str:
        required = "required" if parameter.required else "optional"
        default = "" if parameter.default is None else f", default={parameter.default}"
        return f"{parameter.name} ({parameter.type}, {required}{default}) - {parameter.description}"


_ALLOWED_OPERATORS = {
    ast.Add: op.add,
    ast.Sub: op.sub,
    ast.Mult: op.mul,
    ast.Div: op.truediv,
    ast.Pow: op.pow,
    ast.Mod: op.mod,
    ast.FloorDiv: op.floordiv,
    ast.USub: op.neg,
    ast.UAdd: op.pos,
}

_ALLOWED_FUNCTIONS = {
    "sqrt": math.sqrt,
    "abs": abs,
    "round": round,
}

_ALLOWED_CONSTANTS = {
    "pi": math.pi,
    "e": math.e,
}


def _safe_eval(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return float(node.value)
    if isinstance(node, ast.Name) and node.id in _ALLOWED_CONSTANTS:
        return float(_ALLOWED_CONSTANTS[node.id])
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_OPERATORS:
        return _ALLOWED_OPERATORS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_OPERATORS:
        return _ALLOWED_OPERATORS[type(node.op)](_safe_eval(node.operand))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        func = _ALLOWED_FUNCTIONS.get(node.func.id)
        if func is None or node.keywords:
            raise ValueError("Unsupported function call.")
        return float(func(*[_safe_eval(argument) for argument in node.args]))
    raise ValueError("Only basic arithmetic, sqrt, abs, round, pi, and e are supported.")


def calculator(expression: str) -> str:
    try:
        tree = ast.parse(expression, mode="eval")
        value = _safe_eval(tree.body)
        if value.is_integer():
            return str(int(value))
        return str(value)
    except Exception as exc:
        return f"Calculator error: {exc}"


def current_time(_: str = "") -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")



AMAP_DEFAULT_URLS = {
    "GAODE_WEATHER_URL": "https://restapi.amap.com/v3/weather/weatherInfo",
    "GAODE_GEOCODE_URL": "https://restapi.amap.com/v3/geocode/geo",
    "GAODE_REGEOCODE_URL": "https://restapi.amap.com/v3/geocode/regeo",
    "GAODE_INPUTTIPS_URL": "https://restapi.amap.com/v3/assistant/inputtips",
    "GAODE_DISTRICT_URL": "https://restapi.amap.com/v3/config/district",
    "GAODE_STATIC_MAP_URL": "https://restapi.amap.com/v3/staticmap",
    "GAODE_AROUND_URL": "https://restapi.amap.com/v5/place/around",
    "GAODE_WALKING_URL": "https://restapi.amap.com/v3/direction/walking",
    "GAODE_DRIVING_URL": "https://restapi.amap.com/v3/direction/driving",
    "GAODE_TRANSIT_URL": "https://restapi.amap.com/v3/direction/transit/integrated",
    "GAODE_BUS_LINENAME_URL": "https://restapi.amap.com/v3/bus/linename",
    "GAODE_BUS_LINEID_URL": "https://restapi.amap.com/v3/bus/lineid",
}


def _load_amap_key() -> str:
    _load_dotenv()
    for key_name in ("GAODE_API_KEY", "AMAP_API_KEY", "AMAP_KEY"):
        value = os.getenv(key_name, "").strip()
        if value:
            return value
    return ""


def _amap_url(env_name: str) -> str:
    default = AMAP_DEFAULT_URLS.get(env_name, "")
    value = os.getenv(env_name, default).strip()
    return value or default


def _fetch_json(url: str, params: Dict[str, Any] | None = None) -> dict:
    url = _strip_surrogates(str(url))
    if params:
        safe_params = {
            str(key): _strip_surrogates(str(value))
            for key, value in params.items()
            if value not in (None, "")
        }
        query = urlencode(safe_params)
        url = f"{url}?{query}"
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _normalize_location_query(location: str) -> str:
    cleaned = _strip_surrogates(" ".join(location.split())).strip()
    cleaned = cleaned.strip(" \t\r\n,.;:!?()[]{}<>")
    return cleaned or location.strip()


def _parse_lon_lat(text: str) -> tuple[float, float] | None:
    match = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*", text)
    if not match:
        return None
    lon = float(match.group(1))
    lat = float(match.group(2))
    if -180 <= lon <= 180 and -90 <= lat <= 90:
        return lon, lat
    return None


def _first_dict(items: Any) -> Dict[str, Any]:
    if isinstance(items, list) and items and isinstance(items[0], dict):
        return items[0]
    if isinstance(items, dict):
        return items
    return {}


def _is_v5_place_url(url: str) -> bool:
    return "/v5/" in url.lower()


def _normalize_pois(raw_pois: Any) -> List[Dict[str, Any]]:
    if isinstance(raw_pois, list):
        return [poi for poi in raw_pois if isinstance(poi, dict)]
    if isinstance(raw_pois, dict):
        poi = raw_pois.get("poi")
        if isinstance(poi, list):
            return [item for item in poi if isinstance(item, dict)]
        if isinstance(poi, dict):
            return [poi]
    return []


def _extract_nearby_query(text: str) -> Dict[str, str]:
    query = _normalize_location_query(text)
    if not query:
        return {"location": text, "keywords": ""}

    pattern = re.compile(
        r"(?P<location>.+?)(?:附近|周边|周围|旁边|附件|周遭|周边地区)"
        r"(?:有(?:什么|哪些)?|找|搜索|查询|的)?(?P<keywords>.+)?$"
    )
    match = pattern.search(query)
    if not match:
        return {"location": query, "keywords": ""}

    location = (match.group("location") or query).strip(" ，,。?？")
    keywords = (match.group("keywords") or "").strip(" ，,。?？")
    return {"location": location or query, "keywords": keywords}


def _pick_location_value(parameters: Mapping[str, Any], raw_text: str = "") -> str:
    for key in ("location", "city", "address", "place", "query", "text", "name"):
        value = parameters.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    if len(parameters) == 1:
        only_value = next(iter(parameters.values()))
        if isinstance(only_value, str) and only_value.strip():
            return only_value.strip()

    raw_text = raw_text.strip()
    if raw_text:
        return raw_text
    return ""


def _resolve_location(location: str, api_key: str) -> Dict[str, str]:
    query = _normalize_location_query(location)
    if not query:
        raise ValueError("Weather error: empty location.")

    coordinate = _parse_lon_lat(query)
    if coordinate is not None:
        lon, lat = coordinate
        coord_text = f"{lon:.6f},{lat:.6f}"
        reverse_data = _fetch_json(
            _amap_url("GAODE_REGEOCODE_URL"),
            {
                "key": api_key,
                "location": coord_text,
                "extensions": "base",
                "output": "JSON",
            },
        )
        regeocode = reverse_data.get("regeocode") if isinstance(reverse_data, dict) else {}
        address_component = regeocode.get("addressComponent") if isinstance(regeocode, dict) else {}
        adcode = str(address_component.get("adcode") or "").strip()
        name = str(regeocode.get("formatted_address") or query).strip() if isinstance(regeocode, dict) else query
        return {"name": name or coord_text, "adcode": adcode, "location": coord_text}

    district_data = _fetch_json(
        _amap_url("GAODE_DISTRICT_URL"),
        {
            "key": api_key,
            "keywords": query,
            "subdistrict": 0,
            "extensions": "base",
            "output": "JSON",
        },
    )
    if district_data.get("status") == "1":
        district = _first_dict(district_data.get("districts") or [])
        adcode = str(district.get("adcode") or "").strip()
        center = str(district.get("center") or "").strip()
        name = str(district.get("name") or query).strip()
        if adcode and center:
            return {"name": name, "adcode": adcode, "location": center}

    geocode_data = _fetch_json(
        _amap_url("GAODE_GEOCODE_URL"),
        {
            "key": api_key,
            "address": query,
            "output": "JSON",
        },
    )
    if geocode_data.get("status") == "1":
        geocode = _first_dict(geocode_data.get("geocodes") or [])
        adcode = str(geocode.get("adcode") or "").strip()
        center = str(geocode.get("location") or "").strip()
        name = str(geocode.get("formatted_address") or query).strip()
        if adcode and center:
            return {"name": name, "adcode": adcode, "location": center}

    raise ValueError(f"Weather error: could not resolve location for '{location}'.")


def _fetch_amap_weather(adcode: str, api_key: str, extensions: str) -> dict:
    return _fetch_json(
        _amap_url("GAODE_WEATHER_URL"),
        {
            "key": api_key,
            "city": adcode,
            "extensions": extensions,
            "output": "JSON",
        },
    )


def _format_weather_live(live: Dict[str, Any]) -> str:
    return (
        f"Current: {live.get('weather', '?')}, "
        f"{live.get('temperature', '?')}C, "
        f"humidity {live.get('humidity', '?')}%, "
        f"wind {live.get('winddirection', '?')} {live.get('windpower', '?')}?, "
        f"report time {live.get('reporttime', '?')}"
    )


def _format_weather_cast(cast: Dict[str, Any], label: str) -> str:
    return (
        f"{label}: date {cast.get('date', '?')} ({cast.get('week', '?')}), "
        f"day {cast.get('dayweather', '?')} {cast.get('daytemp', '?')}C, "
        f"night {cast.get('nightweather', '?')} {cast.get('nighttemp', '?')}C, "
        f"day wind {cast.get('daywind', '?')} {cast.get('daypower', '?')}?, "
        f"night wind {cast.get('nightwind', '?')} {cast.get('nightpower', '?')}?"
    )


def weather(location: str) -> str:
    location = location.strip()
    if not location:
        return "Weather error: empty location."

    api_key = _load_amap_key()
    if not api_key:
        return "Weather error: missing GAODE_API_KEY."

    try:
        resolved = _resolve_location(location, api_key)
        live_data = _fetch_amap_weather(resolved["adcode"], api_key, "base")
        forecast_data = _fetch_amap_weather(resolved["adcode"], api_key, "all")
    except HTTPError as exc:
        return f"Weather error: HTTP {exc.code}"
    except URLError as exc:
        return f"Weather error: {exc.reason}"
    except TimeoutError:
        return "Weather error: request timed out."
    except Exception as exc:
        return f"Weather error: {exc}"

    live = {}
    if live_data.get("status") == "1":
        lives = live_data.get("lives") or []
        if lives and isinstance(lives[0], dict):
            live = lives[0]

    casts: List[Dict[str, Any]] = []
    reporttime = ""
    if forecast_data.get("status") == "1":
        forecast = forecast_data.get("forecast") or {}
        if isinstance(forecast, dict):
            raw_casts = forecast.get("casts") or []
            if isinstance(raw_casts, list):
                casts = [cast for cast in raw_casts if isinstance(cast, dict)]
            reporttime = str(forecast.get("reporttime") or "").strip()

    lines = [f"Location: {resolved['name']} ({resolved['adcode']})"]
    if live:
        lines.append(_format_weather_live(live))
    else:
        lines.append("Current: unavailable.")

    if casts:
        labels = ["Today forecast", "Tomorrow forecast", "Day after tomorrow forecast"]
        for label, cast in zip(labels, casts[:3]):
            lines.append(_format_weather_cast(cast, label))
        if reporttime:
            lines.append(f"Forecast report time: {reporttime}")
    else:
        lines.append("Forecast: unavailable.")

    return "\n".join(lines)


def build_static_map_url(location: str, zoom: int = 13, size: str = "600*400", scale: int = 1) -> str:
    api_key = _load_amap_key()
    if not api_key:
        raise ValueError("Static map error: missing GAODE_API_KEY.")

    resolved = _resolve_location(location, api_key)
    params = {
        "key": api_key,
        "location": resolved["location"],
        "zoom": max(1, min(int(zoom), 17)),
        "size": size,
        "scale": max(1, min(int(scale), 2)),
        "markers": f"mid,,A:{resolved['location']}",
    }
    query = urlencode({key: value for key, value in params.items() if value not in (None, "")})
    return f"{_amap_url('GAODE_STATIC_MAP_URL')}?{query}"


def nearby_search(
    location: str,
    keywords: str = "",
    types: str = "",
    radius: int = 1000,
    page: int = 1,
    offset: int = 10,
) -> str:
    api_key = _load_amap_key()
    if not api_key:
        raise ValueError("Nearby search error: missing GAODE_API_KEY.")

    if not keywords.strip() and not types.strip():
        parsed = _extract_nearby_query(location)
        location = parsed["location"]
        keywords = parsed["keywords"]

    resolved = _resolve_location(location, api_key)
    around_url = _amap_url("GAODE_AROUND_URL")
    payload: Dict[str, Any] = {
        "key": api_key,
        "location": resolved["location"],
        "keywords": keywords.strip(),
        "types": types.strip(),
        "radius": max(1, min(int(radius), 50000)),
        "output": "JSON",
    }
    if _is_v5_place_url(around_url):
        payload.update(
            {
                "page_num": max(1, int(page)),
                "page_size": max(1, min(int(offset), 25)),
                "show_fields": "business",
            }
        )
    else:
        payload.update(
            {
                "page": max(1, int(page)),
                "offset": max(1, min(int(offset), 25)),
                "extensions": "base",
            }
        )

    data = _fetch_json(around_url, payload)
    if data.get("status") != "1":
        return f"Nearby search error: {data.get('info', 'unknown error')}"

    pois = _normalize_pois(data.get("pois"))
    if not pois:
        return f"No nearby POIs found around {resolved['name']}."

    lines = [
        f"Center: {resolved['name']} ({resolved['location']})",
        f"Total results: {data.get('count', len(pois))}",
    ]
    for index, poi in enumerate(pois[:offset], start=1):
        business = poi.get("business") if isinstance(poi.get("business"), dict) else {}
        business_area = business.get("business_area") or poi.get("businessarea") or "?"
        lines.append(
            f"{index}. {poi.get('name', '?')} | {poi.get('type', '?')} | "
            f"{poi.get('address', '?')} | business area {business_area} | "
            f"distance {poi.get('distance', '?')}m"
        )
    return "\n".join(lines)

class CalculatorTool(Tool):
    def __init__(self) -> None:
        super().__init__(
            name="Calculator",
            description="Evaluate arithmetic expressions. Supports +, -, *, /, //, %, **, sqrt, abs, round, pi, and e.",
        )

    def run(self, parameters: ParameterInput) -> str:
        normalized = self.normalize_parameters(parameters)
        return calculator(normalized["expression"])

    def get_parameters(self) -> Sequence[ToolParameter]:
        return [
            ToolParameter(
                name="expression",
                type="string",
                description="The arithmetic expression to evaluate, such as 12 * (3 + 4) or sqrt(16).",
            )
        ]


class NowTool(Tool):
    def __init__(self) -> None:
        super().__init__(
            name="Now",
            description="Get the current local date and time.",
        )

    def run(self, parameters: ParameterInput) -> str:
        self.normalize_parameters(parameters)
        return current_time()

    def get_parameters(self) -> Sequence[ToolParameter]:
        return []


class WeatherTool(Tool):
    def __init__(self, source_label: str = "local tool") -> None:
        super().__init__(
            name="Weather",
            description="Get current weather and a short forecast for a location using Amap weather API.",
            source_label=source_label,
        )

    def run(self, parameters: ParameterInput) -> str:
        normalized = self.normalize_parameters(parameters)
        location = _pick_location_value(normalized)
        return weather(location)

    def get_parameters(self) -> Sequence[ToolParameter]:
        return [
            ToolParameter(
                name="location",
                type="string",
                description="A city, district, address, or 'longitude,latitude' coordinate. Prefer the place name only, such as 广东省中山市.",
                required=False,
                default="",
            )
        ]


class StaticMapTool(Tool):
    def __init__(self, source_label: str = "local tool") -> None:
        super().__init__(
            name="StaticMap",
            description="Build an Amap static map image URL for a city, address, or coordinate.",
            source_label=source_label,
        )

    def run(self, parameters: ParameterInput) -> str:
        normalized = self.normalize_parameters(parameters)
        try:
            location = _pick_location_value(normalized)
            url = build_static_map_url(
                location,
                zoom=int(normalized["zoom"]),
                size=str(normalized["size"]),
                scale=int(normalized["scale"]),
            )
        except HTTPError as exc:
            return f"Static map error: HTTP {exc.code}"
        except URLError as exc:
            return f"Static map error: {exc.reason}"
        except TimeoutError:
            return "Static map error: request timed out."
        except Exception as exc:
            return f"Static map error: {exc}"
        return f"Static map URL: {url}"

    def get_parameters(self) -> Sequence[ToolParameter]:
        return [
            ToolParameter(
                name="location",
                type="string",
                description="A city, district, address, or 'longitude,latitude' coordinate.",
                required=False,
                default="",
            ),
            ToolParameter(
                name="zoom",
                type="integer",
                description="Map zoom level from 1 to 17.",
                required=False,
                default=13,
            ),
            ToolParameter(
                name="size",
                type="string",
                description="Image size as width*height. Maximum is 1024*1024.",
                required=False,
                default="600*400",
            ),
            ToolParameter(
                name="scale",
                type="integer",
                description="Image scale, 1 for normal or 2 for high resolution.",
                required=False,
                default=1,
            ),
        ]


class NearbySearchTool(Tool):
    def __init__(self, source_label: str = "local tool") -> None:
        super().__init__(
            name="NearbySearch",
            description="Search nearby POIs around a city, address, or coordinate using Amap around search API.",
            source_label=source_label,
        )

    def run(self, parameters: ParameterInput) -> str:
        normalized = self.normalize_parameters(parameters)
        try:
            location = _pick_location_value(normalized)
            return nearby_search(
                location=location,
                keywords=str(normalized.get("keywords", "")),
                types=str(normalized.get("types", "")),
                radius=int(normalized["radius"]),
                page=int(normalized["page"]),
                offset=int(normalized["offset"]),
            )
        except HTTPError as exc:
            return f"Nearby search error: HTTP {exc.code}"
        except URLError as exc:
            return f"Nearby search error: {exc.reason}"
        except TimeoutError:
            return "Nearby search error: request timed out."
        except Exception as exc:
            return f"Nearby search error: {exc}"

    def get_parameters(self) -> Sequence[ToolParameter]:
        return [
            ToolParameter(
                name="location",
                type="string",
                description="A city, district, address, or 'longitude,latitude' coordinate used as the search center.",
                required=False,
                default="",
            ),
            ToolParameter(
                name="keywords",
                type="string",
                description="POI keyword, such as coffee, hospital, parking, or restaurant.",
                required=False,
                default="",
            ),
            ToolParameter(
                name="types",
                type="string",
                description="Amap POI type code filter. Leave empty when unsure.",
                required=False,
                default="",
            ),
            ToolParameter(
                name="radius",
                type="integer",
                description="Search radius in meters.",
                required=False,
                default=1000,
            ),
            ToolParameter(
                name="page",
                type="integer",
                description="Result page number.",
                required=False,
                default=1,
            ),
            ToolParameter(
                name="offset",
                type="integer",
                description="Maximum number of results to return, up to 25.",
                required=False,
                default=10,
            ),
        ]


def create_default_registry(memory_namespace: str = "default", include_external: bool = True) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register_tool(CalculatorTool())
    registry.register_tool(NowTool())
    if include_external:
        registry.register_default_external_tools()
    return registry


DEFAULT_REGISTRY = create_default_registry(include_external=False)
TOOLS: List[Tool] = DEFAULT_REGISTRY.list_tools()


def tool_list_text() -> str:
    return DEFAULT_REGISTRY.get_tools_description()


def find_tool(name: str) -> Tool:
    return DEFAULT_REGISTRY.find_tool(name)


def execute_tool(name: str, parameters: ParameterInput) -> str:
    return DEFAULT_REGISTRY.execute_tool(name, parameters)


def tool_schemas() -> List[Dict[str, Any]]:
    return DEFAULT_REGISTRY.to_openai_schema()
