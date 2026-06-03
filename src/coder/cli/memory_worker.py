from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from src.core.llm_client import DeepSeekClient, MemoryLLMClient
from src.core.memory_pipeline import ExitMemoryConsolidator


def main(argv: list[str] | None = None) -> None:
    args = list(argv or sys.argv[1:])
    if not args:
        raise SystemExit("Usage: python -m coder memory-worker <job-path>")

    job_path = Path(args[0]).expanduser().resolve()
    if not job_path.exists():
        raise SystemExit(f"Memory job not found: {job_path}")

    job = _load_job(job_path)
    result = _process_job(job)
    _write_result(job_path, job, result)


def _load_job(path: Path) -> Dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SystemExit(f"Cannot read memory job: {exc}") from exc
    if not isinstance(raw, dict):
        raise SystemExit("Memory job must be a JSON object.")
    return raw


def _process_job(job: Dict[str, Any]) -> Dict[str, Any]:
    client = MemoryLLMClient()
    consolidator = ExitMemoryConsolidator(client)
    return consolidator.consolidate_job(job)


def _write_result(path: Path, job: Dict[str, Any], result: Dict[str, Any]) -> None:
    payload = {
        **job,
        "status": "done" if result.get("ok") else "failed",
        "result": result,
        "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    try:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


if __name__ == "__main__":
    main()
