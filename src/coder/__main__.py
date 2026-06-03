from __future__ import annotations

import sys

from .cli.app import main as chat_main
from .cli.memory_worker import main as memory_worker_main
from src.core.protocols.mcp.server import main as mcp_server_main


def main() -> None:
    argv = sys.argv[1:]
    if argv and argv[0] == "memory":
        print("The personal memory sync command was removed. Long-term memory is updated automatically on /exit.")
        return
    if argv and argv[0] == "memory-worker":
        memory_worker_main(argv[1:])
        return
    if argv and argv[0] == "mcp-server":
        mcp_server_main(argv[1:])
        return
    chat_main()


if __name__ == "__main__":
    main()
