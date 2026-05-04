"""Per-executor command-shaping registry for the Coding Adapter.

Each supported executor gets a small :class:`ExecutorCommandShaper` that
knows how to turn an :class:`~resources.adapters.coding.adapter.CodingTaskSpec`
prompt into a CLI argv inside the runtime container. The shaping is
intentionally minimal: the Coding Adapter does not interpret the prompt,
it just hands it to the executor's CLI in whichever idiomatic shape the
executor expects.

The registry can be re-keyed by the operator's
``adapter.coding.executors`` catalog (which sets the actual ``cli``
binary name) without requiring changes here — :func:`shape_command`
takes the configured CLI name as a parameter.
"""

from __future__ import annotations

from typing import Final, Protocol

from resources.adapters.coding.adapter import ExecutorId


class _ExecutorCommandShaper(Protocol):
    """Callable that maps ``(cli, prompt)`` to a CLI argv tuple."""

    def __call__(self, *, cli: str, prompt: str) -> tuple[str, ...]: ...


def _claude_code_argv(*, cli: str, prompt: str) -> tuple[str, ...]:
    """Claude Code CLI: ``claude -p <prompt>`` for non-interactive print mode.

    Without ``-p`` the CLI sits at an interactive REPL and the wallclock
    watchdog has to kill it. ``-p`` (a.k.a. ``--print``) makes it run the
    prompt once and exit.
    """
    return (cli, "-p", prompt)


def _codex_argv(*, cli: str, prompt: str) -> tuple[str, ...]:
    """Codex CLI: ``codex exec <prompt>`` per OpenAI's coding-agent CLI."""
    return (cli, "exec", prompt)


def _opencode_argv(*, cli: str, prompt: str) -> tuple[str, ...]:
    """OpenCode CLI: ``opencode run <prompt>``."""
    return (cli, "run", prompt)


_SHAPERS: Final[dict[ExecutorId, _ExecutorCommandShaper]] = {
    ExecutorId.CLAUDE_CODE: _claude_code_argv,
    ExecutorId.CODEX: _codex_argv,
    ExecutorId.OPENCODE: _opencode_argv,
}


class UnknownExecutorError(ValueError):
    """Raised when a command shaper is requested for an unknown executor."""


def shape_command(*, executor: ExecutorId, cli: str, prompt: str) -> tuple[str, ...]:
    """Return the argv to invoke the given executor's CLI for ``prompt``.

    Raises:
        UnknownExecutorError: if ``executor`` is not in the registry.
    """
    shaper = _SHAPERS.get(executor)
    if shaper is None:
        raise UnknownExecutorError(f"no command shaper registered for {executor!r}")
    return shaper(cli=cli, prompt=prompt)
