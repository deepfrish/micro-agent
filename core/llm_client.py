from __future__ import annotations

import json
import os
from pathlib import Path
import urllib.error
import urllib.request
from typing import Dict, List


def _load_dotenv() -> None:
    env_path = Path(__file__).resolve().parents[1] / ".env"
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


class DeepSeekClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
    ) -> None:
        _load_dotenv()
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY", "")
        self.base_url = (base_url or os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")).rstrip("/")
        self.model = model or os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
        self.timeout = float(timeout if timeout is not None else os.getenv("DEEPSEEK_TIMEOUT", "120"))
        self.use_proxy = self._env_flag("DEEPSEEK_USE_PROXY", default=False)

    def chat(self, messages: List[Dict[str, str]], temperature: float = 0.2) -> str:
        if not self.api_key:
            raise RuntimeError("Missing DEEPSEEK_API_KEY. Put it in your .env file or environment.")

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )

        try:
            opener = self._build_opener()
            with opener.open(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"DeepSeek API error: {exc.code} {body}") from exc
        except TimeoutError as exc:
            raise RuntimeError(
                f"DeepSeek API timed out after {self.timeout}s. "
                f"Check network, base URL, model name, or increase DEEPSEEK_TIMEOUT."
            ) from exc
        except OSError as exc:
            raise RuntimeError(f"DeepSeek network error: {exc}") from exc

        return data["choices"][0]["message"]["content"]

    def _build_opener(self) -> urllib.request.OpenerDirector:
        if self.use_proxy:
            return urllib.request.build_opener()
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))

    @staticmethod
    def _env_flag(name: str, *, default: bool = False) -> bool:
        value = os.getenv(name)
        if value is None:
            return default
        return value.strip().lower() in {"1", "true", "yes", "on"}
