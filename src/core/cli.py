"""
`call-copilot <subcommand>` dispatch — called from src/tui/app.py's main()
before falling through to launching the TUI.
"""

from src.core import updater

_COMMANDS = {
    "update": (lambda: updater.run_update(), "instala la última versión"),
    "check-update": (lambda: updater.run_check_update(), "avisa si hay una versión nueva, sin instalarla"),
    "version": (lambda: updater.run_version(), "versión y commit instalado"),
    "uninstall": (lambda: updater.run_uninstall(), "desinstala (config/datos en ~/.call-copilot quedan)"),
    "doctor": (lambda: updater.run_doctor(), "diagnóstico: pipx, Python, extras, GPU"),
}

_HELP_ALIASES = ("help", "--help", "-h")


def run_help() -> int:
    print("call-copilot — copiloto de llamadas + transcriptor de video (TUI)")
    print()
    print("Uso: call-copilot [comando]")
    print()
    print("Sin argumentos, arranca la TUI. Comandos disponibles:")
    names = list(_COMMANDS) + ["help"]
    width = max(len(name) for name in names)
    for name, (_, desc) in _COMMANDS.items():
        print(f"  {name.ljust(width)}  {desc}")
    print(f"  {'help'.ljust(width)}  esta ayuda ('--help'/'-h' también andan)")
    return 0


def dispatch(argv: list[str]) -> int | None:
    """Returns an exit code when argv[0] matches a known subcommand or a
    help alias, or None to fall through to launching the TUI (bare
    invocation, or an unrecognized first argument)."""
    if not argv:
        return None
    command = argv[0]
    if command in _HELP_ALIASES:
        return run_help()
    entry = _COMMANDS.get(command)
    if entry is None:
        return None
    handler, _ = entry
    return handler()
