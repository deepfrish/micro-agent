from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.product.conversation import ConversationManager

from .commands import parse_chat_command


def run() -> None:
    manager = ConversationManager()
    print("micro-agent CLI ready.")
    print(
        "Commands: /new start a new chat, /net enable web mode, /net once web mode for next turn, /net off disable it, /compress compress the current chat window, /tools show current tool sources, /del <namespace> delete chat history, /exit quit, /exit -n leave the current chat, /<namespace> switch chats."
    )
    known = manager.known_namespaces()
    if known:
        print("Known namespaces: " + ", ".join(known))
    else:
        print("Known namespaces: none yet.")

    while True:
        active = manager.active_namespace
        prompt = f"[{active}]> " if active else "> "
        question = input(prompt).strip()
        if not question:
            continue
        if question.lower() in {"exit", "quit", "q"}:
            _save_active_window_memory(manager)
            print("Bye.")
            break

        if question.startswith("/"):
            command = parse_chat_command(question)
            if command.kind == "noop":
                continue
            if command.kind == "new":
                manager.start_new_conversation()
                print("Ready for a new chat. Ask the first question and I will name the namespace automatically.")
                continue
            if command.kind == "exit":
                if command.argument and command.argument != "-n":
                    print("Unknown /exit option. Use /exit to quit or /exit -n to leave the current chat window.")
                    continue
                _save_active_window_memory(manager)
                if command.argument == "-n":
                    print("Left the current chat window.")
                    known = manager.known_namespaces()
                    print("Known namespaces: " + ", ".join(known) if known else "Known namespaces: none yet.")
                    continue
                print("Bye.")
                break
            if command.kind == "delete":
                target = command.argument or active
                if not target:
                    print("No active chat to delete.")
                    continue
                try:
                    session = manager.delete_session(target)
                except Exception as exc:
                    print(f"Cannot delete: {exc}")
                    continue
                print(f"Deleted chat [{session.namespace}]. Long-term memory was kept.")
                continue
            if command.kind == "compress":
                if manager.active_session() is None:
                    print("No active chat window to compress.")
                    continue
                result = manager.compress_current_window()
                if not result.get("ok"):
                    print(f"Compression failed: {result.get('error', 'unknown error')}")
                    continue
                if result.get("skipped"):
                    print(
                        "Compression skipped: "
                        f"{result.get('reason', 'window not ready')}"
                    )
                    continue
                scores = result.get("scores") or {}
                print(
                    "Compressed current window: "
                    f"{result.get('original_message_count', 0)} -> {result.get('compressed_message_count', 0)} messages, "
                    f"recall={result.get('recall_rate', 0):.3f}, "
                    f"scores="
                    f"C{scores.get('coverage', 0)}/F{scores.get('fidelity', 0)}/"
                    f"Co{scores.get('conciseness', 0)}/Ct{scores.get('continuity', 0)}, "
                    f"log={result.get('log_path', 'examples/compress_log.jsonl')}"
                )
                continue
            if command.kind == "tools":
                session = manager.active_session()
                if session is None:
                    print("No active chat window.")
                    continue
                agent = session.ensure_agent(manager.config, manager.client, manager.memory_store)
                print(agent.tool_registry.get_tools_description(include_source=True))
                continue
            if command.kind == "rag":
                session = manager.active_session()
                if session is None:
                    print("No active chat window. Start or switch a chat first.")
                    continue
                strategy = command.argument.strip().lower()
                if strategy not in ("base", "mqe", "hyde"):
                    print("Unknown rag strategy. Use /rag=base, /rag=mqe, or /rag=hyde.")
                    continue
                manager.set_rag_strategy(strategy)
                print(f"RAG strategy set to '{strategy}' for [{session.namespace}].")
                continue
            if command.kind == "net":
                session = manager.active_session()
                if session is None:
                    print("No active chat window. Start or switch a chat first.")
                    continue
                argument = (command.argument or "on").strip().lower()
                if argument in {"", "on", "enable", "enabled"}:
                    mode = manager.set_network_mode("on")
                    print(f"Network mode for [{session.namespace}]: {mode}. Future turns will prefer ReAct + freeweb.")
                    continue
                if argument in {"once", "1"}:
                    mode = manager.set_network_mode("once")
                    print(f"Network mode for [{session.namespace}]: {mode}. The next turn will prefer ReAct + freeweb.")
                    continue
                if argument in {"off", "disable", "disabled"}:
                    mode = manager.set_network_mode("off")
                    print(f"Network mode for [{session.namespace}]: {mode}.")
                    continue
                if argument in {"status", "state"}:
                    print(f"Network mode for [{session.namespace}]: {manager.get_network_mode()}.")
                    continue
                print("Unknown /net option. Use /net, /net once, /net off, or /net status.")
                continue

            try:
                session = manager.switch(command.argument)
            except Exception as exc:
                print(f"Cannot switch: {exc}")
                continue

            print(f"Switched to [{session.namespace}].")
            continue

        try:
            session, answer, created_new = manager.ask(question)
        except Exception as exc:
            print(f"Error: {exc}")
            continue

        if created_new:
            print(f"Created new chat [{session.namespace}] from the first question.")
        print(f"\n[{session.namespace}] Final answer:")
        print(answer)
        print()


def main() -> None:
    run()


def _save_active_window_memory(manager: ConversationManager) -> None:
    result = manager.exit_current_conversation(background=True)
    job = result.get("job")
    if not job:
        return

    job_path = _write_memory_job(job)
    try:
        _spawn_memory_worker(job_path)
    except Exception as exc:
        print(f"Failed to queue memory consolidation: {exc}")
        return

    print(f"Queued window memory consolidation in background: {job_path.name}")


def _write_memory_job(job: dict) -> Path:
    job_dir = ROOT / "data" / "memory_jobs"
    job_dir.mkdir(parents=True, exist_ok=True)
    job_name = f"{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid4().hex}.json"
    job_path = job_dir / job_name
    job_path.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    return job_path


def _spawn_memory_worker(job_path: Path) -> None:
    command = [sys.executable, "-m", "src.coder", "memory-worker", str(job_path)]
    kwargs = {
        "cwd": str(ROOT),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(command, **kwargs)


if __name__ == "__main__":
    main()
