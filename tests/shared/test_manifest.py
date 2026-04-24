"""Unit tests for component manifest model, validation, and registry."""

from __future__ import annotations

import pytest

from lib.shared.manifest import (
    ActorManifest,
    ComponentId,
    ComponentManifest,
    ManifestError,
    ManifestRegistry,
    ModuleRoot,
    ResourceManifest,
    ServiceManifest,
    component_id_to_schema_name,
    validate_component_id,
    validate_module_root,
)


# ---------------------------------------------------------------------------
# Test factories — always build fresh instances, never touch global registry
# ---------------------------------------------------------------------------


def _resource(
    id: str = "substrate_test_res",
    system: str = "state",
    kind: str = "substrate",
    owner: str | None = None,
) -> ResourceManifest:
    """Build a minimal resource manifest for testing."""
    return ResourceManifest(
        id=ComponentId(id),
        layer=0,
        system=system,
        module_roots=frozenset({ModuleRoot("resources.test_res")}),
        kind=kind,
        owner_service_id=ComponentId(owner) if owner else None,
    )


def _service(
    id: str = "service_test_svc",
    system: str = "state",
    owns: tuple[str, ...] | None = None,
    exposes: bool = False,
    summary: str = "",
) -> ServiceManifest:
    """Build a minimal service manifest for testing."""
    return ServiceManifest(
        id=ComponentId(id),
        layer=1,
        system=system,
        module_roots=frozenset({ModuleRoot("services.test_svc")}),
        public_api_roots=frozenset({ModuleRoot("services.test_svc.api")}),
        owns_resources=(frozenset(ComponentId(r) for r in owns) if owns else None),
        exposes_capabilities=exposes,
        tool_system_summary=summary,
    )


def _actor(
    id: str = "actor_test",
    system: str = "control",
    principal: str = "operator",
) -> ActorManifest:
    """Build a minimal actor manifest for testing."""
    return ActorManifest(
        id=ComponentId(id),
        layer=2,
        system=system,
        module_roots=frozenset({ModuleRoot("actors.test_actor")}),
        principal=principal,
    )


# ---------------------------------------------------------------------------
# validate_component_id
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "id_value", ["ab", "my_service", "a1_2_3", "service_vault_authority"]
)
def test_validate_component_id_accepts_valid_ids(id_value: str) -> None:
    """Valid component ids should not raise."""
    validate_component_id(ComponentId(id_value))


@pytest.mark.parametrize(
    "id_value",
    [
        "",
        "A",
        "1abc",
        "a",
        "-abc",
        "a" * 64,
        "has-hyphen",
        "HAS_UPPER",
    ],
)
def test_validate_component_id_rejects_invalid_ids(id_value: str) -> None:
    """Invalid component ids should raise ManifestError."""
    with pytest.raises(ManifestError):
        validate_component_id(ComponentId(id_value))


# ---------------------------------------------------------------------------
# validate_module_root
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "root",
    ["services", "services.vault", "_private", "A_module.Sub"],
)
def test_validate_module_root_accepts_valid_roots(root: str) -> None:
    """Valid Python-style module roots should not raise."""
    validate_module_root(ModuleRoot(root))


@pytest.mark.parametrize(
    "root",
    ["", ".leading", "trailing.", "has..double", "123start"],
)
def test_validate_module_root_rejects_invalid_roots(root: str) -> None:
    """Invalid module roots should raise ManifestError."""
    with pytest.raises(ManifestError):
        validate_module_root(ModuleRoot(root))


# ---------------------------------------------------------------------------
# component_id_to_schema_name
# ---------------------------------------------------------------------------


def test_component_id_to_schema_name_returns_id_string() -> None:
    """Schema name should be the component id string verbatim."""
    assert component_id_to_schema_name(ComponentId("service_vault")) == "service_vault"


# ---------------------------------------------------------------------------
# ComponentManifest __post_init__ validation
# ---------------------------------------------------------------------------


def test_component_manifest_rejects_empty_module_roots() -> None:
    """ComponentManifest with empty module_roots should raise ManifestError."""
    with pytest.raises(ManifestError, match="module_roots must not be empty"):
        ComponentManifest(
            id=ComponentId("test_component"),
            layer=0,
            system="state",
            module_roots=frozenset(),
        )


def test_component_manifest_rejects_invalid_id() -> None:
    """ComponentManifest with invalid id should raise ManifestError."""
    with pytest.raises(ManifestError):
        ComponentManifest(
            id=ComponentId("1_invalid"),
            layer=0,
            system="state",
            module_roots=frozenset({ModuleRoot("test")}),
        )


# ---------------------------------------------------------------------------
# ResourceManifest
# ---------------------------------------------------------------------------


def test_resource_manifest_validates_owner_service_id() -> None:
    """ResourceManifest should reject an invalid owner_service_id."""
    with pytest.raises(ManifestError):
        ResourceManifest(
            id=ComponentId("substrate_test_res"),
            layer=0,
            system="state",
            module_roots=frozenset({ModuleRoot("resources.test")}),
            kind="substrate",
            owner_service_id=ComponentId("1_bad_id"),
        )


# ---------------------------------------------------------------------------
# ServiceManifest
# ---------------------------------------------------------------------------


def test_service_manifest_rejects_empty_public_api_roots() -> None:
    """ServiceManifest with empty public_api_roots should raise ManifestError."""
    with pytest.raises(ManifestError, match="public_api_roots must not be empty"):
        ServiceManifest(
            id=ComponentId("service_test"),
            layer=1,
            system="state",
            module_roots=frozenset({ModuleRoot("services.test")}),
            public_api_roots=frozenset(),
        )


def test_service_manifest_requires_summary_when_exposes_capabilities() -> None:
    """ServiceManifest must provide tool_system_summary when exposes_capabilities=True."""
    with pytest.raises(ManifestError, match="tool_system_summary"):
        ServiceManifest(
            id=ComponentId("service_test"),
            layer=1,
            system="state",
            module_roots=frozenset({ModuleRoot("services.test")}),
            public_api_roots=frozenset({ModuleRoot("services.test.api")}),
            exposes_capabilities=True,
            tool_system_summary="",
        )


def test_service_manifest_schema_name_derives_from_id() -> None:
    """ServiceManifest.schema_name should return the component id string."""
    svc = _service(id="service_vault_authority")
    assert svc.schema_name == "service_vault_authority"


# ---------------------------------------------------------------------------
# ActorManifest
# ---------------------------------------------------------------------------


def test_actor_manifest_rejects_empty_principal() -> None:
    """ActorManifest with empty principal should raise ManifestError."""
    with pytest.raises(ManifestError, match="principal must not be empty"):
        ActorManifest(
            id=ComponentId("actor_test"),
            layer=2,
            system="control",
            module_roots=frozenset({ModuleRoot("actors.test")}),
            principal="",
        )


# ---------------------------------------------------------------------------
# ManifestRegistry CRUD
# ---------------------------------------------------------------------------


def test_registry_register_and_get_component() -> None:
    """Registered components should be retrievable by id."""
    registry = ManifestRegistry()
    res = _resource()
    registry.register_component(res)
    assert registry.get_component(res.id) is res


def test_registry_rejects_duplicate_id_with_different_definition() -> None:
    """Re-registering the same id with a different manifest should raise."""
    registry = ManifestRegistry()
    registry.register_component(_resource(id="substrate_dup"))
    with pytest.raises(ManifestError, match="duplicate"):
        registry.register_component(_resource(id="substrate_dup", system="action"))


def test_registry_allows_identical_re_registration() -> None:
    """Re-registering the exact same manifest should not raise."""
    registry = ManifestRegistry()
    res = _resource()
    registry.register_component(res)
    registry.register_component(res)
    assert registry.get_component(res.id) is res


def test_registry_get_component_raises_for_unknown_id() -> None:
    """Getting an unregistered component should raise ManifestError."""
    registry = ManifestRegistry()
    with pytest.raises(ManifestError, match="not registered"):
        registry.get_component(ComponentId("substrate_unknown"))


# ---------------------------------------------------------------------------
# ManifestRegistry listing
# ---------------------------------------------------------------------------


def test_registry_list_resources_sorted_by_id() -> None:
    """list_resources should return resources sorted alphabetically by id."""
    registry = ManifestRegistry()
    registry.register_component(_resource(id="substrate_zzz"))
    registry.register_component(_resource(id="substrate_aaa"))
    registry.register_component(_resource(id="substrate_mmm"))

    ids = [str(r.id) for r in registry.list_resources()]
    assert ids == ["substrate_aaa", "substrate_mmm", "substrate_zzz"]


def test_registry_list_services_sorted_by_system_then_id() -> None:
    """list_services should sort by system order (state < action < control) then id."""
    registry = ManifestRegistry()
    registry.register_component(_service(id="service_ctrl_a", system="control"))
    registry.register_component(_service(id="service_state_b", system="state"))
    registry.register_component(_service(id="service_action_a", system="action"))
    registry.register_component(_service(id="service_state_a", system="state"))

    ids = [str(s.id) for s in registry.list_services()]
    assert ids == [
        "service_state_a",
        "service_state_b",
        "service_action_a",
        "service_ctrl_a",
    ]


def test_registry_list_actors_sorted_by_id() -> None:
    """list_actors should return actors sorted alphabetically by id."""
    registry = ManifestRegistry()
    registry.register_component(_actor(id="actor_zz"))
    registry.register_component(_actor(id="actor_aa"))

    ids = [str(a.id) for a in registry.list_actors()]
    assert ids == ["actor_aa", "actor_zz"]


def test_registry_list_components_returns_all_types() -> None:
    """list_components should return resources, services, and actors."""
    registry = ManifestRegistry()
    registry.register_component(_resource(id="substrate_rr"))
    registry.register_component(_service(id="service_ss"))
    registry.register_component(_actor(id="actor_aa"))

    components = registry.list_components()
    assert len(components) == 3
    ids = {str(c.id) for c in components}
    assert ids == {"substrate_rr", "service_ss", "actor_aa"}


# ---------------------------------------------------------------------------
# Ownership cross-validation
# ---------------------------------------------------------------------------


def test_registry_rejects_resource_with_multiple_owners() -> None:
    """Two services claiming the same resource should raise ManifestError."""
    registry = ManifestRegistry()
    registry.register_component(_resource(id="substrate_shared"))
    registry.register_component(
        _service(id="service_owner_a", owns=("substrate_shared",))
    )
    with pytest.raises(ManifestError, match="multiple owners"):
        registry.register_component(
            _service(id="service_owner_b", owns=("substrate_shared",))
        )


def test_registry_assert_valid_rejects_unknown_owner_reference() -> None:
    """A resource referencing an unregistered owner should fail assert_valid."""
    registry = ManifestRegistry()
    registry.register_component(_resource(id="substrate_orphan", owner="service_ghost"))
    with pytest.raises(ManifestError, match="unknown owner"):
        registry.assert_valid()


def test_registry_detects_owner_mismatch_at_registration() -> None:
    """Resource owner_service_id disagreeing with service owns_resources should raise eagerly."""
    registry = ManifestRegistry()
    registry.register_component(
        _resource(id="substrate_contested", owner="service_owner_b")
    )
    registry.register_component(
        _service(id="service_owner_a", owns=("substrate_contested",))
    )
    with pytest.raises(ManifestError, match="owner mismatch"):
        registry.register_component(_service(id="service_owner_b"))
