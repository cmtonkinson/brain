"""Negative-fixture tests for static analyzer regression protection.

These tests ensure each shared static analyzer detects representative violating
patterns, so analyzer behavior does not silently regress as implementation
changes over time.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from packages.brain_shared.manifest import ComponentId, ModuleRoot, ServiceManifest
from tests.shared import test_component_layer_dependencies as layer_sut
from tests.shared import test_no_dynamic_imports as dynamic_sut
from tests.shared import test_service_public_api_boundaries as public_api_sut
from tests.shared import test_service_resource_ownership_imports as ownership_sut
from tests.shared import test_ulid_pk_enforcement as migration_sut
from tests.shared.static_analysis_helpers import imports_for_source

_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "static_analysis"


def _fixture_text(name: str) -> str:
    """Read one fixture source file under shared static-analysis fixtures."""
    return (_FIXTURE_ROOT / name).read_text(encoding="utf-8")


def test_public_api_analyzer_detects_private_import_violation() -> None:
    """Public API analyzer must flag external imports into private service modules."""
    source = _fixture_text("public_api_private_import.py")
    known_modules = {
        "services.state.example.internal.repo",
        "services.state.example.internal",
    }
    imports = imports_for_source(
        source=source,
        caller_module="resources.substrates.anything.client",
        known_modules=known_modules,
    )

    service = public_api_sut._ServiceBoundary(
        service_id="service_example",
        schema_name="service_example",
        module_roots=("services.state.example",),
        public_api_roots=("services.state.example.api",),
    )

    violations = [
        ref
        for ref in imports
        if service.is_private_module(ref.module_name)
    ]

    assert violations


def test_layer_analyzer_detects_lower_to_higher_dependency() -> None:
    """Layer analyzer must flag lower-layer component imports to higher layer."""
    source = _fixture_text("layer_violation.py")
    known_modules = {
        "services.action.example.api",
        "services.action.example",
    }
    imports = imports_for_source(
        source=source,
        caller_module="resources.substrates.some_resource.client",
        known_modules=known_modules,
    )

    caller = layer_sut._ComponentBoundary(
        component_id="substrate_some_resource",
        layer=0,
        module_roots=("resources.substrates.some_resource",),
    )
    target = layer_sut._ComponentBoundary(
        component_id="service_action_example",
        layer=1,
        module_roots=("services.action.example",),
    )

    assert any(
        target.owns_module(ref.module_name) and target.layer > caller.layer for ref in imports
    )


def test_resource_ownership_analyzer_detects_owned_resource_violation() -> None:
    """Ownership analyzer must flag imports into resources owned by another service."""
    source = _fixture_text("resource_ownership_violation.py")
    known_modules = {
        "resources.substrates.secret_store.client",
        "resources.substrates.secret_store",
    }
    imports = imports_for_source(
        source=source,
        caller_module="services.state.alpha_service.impl",
        known_modules=known_modules,
    )

    caller_service = ownership_sut._ServiceBoundary(
        service_id="service_alpha",
        module_roots=("services.state.alpha_service",),
        owns_resources=frozenset(),
    )
    owned_resource = ownership_sut._ResourceBoundary(
        resource_id="substrate_secret_store",
        owner_service_id="service_beta",
        module_roots=("resources.substrates.secret_store",),
    )

    assert any(
        owned_resource.owns_module(ref.module_name)
        and owned_resource.resource_id not in caller_service.owns_resources
        for ref in imports
    )


def test_dynamic_import_analyzer_detects_banned_patterns() -> None:
    """Dynamic import analyzer must reject importlib and builtin import usage."""
    source = _fixture_text("dynamic_import_violation.py")
    violations = dynamic_sut._analyze_source_for_dynamic_imports(
        source=source,
        caller_module="services.state.example.runtime",
        file_path=Path("fixture_dynamic_import.py"),
    )

    assert violations


def test_migration_analyzer_detects_pk_and_fk_violations() -> None:
    """Migration analyzer must detect non-ulid PK and cross-schema FK targets."""
    source = _fixture_text("migration_violation.py")

    with tempfile.TemporaryDirectory() as temp_dir:
        migration_file = Path(temp_dir) / "bad_migration.py"
        migration_file.write_text(source, encoding="utf-8")

        service = ServiceManifest(
            id=ComponentId("service_example"),
            layer=1,
            system="state",
            module_roots=frozenset({ModuleRoot("services.state.example")}),
            public_api_roots=frozenset({ModuleRoot("services.state.example.api")}),
            owns_resources=frozenset(),
        )

        violations = migration_sut._analyze_migration_file(
            migration_file=migration_file,
            service=service,
        )

    assert violations
