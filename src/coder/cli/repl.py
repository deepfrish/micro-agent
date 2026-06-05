import os
from pathlib import Path
from typing import List, Callable, Optional

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter, Completer, Completion
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.styles import Style

from .commands import get_registered_commands

# Styling for the prompt
_style = Style.from_dict({
    "prompt": "ansicyan bold",
    "namespace": "ansigreen bold",
})

# Default command list to show when typing '/'
_builtin_commands = [
    "/new",
    "/net",
    "/rag",
    "/compress",
    "/tools",
    "/del",
    "/exit",
]

class CommandCompleter(Completer):
    """Completer for CLI slash commands."""
    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if text.startswith("/"):
            word = text.split(" ")[0]
            # Use dynamically registered commands if available
            cmds = get_registered_commands() if get_registered_commands() else _builtin_commands
            for cmd in cmds:
                if cmd.startswith(word):
                    yield Completion(cmd, start_position=-len(word))


class REPLSession:
    def __init__(self, history_file: str = ".micro_agent_history"):
        history_path = Path.home() / history_file
        self.session = PromptSession(
            history=FileHistory(str(history_path)),
            auto_suggest=AutoSuggestFromHistory(),
            completer=CommandCompleter(),
            style=_style,
        )

    def prompt(self, namespace: Optional[str]) -> str:
        """Prompt the user for input with the current namespace."""
        if namespace:
            prompt_fragments = [
                ("class:prompt", "["),
                ("class:namespace", namespace),
                ("class:prompt", "]> "),
            ]
        else:
            prompt_fragments = [("class:prompt", "> ")]

        try:
            return self.session.prompt(prompt_fragments).strip()
        except KeyboardInterrupt:
            # Handle Ctrl+C (cancel current input)
            return ""
        except EOFError:
            # Handle Ctrl+D (exit)
            return "/exit"
