"""
`call-copilot <subcommand>` dispatch — called from src/tui/app.py's main()
before falling through to launching the TUI.
"""

from src.core import updater

_COMMANDS = {
    "update": lambda: updater.run_update(),
    "check-update": lambda: updater.run_check_update(),
    "version": lambda: updater.run_version(),
    "uninstall": lambda: updater.run_uninstall(),
    "doctor": lambda: updater.run_doctor(),
}


def dispatch(argv: list[str]) -> int | None:
    """Returns an exit code when argv[0] matches a known subcommand, or
    None to fall through to launching the TUI (bare invocation, or an
    unrecognized first argument)."""
    if not argv:
        return None
    handler = _COMMANDS.get(argv[0])
    if handler is None:
        return None
    return handler()
