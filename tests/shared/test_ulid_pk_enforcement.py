"""System-level static invariants for service-owned Postgres migrations.

These checks are intentionally registry-driven and source-based so they scale to
newly added services (including third-party packages) without manual updates.
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from packages.brain_shared.component_loader import import_registered_component_modules
from packages.brain_shared.manifest import ServiceManifest, get_registry


@dataclass(frozen=True)
class _Violation:
    """One migration invariant violation suitable for assertion output."""

    file_path: Path
    line: int
    message: str

    def format(self) -> str:
        """Render violation text with stable file and line context."""
        return f"{self.file_path}:{self.line}: {self.message}"


def test_service_migrations_use_ulid_bin_primary_keys_and_local_foreign_keys() -> None:
    """Enforce PK/FK ownership invariants for every registered service migration."""
    services = _registered_services()

    violations: list[_Violation] = []
    for service in services:
        for migration_file in _migration_files_for_service(service):
            violations.extend(
                _analyze_migration_file(migration_file=migration_file, service=service)
            )

    assert not violations, "\n".join(v.format() for v in violations)


def _registered_services() -> tuple[ServiceManifest, ...]:
    """Import component manifests and return validated service manifests."""
    import_registered_component_modules()
    registry = get_registry()
    registry.assert_valid()
    return registry.list_services()


def _migration_files_for_service(service: ServiceManifest) -> tuple[Path, ...]:
    """Return migration version files discovered from service module roots."""
    repo_root = Path.cwd().resolve()
    files: set[Path] = set()

    for module_root in service.module_roots:
        module_path = repo_root.joinpath(*str(module_root).split("."))
        versions_dir = module_path / "migrations" / "versions"
        if not versions_dir.exists():
            continue
        files.update(versions_dir.glob("*.py"))

    return tuple(sorted(files))


def _analyze_migration_file(
    *, migration_file: Path, service: ServiceManifest
) -> list[_Violation]:
    """Analyze one migration file for service schema PK/FK invariants."""
    source = migration_file.read_text(encoding="utf-8")
    module = ast.parse(source, filename=str(migration_file))
    ulid_helpers = _ulid_helper_functions(module)

    violations: list[_Violation] = []
    for node in ast.walk(module):
        if not isinstance(node, ast.Call):
            continue
        if _is_call(node, ("op", "create_table")):
            violations.extend(
                _analyze_create_table_call(
                    call=node,
                    file_path=migration_file,
                    service=service,
                    ulid_helpers=ulid_helpers,
                )
            )
            continue
        if _is_call(node, ("op", "create_foreign_key")):
            violations.extend(
                _analyze_create_foreign_key_call(
                    call=node,
                    file_path=migration_file,
                    service=service,
                )
            )

    return violations


def _analyze_create_table_call(
    *,
    call: ast.Call,
    file_path: Path,
    service: ServiceManifest,
    ulid_helpers: set[str],
) -> list[_Violation]:
    """Validate PK and FK constraints in one ``op.create_table`` call."""
    violations: list[_Violation] = []

    schema_expr = _keyword_value(call, "schema")
    if schema_expr is None:
        violations.append(
            _Violation(
                file_path=file_path,
                line=call.lineno,
                message="create_table must set explicit schema= for ownership checks",
            )
        )

    schema_tokens = _allowed_schema_tokens(schema_expr=schema_expr, service=service)

    column_types: dict[str, ast.AST] = {}
    pk_columns: set[str] = set()

    for arg in call.args[1:]:
        if isinstance(arg, ast.Call) and _is_any_call(arg, {("sa", "Column"), (None, "Column")}):
            column_name = _string_positional_arg(arg, 0)
            type_expr = arg.args[1] if len(arg.args) > 1 else None
            if column_name is None or type_expr is None:
                continue

            column_types[column_name] = type_expr
            if _keyword_is_true(arg, "primary_key"):
                pk_columns.add(column_name)

            for fk_target in _column_foreign_key_targets(arg):
                violations.extend(
                    _validate_fk_target(
                        fk_target_expr=fk_target,
                        schema_tokens=schema_tokens,
                        service=service,
                        file_path=file_path,
                        line=arg.lineno,
                    )
                )
            continue

        if isinstance(arg, ast.Call) and _is_any_call(
            arg, {("sa", "PrimaryKeyConstraint"), (None, "PrimaryKeyConstraint")}
        ):
            for idx, value in enumerate(arg.args):
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    pk_columns.add(value.value)
                else:
                    violations.append(
                        _Violation(
                            file_path=file_path,
                            line=arg.lineno,
                            message=(
                                "PrimaryKeyConstraint columns must be literal strings; "
                                f"non-literal argument at index {idx}"
                            ),
                        )
                    )
            continue

        if isinstance(arg, ast.Call) and _is_any_call(
            arg, {("sa", "ForeignKeyConstraint"), (None, "ForeignKeyConstraint")}
        ):
            targets = _foreign_key_constraint_targets(arg)
            if len(targets) == 0:
                violations.append(
                    _Violation(
                        file_path=file_path,
                        line=arg.lineno,
                        message="ForeignKeyConstraint must declare at least one remote target",
                    )
                )
            for fk_target in targets:
                violations.extend(
                    _validate_fk_target(
                        fk_target_expr=fk_target,
                        schema_tokens=schema_tokens,
                        service=service,
                        file_path=file_path,
                        line=arg.lineno,
                    )
                )

    for column_name in sorted(pk_columns):
        type_expr = column_types.get(column_name)
        if type_expr is None:
            violations.append(
                _Violation(
                    file_path=file_path,
                    line=call.lineno,
                    message=(
                        "PK column declared without matching Column definition: "
                        f"'{column_name}'"
                    ),
                )
            )
            continue

        if not _expr_is_ulid_bin_type(type_expr=type_expr, ulid_helpers=ulid_helpers):
            violations.append(
                _Violation(
                    file_path=file_path,
                    line=type_expr.lineno,
                    message=(
                        "Primary key column must use schema-local ulid_bin type; "
                        f"column '{column_name}' is non-compliant"
                    ),
                )
            )

    return violations


def _analyze_create_foreign_key_call(
    *, call: ast.Call, file_path: Path, service: ServiceManifest
) -> list[_Violation]:
    """Validate ``op.create_foreign_key`` schema ownership constraints."""
    source_schema = _keyword_value(call, "source_schema")
    referent_schema = _keyword_value(call, "referent_schema")

    if source_schema is None or referent_schema is None:
        return [
            _Violation(
                file_path=file_path,
                line=call.lineno,
                message=(
                    "create_foreign_key must set source_schema= and referent_schema= "
                    "for deterministic cross-schema validation"
                ),
            )
        ]

    source_tokens = _allowed_schema_tokens(schema_expr=source_schema, service=service)
    referent_token = _schema_token_from_schema_expr(referent_schema)

    if referent_token is None:
        return [
            _Violation(
                file_path=file_path,
                line=call.lineno,
                message="create_foreign_key referent_schema must be statically resolvable",
            )
        ]

    if referent_token not in source_tokens:
        return [
            _Violation(
                file_path=file_path,
                line=call.lineno,
                message=(
                    "Cross-schema FK is prohibited; referent schema "
                    f"'{referent_token}' != service schema '{service.schema_name}'"
                ),
            )
        ]

    return []


def _validate_fk_target(
    *,
    fk_target_expr: ast.AST,
    schema_tokens: set[str],
    service: ServiceManifest,
    file_path: Path,
    line: int,
) -> list[_Violation]:
    """Validate one FK target string belongs to the owning service schema."""
    schema_token = _schema_token_from_fk_target_expr(fk_target_expr)
    if schema_token is None:
        return [
            _Violation(
                file_path=file_path,
                line=line,
                message=(
                    "FK target must be schema-qualified (schema.table.column) and "
                    "statically resolvable"
                ),
            )
        ]

    if schema_token not in schema_tokens:
        return [
            _Violation(
                file_path=file_path,
                line=line,
                message=(
                    "Cross-schema FK is prohibited; target schema "
                    f"'{schema_token}' != service schema '{service.schema_name}'"
                ),
            )
        ]

    return []


def _allowed_schema_tokens(*, schema_expr: ast.AST | None, service: ServiceManifest) -> set[str]:
    """Return accepted schema tokens for one table within the owning service."""
    tokens = {service.schema_name}
    token = _schema_token_from_schema_expr(schema_expr) if schema_expr is not None else None
    if token is not None:
        tokens.add(token)
    return tokens


def _schema_token_from_schema_expr(schema_expr: ast.AST) -> str | None:
    """Return normalized schema token from a schema expression."""
    if isinstance(schema_expr, ast.Constant) and isinstance(schema_expr.value, str):
        return schema_expr.value
    if isinstance(schema_expr, ast.Name):
        return f"{{{schema_expr.id}}}"
    rendered = _render_string_expr(schema_expr)
    if rendered is None:
        return None
    return rendered


def _schema_token_from_fk_target_expr(fk_target_expr: ast.AST) -> str | None:
    """Extract schema token from a FK target expression."""
    rendered = _render_string_expr(fk_target_expr)
    if rendered is None:
        return None
    parts = rendered.split(".")
    if len(parts) < 3:
        return None
    return parts[0]


def _render_string_expr(expr: ast.AST) -> str | None:
    """Render a deterministic string template for literal/f-string expressions."""
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return expr.value
    if isinstance(expr, ast.JoinedStr):
        rendered_parts: list[str] = []
        for part in expr.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                rendered_parts.append(part.value)
                continue
            if isinstance(part, ast.FormattedValue) and isinstance(part.value, ast.Name):
                rendered_parts.append(f"{{{part.value.id}}}")
                continue
            return None
        return "".join(rendered_parts)
    return None


def _ulid_helper_functions(module: ast.Module) -> set[str]:
    """Return local helper function names that clearly resolve to ``ulid_bin``."""
    ulid_helpers: set[str] = set()
    functions = [node for node in module.body if isinstance(node, ast.FunctionDef)]

    changed = True
    while changed:
        changed = False
        for function in functions:
            if function.name in ulid_helpers:
                continue
            if _function_defines_ulid_bin(function=function, known_helpers=ulid_helpers):
                ulid_helpers.add(function.name)
                changed = True

    return ulid_helpers


def _function_defines_ulid_bin(*, function: ast.FunctionDef, known_helpers: set[str]) -> bool:
    """Return whether a local helper function is provably ``ulid_bin``-producing."""
    for node in ast.walk(function):
        if isinstance(node, ast.Constant) and node.value == "ulid_bin":
            return True
        if isinstance(node, ast.Call):
            callee_name = _call_name(node)
            if callee_name is not None and callee_name in known_helpers:
                return True
    return False


def _expr_is_ulid_bin_type(*, type_expr: ast.AST, ulid_helpers: set[str]) -> bool:
    """Return True when a PK type expression resolves to schema-local ``ulid_bin``."""
    for node in ast.walk(type_expr):
        if isinstance(node, ast.Constant) and node.value == "ulid_bin":
            return True

    if isinstance(type_expr, ast.Call):
        callee_name = _call_name(type_expr)
        if callee_name in ulid_helpers:
            return True
        if callee_name is not None:
            normalized = callee_name.lower().replace(".", "_")
            if "ulid" in normalized and (
                "domain" in normalized or "primary_key" in normalized or normalized.endswith("_pk")
            ):
                return True

    return False


def _column_foreign_key_targets(column_call: ast.Call) -> tuple[ast.AST, ...]:
    """Return FK target expressions from ``sa.Column(..., sa.ForeignKey(...))``."""
    targets: list[ast.AST] = []
    for argument in column_call.args:
        if isinstance(argument, ast.Call) and _is_any_call(
            argument, {("sa", "ForeignKey"), (None, "ForeignKey")}
        ):
            if len(argument.args) > 0:
                targets.append(argument.args[0])
    return tuple(targets)


def _foreign_key_constraint_targets(fk_call: ast.Call) -> tuple[ast.AST, ...]:
    """Return FK target expressions from ``sa.ForeignKeyConstraint`` calls."""
    if len(fk_call.args) < 2:
        return ()
    targets_expr = fk_call.args[1]
    if isinstance(targets_expr, (ast.List, ast.Tuple)):
        return tuple(targets_expr.elts)
    return ()


def _is_call(call: ast.Call, expected: tuple[str, str]) -> bool:
    """Return True when call target matches an expected ``module.name`` pair."""
    module, name = expected
    func = call.func
    return (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id == module
        and func.attr == name
    )


def _is_any_call(call: ast.Call, expected: set[tuple[str | None, str]]) -> bool:
    """Return True when call target matches any expected name pattern."""
    for module, name in expected:
        if module is None:
            if isinstance(call.func, ast.Name) and call.func.id == name:
                return True
            continue
        if _is_call(call, (module, name)):
            return True
    return False


def _call_name(call: ast.Call) -> str | None:
    """Return normalized dotted callee name for ``ast.Call`` nodes."""
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return f"{func.value.id}.{func.attr}"
    return None


def _keyword_value(call: ast.Call, keyword_name: str) -> ast.AST | None:
    """Return one keyword value from a call expression when present."""
    for keyword in call.keywords:
        if keyword.arg == keyword_name:
            return keyword.value
    return None


def _keyword_is_true(call: ast.Call, keyword_name: str) -> bool:
    """Return True when a call keyword is the literal boolean ``True``."""
    value = _keyword_value(call, keyword_name)
    return isinstance(value, ast.Constant) and value.value is True


def _string_positional_arg(call: ast.Call, index: int) -> str | None:
    """Return one positional string argument from a call expression."""
    if len(call.args) <= index:
        return None
    value = call.args[index]
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return value.value
    return None
