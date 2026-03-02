"""Static checks for standardized service HTTP registration hooks."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class _Violation:
    """One static contract violation with stable source context."""

    file_path: Path
    line: int
    message: str

    def format(self) -> str:
        """Render one violation line for assertion output."""
        return f"{self.file_path}:{self.line}: {self.message}"


def test_service_api_modules_define_standard_register_routes_hook() -> None:
    """Each service API module must expose ``register_routes(*, router, service)``."""
    violations: list[_Violation] = []
    for api_file in sorted(Path("services").glob("*/*/api.py")):
        module = ast.parse(api_file.read_text(encoding="utf-8"), filename=str(api_file))
        functions = [node for node in module.body if isinstance(node, ast.FunctionDef)]

        register = next((fn for fn in functions if fn.name == "register_routes"), None)
        if register is None:
            violations.append(
                _Violation(
                    file_path=api_file,
                    line=1,
                    message=(
                        "missing required register_routes(*, router, service) hook "
                        "in service api module"
                    ),
                )
            )
            continue

        positional_arg_names = tuple(arg.arg for arg in register.args.args)
        if positional_arg_names:
            violations.append(
                _Violation(
                    file_path=api_file,
                    line=register.lineno,
                    message=(
                        "register_routes must declare keyword-only parameters "
                        "(*, router, service)"
                    ),
                )
            )

        keyword_only_names = tuple(arg.arg for arg in register.args.kwonlyargs)
        if keyword_only_names != ("router", "service"):
            violations.append(
                _Violation(
                    file_path=api_file,
                    line=register.lineno,
                    message=(
                        "register_routes must declare keyword-only parameters exactly "
                        "(*, router, service)"
                    ),
                )
            )

    assert not violations, "\n".join(v.format() for v in violations)
