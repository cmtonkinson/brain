"""Entrypoint for the Brain Console TUI."""

from __future__ import annotations

from actors.console.app import ConsoleApp


def main() -> None:
    """Run the console application."""
    ConsoleApp().run()


if __name__ == "__main__":
    main()
