from contextlib import contextmanager
from typing import Generator

from rich.console import Console
from rich.markdown import Markdown
from rich.theme import Theme
from rich.panel import Panel

# Custom theme for the CLI
_theme = Theme({
    "info": "dim cyan",
    "warning": "yellow",
    "danger": "bold red",
    "system": "bold green",
    "user": "bold blue",
})

console = Console(theme=_theme)


def print_markdown(content: str) -> None:
    """Print markdown content nicely formatted."""
    md = Markdown(content)
    console.print(md)


def print_system(message: str) -> None:
    """Print a system message."""
    console.print(f"[system]{message}[/system]")


def print_info(message: str) -> None:
    """Print an informational message."""
    console.print(f"[info]{message}[/info]")


def print_error(message: str) -> None:
    """Print an error message."""
    console.print(f"[danger]Error: {message}[/danger]")


def print_panel(content: str, title: str) -> None:
    """Print content wrapped in a panel."""
    console.print(Panel(content, title=title, border_style="blue"))


@contextmanager
def show_spinner(message: str = "Thinking...") -> Generator[None, None, None]:
    """Show a spinner while a block of code executes."""
    with console.status(f"[bold cyan]{message}", spinner="dots"):
        yield
