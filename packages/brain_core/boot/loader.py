"""Discovery and contract loading for optional component ``boot.py`` modules."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys

from packages.brain_shared.component_loader import (
    import_component_modules,
    import_registered_component_modules,
)
from packages.brain_shared.manifest import list_components

from .contracts import BootHookContract, coerce_dependencies, require_zero_arg_callable


@dataclass(frozen=True, slots=True)
class BootModuleSpec:
    """One discovered boot module paired with its owning component id."""

    component_id: str
    module_name: str


def discover_boot_modules() -> tuple[BootModuleSpec, ...]:
    """Discover optional boot modules exposed by registered component roots."""
    import_registered_component_modules()

    discovered: list[BootModuleSpec] = []
    seen_modules: set[str] = set()
    repo_root = Path.cwd().resolve()
    for component in list_components():
        for module_root in sorted(component.module_roots):
            module_name = f"{module_root}.boot"
            if module_name in seen_modules:
                continue
            module_path = repo_root / Path(*module_name.split("."))
            if not module_path.with_suffix(".py").exists():
                continue
            seen_modules.add(module_name)
            discovered.append(
                BootModuleSpec(component_id=str(component.id), module_name=module_name)
            )
    return tuple(discovered)


def load_boot_hooks() -> tuple[BootHookContract, ...]:
    """Load and validate all discovered component boot hooks."""
    hooks: list[BootHookContract] = []
    for boot_module in discover_boot_modules():
        import_component_modules((boot_module.module_name,))
        module = sys.modules[boot_module.module_name]
        dependencies = coerce_dependencies(
            getattr(module, "dependencies", None),
            module_name=boot_module.module_name,
        )
        is_ready = require_zero_arg_callable(
            getattr(module, "is_ready", None),
            module_name=boot_module.module_name,
            attribute_name="is_ready",
        )
        boot = require_zero_arg_callable(
            getattr(module, "boot", None),
            module_name=boot_module.module_name,
            attribute_name="boot",
        )
        hooks.append(
            BootHookContract(
                component_id=boot_module.component_id,
                module_name=boot_module.module_name,
                dependencies=dependencies,
                is_ready=is_ready,
                boot=boot,
            )
        )
    return tuple(hooks)
