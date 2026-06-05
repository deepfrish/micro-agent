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
from .repl import REPLSession
from .display import print_markdown, print_system, print_error, print_info, print_panel, show_spinner


def run() -> None:
    manager = ConversationManager()
    repl = REPLSession()

    print_system("micro-agent CLI ready.")
    help_text = (
        "可用命令：\n"
        "  /new               - 开始新的聊天\n"
        "  /net [on|once|off] - 控制网页模式\n"
        "  /rag <strategy>    - 切换RAG检索策略\n"
        "  /compress          - 压缩当前聊天窗口历史\n"
        "  /history           - 显示当前聊天的历史记录\n"
        "  /tools             - 显示当前可用工具列表\n"
        "  /del <namespace>   - 删除指定的聊天历史\n"
        "  /exit              - 保存会话并退出\n"
        "  /exit -n           - 保存并离开当前会话\n"
        "  /<namespace>       - 切换到指定的聊天会话"
    )
    print_panel(help_text, title="Help")

    known = manager.known_namespaces()
    if known:
        print_info("Known namespaces: " + ", ".join(known))
    else:
        print_info("Known namespaces: none yet.")

    while True:
        active = manager.active_namespace
        question = repl.prompt(active)
        
        if not question:
            continue
            
        if question.lower() in {"exit", "quit", "q"}:
            _save_active_window_memory(manager)
            print_system("Bye.")
            break

        if question.startswith("/"):
            command = parse_chat_command(question)
            if command.kind == "noop":
                continue
            if command.kind == "new":
                manager.start_new_conversation()
                print_info("Ready for a new chat. Ask the first question and I will name the namespace automatically.")
                continue
            if command.kind == "exit":
                if command.argument and command.argument != "-n":
                    print_error("Unknown /exit option. Use /exit to quit or /exit -n to leave the current chat window.")
                    continue
                _save_active_window_memory(manager)
                if command.argument == "-n":
                    print_info("Left the current chat window.")
                    known = manager.known_namespaces()
                    print_info("Known namespaces: " + ", ".join(known) if known else "Known namespaces: none yet.")
                    continue
                print_system("Bye.")
                break
            if command.kind == "delete":
                target = command.argument or active
                if not target:
                    print_error("No active chat to delete.")
                    continue
                try:
                    session = manager.delete_session(target)
                except Exception as exc:
                    print_error(f"Cannot delete: {exc}")
                    continue
                print_info(f"Deleted chat [{session.namespace}]. Long-term memory was kept.")
                continue
            if command.kind == "compress":
                if manager.active_session() is None:
                    print_error("No active chat window to compress.")
                    continue
                with show_spinner("Compressing memory..."):
                    result = manager.compress_current_window()
                if not result.get("ok"):
                    print_error(f"Compression failed: {result.get('error', 'unknown error')}")
                    continue
                if result.get("skipped"):
                    print_info(f"Compression skipped: {result.get('reason', 'window not ready')}")
                    continue
                scores = result.get("scores") or {}
                print_info(
                    f"Compressed: {result.get('original_message_count', 0)} -> {result.get('compressed_message_count', 0)} messages, "
                    f"recall={result.get('recall_rate', 0):.3f}"
                )
                continue
            if command.kind == "history":
                session = manager.active_session()
                if session is None:
                    print_error("No active chat window.")
                    continue
                if not session.history:
                    print_info("No history in this chat.")
                    continue
                for msg in session.history:
                    role = str(msg.get("role", "unknown"))
                    content = str(msg.get("content") or "").strip()
                    if not content and role == "assistant" and msg.get("tool_calls"):
                        calls = [f"{c.get('function', {}).get('name')}" for c in msg["tool_calls"]]
                        content = f"[Tool Calls: {', '.join(calls)}]"
                    if not content and role == "tool":
                        content = "[Tool output hidden for brevity]"
                    if not content:
                        continue
                    print_panel(content, title=role.capitalize())
                continue
            if command.kind == "tools":
                session = manager.active_session()
                if session is None:
                    print_error("No active chat window.")
                    continue
                agent = session.ensure_agent(manager.config, manager.client, manager.memory_store)
                print_markdown(agent.tool_registry.get_tools_description(include_source=True))
                continue
            if command.kind == "rag":
                session = manager.active_session()
                if session is None:
                    print_error("No active chat window. Start or switch a chat first.")
                    continue
                strategy = command.argument.strip().lower()
                if strategy not in ("base", "mqe", "hyde"):
                    print_error("Unknown rag strategy. Use /rag=base, /rag=mqe, or /rag=hyde.")
                    continue
                manager.set_rag_strategy(strategy)
                print_info(f"RAG strategy set to '{strategy}' for [{session.namespace}].")
                continue
            if command.kind == "net":
                session = manager.active_session()
                if session is None:
                    print_error("No active chat window. Start or switch a chat first.")
                    continue
                argument = (command.argument or "on").strip().lower()
                if argument in {"", "on", "enable", "enabled"}:
                    mode = manager.set_network_mode("on")
                    print_info(f"Network mode for [{session.namespace}]: {mode}. Future turns will prefer ReAct + freeweb.")
                    continue
                if argument in {"once", "1"}:
                    mode = manager.set_network_mode("once")
                    print_info(f"Network mode for [{session.namespace}]: {mode}. The next turn will prefer ReAct + freeweb.")
                    continue
                if argument in {"off", "disable", "disabled"}:
                    mode = manager.set_network_mode("off")
                    print_info(f"Network mode for [{session.namespace}]: {mode}.")
                    continue
                if argument in {"status", "state"}:
                    print_info(f"Network mode for [{session.namespace}]: {manager.get_network_mode()}.")
                    continue
                print_error("Unknown /net option.")
                continue

            try:
                session = manager.switch(command.argument)
            except Exception as exc:
                print_error(f"Cannot switch: {exc}")
                continue

            print_info(f"Switched to [{session.namespace}].")
            if session.history:
                print_panel("History restored.", title=session.namespace)
            continue

        try:
            with show_spinner("Agent is thinking..."):
                session, answer, created_new = manager.ask(question)
        except Exception as exc:
            print_error(f"{exc}")
            continue

        if created_new:
            print_info(f"Created new chat [{session.namespace}] from the first question.")
        
        print_markdown(answer)
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
        print_error(f"Failed to queue memory consolidation: {exc}")
        return

    print_info(f"Queued window memory consolidation in background: {job_path.name}")


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
