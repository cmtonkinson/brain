"""Layer B: end-to-end upgrade application against real substrates.

Each test builds a tiny fixture upgrade directory at runtime, points
``BRAIN_UPGRADES_DIR`` and ``BRAIN_UPGRADES_LEDGER`` at ``tmp_path``, seeds
the ledger, runs ``apply_pending``, and asserts the substrate was mutated
as expected.

Gated on ``BRAIN_RUN_INTEGRATION_REAL=1``. Reuses the ephemeral-Docker
fixtures from ``tests.integration.fixtures``.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from lib.core.upgrades.ledger import (
    LEDGER_SCHEMA_VERSION,
    Ledger,
    now_utc_iso,
    read_ledger,
    write_ledger,
)
from lib.core.upgrades.runner import apply_pending
from tests.integration.helpers import real_provider_tests_enabled

pytest_plugins = ("tests.integration.fixtures",)

pytestmark = pytest.mark.skipif(
    not real_provider_tests_enabled(),
    reason="set BRAIN_RUN_INTEGRATION_REAL=1 to run real-provider integration tests",
)


def _seed_empty_ledger() -> None:
    write_ledger(
        Ledger(
            schema_version=LEDGER_SCHEMA_VERSION,
            installed_at=now_utc_iso(),
            applied=[],
        )
    )


def _isolated_upgrades(monkeypatch, tmp_path) -> Path:
    """Point env at tmp_path-backed upgrades + state."""
    upgrades_dir = tmp_path / "upgrades"
    state_dir = tmp_path / "state"
    upgrades_dir.mkdir()
    state_dir.mkdir()
    monkeypatch.setenv("BRAIN_UPGRADES_DIR", str(upgrades_dir))
    monkeypatch.setenv("BRAIN_STATE_DIR", str(state_dir))
    monkeypatch.delenv("BRAIN_UPGRADES_LEDGER", raising=False)
    return upgrades_dir


def _write_upgrade(
    upgrades_dir: Path, *, upgrade_id: str, slug: str, body: str
) -> None:
    directory = upgrades_dir / f"{upgrade_id}_{slug}"
    directory.mkdir()
    (directory / "upgrade.py").write_text(body)


def test_apply_against_real_postgres_upgrade_runs_and_records(
    monkeypatch, tmp_path, postgres_dsn
):
    upgrades_dir = _isolated_upgrades(monkeypatch, tmp_path)
    # Strip SQLAlchemy driver suffix; psycopg.connect wants the raw libpq URL.
    psycopg_dsn = postgres_dsn.replace("postgresql+psycopg://", "postgresql://")
    monkeypatch.setenv("BRAIN_TEST_POSTGRES_DSN", psycopg_dsn)
    _seed_empty_ledger()

    _write_upgrade(
        upgrades_dir,
        upgrade_id="20260505_0001",
        slug="postgres_marker",
        body=dedent(
            '''\
            """Create a marker table to prove the upgrade ran."""

            from __future__ import annotations

            import os

            from lib.core.upgrades.api import UpgradeContext

            DESCRIPTION = "Create upgrade_marker table"
            PHASE = "post-services"


            def run(ctx: UpgradeContext) -> None:
                import psycopg

                dsn = os.environ["BRAIN_TEST_POSTGRES_DSN"]
                with psycopg.connect(dsn, autocommit=True) as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "CREATE TABLE IF NOT EXISTS upgrade_marker "
                            "(id INT PRIMARY KEY, ts TIMESTAMPTZ DEFAULT now())"
                        )
                        cur.execute(
                            "INSERT INTO upgrade_marker (id) VALUES (1) "
                            "ON CONFLICT DO NOTHING"
                        )
            '''
        ),
    )

    rc = apply_pending(repo_root=tmp_path)

    assert rc == 1
    assert read_ledger().is_applied("20260505_0001")

    import psycopg

    with psycopg.connect(psycopg_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM upgrade_marker WHERE id = 1")
            row = cur.fetchone()
            assert row is not None and row[0] == 1


def test_apply_against_real_valkey_upgrade_clears_prefix(
    monkeypatch, tmp_path, valkey_url
):
    upgrades_dir = _isolated_upgrades(monkeypatch, tmp_path)
    monkeypatch.setenv("BRAIN_TEST_VALKEY_URL", valkey_url)
    _seed_empty_ledger()

    # Pre-populate keys we expect the upgrade to clear, plus one it must keep.
    import valkey

    client = valkey.Valkey.from_url(valkey_url)
    client.set("upgrade-test:keep:a", "x")
    client.set("upgrade-test:victim:1", "y")
    client.set("upgrade-test:victim:2", "z")

    _write_upgrade(
        upgrades_dir,
        upgrade_id="20260505_0001",
        slug="valkey_clear_prefix",
        body=dedent(
            '''\
            """Delete every key under upgrade-test:victim:."""

            from __future__ import annotations

            import os

            from lib.core.upgrades.api import UpgradeContext

            DESCRIPTION = "Drop upgrade-test:victim:* keys"
            PHASE = "post-services"


            def run(ctx: UpgradeContext) -> None:
                import valkey

                client = valkey.Valkey.from_url(os.environ["BRAIN_TEST_VALKEY_URL"])
                for key in client.scan_iter(match="upgrade-test:victim:*"):
                    client.delete(key)
            '''
        ),
    )

    rc = apply_pending(repo_root=tmp_path)

    assert rc == 1
    assert client.get("upgrade-test:keep:a") == b"x"
    assert client.get("upgrade-test:victim:1") is None
    assert client.get("upgrade-test:victim:2") is None

    # Cleanup
    client.delete("upgrade-test:keep:a")


def test_apply_against_real_qdrant_upgrade_recreates_collection(
    monkeypatch, tmp_path, qdrant_url
):
    upgrades_dir = _isolated_upgrades(monkeypatch, tmp_path)
    monkeypatch.setenv("BRAIN_TEST_QDRANT_URL", qdrant_url)
    _seed_empty_ledger()

    collection = "upgrade_test_collection"

    _write_upgrade(
        upgrades_dir,
        upgrade_id="20260505_0001",
        slug="qdrant_recreate",
        body=dedent(
            f'''\
            """Drop and recreate a Qdrant collection."""

            from __future__ import annotations

            import os

            from lib.core.upgrades.api import UpgradeContext

            DESCRIPTION = "Drop and recreate the upgrade_test_collection"
            PHASE = "post-services"


            def run(ctx: UpgradeContext) -> None:
                from qdrant_client import QdrantClient
                from qdrant_client.models import Distance, VectorParams

                client = QdrantClient(url=os.environ["BRAIN_TEST_QDRANT_URL"])
                if client.collection_exists("{collection}"):
                    client.delete_collection("{collection}")
                client.create_collection(
                    collection_name="{collection}",
                    vectors_config=VectorParams(size=4, distance=Distance.COSINE),
                )
            '''
        ),
    )

    rc = apply_pending(repo_root=tmp_path)

    assert rc == 1

    from qdrant_client import QdrantClient

    client = QdrantClient(url=qdrant_url)
    try:
        info = client.get_collection(collection)
        # Vector size 4 confirms the upgrade actually ran.
        params = info.config.params.vectors
        size = (
            params.size if hasattr(params, "size") else next(iter(params.values())).size
        )
        assert size == 4
    finally:
        client.delete_collection(collection)


def test_apply_against_real_seaweedfs_upgrade_writes_object(
    monkeypatch, tmp_path, seaweedfs_endpoint
):
    upgrades_dir = _isolated_upgrades(monkeypatch, tmp_path)
    monkeypatch.setenv("BRAIN_TEST_SEAWEEDFS_ENDPOINT", seaweedfs_endpoint)
    _seed_empty_ledger()

    bucket = "brain-int-test"
    key = "upgrade-marker.txt"

    _write_upgrade(
        upgrades_dir,
        upgrade_id="20260505_0001",
        slug="seaweedfs_marker",
        body=dedent(
            f'''\
            """Drop a marker object into the test bucket."""

            from __future__ import annotations

            import os

            from lib.core.upgrades.api import UpgradeContext

            DESCRIPTION = "Place upgrade-marker.txt in {bucket}"
            PHASE = "post-services"


            def run(ctx: UpgradeContext) -> None:
                import urllib.request

                endpoint = os.environ["BRAIN_TEST_SEAWEEDFS_ENDPOINT"]
                url = f"{{endpoint}}/{bucket}/{key}"
                req = urllib.request.Request(url, data=b"hello", method="PUT")
                with urllib.request.urlopen(req) as resp:
                    assert resp.status in (200, 201, 204), resp.status
            '''
        ),
    )

    rc = apply_pending(repo_root=tmp_path)

    assert rc == 1

    import urllib.request

    with urllib.request.urlopen(f"{seaweedfs_endpoint}/{bucket}/{key}") as resp:
        assert resp.read() == b"hello"
