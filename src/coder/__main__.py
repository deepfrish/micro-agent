from __future__ import annotations

import sys
import click

from .cli.app import main as chat_main
from .cli.memory_worker import main as memory_worker_main
from src.core.protocols.mcp.server import main as mcp_server_main


@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx):
    """micro-agent CLI - A conversational agent skeleton."""
    if ctx.invoked_subcommand is None:
        # Default action: start chat
        chat_main()


@cli.command()
def memory():
    """(Deprecated) Sync long-term memory."""
    click.echo("The personal memory sync command was removed. Long-term memory is updated automatically on /exit.")


@cli.command(name="memory-worker", context_settings=dict(ignore_unknown_options=True))
@click.argument('args', nargs=-1, type=click.UNPROCESSED)
def memory_worker(args):
    """Run the memory worker."""
    memory_worker_main(list(args))


@cli.command(name="mcp-server", context_settings=dict(ignore_unknown_options=True))
@click.argument('args', nargs=-1, type=click.UNPROCESSED)
def mcp_server(args):
    """Run the MCP server."""
    mcp_server_main(list(args))


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
