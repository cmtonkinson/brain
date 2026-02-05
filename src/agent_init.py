"""Agent initialization module for registering hooks and services."""

from __future__ import annotations

import logging
import os
from typing import Callable

from sqlalchemy.orm import Session

from commitments.ingestion_hook import create_commitment_extraction_hook
from commitments.signal_extraction import create_signal_commitment_extractor
from config import settings
from ingestion.hooks import HookFilters, register_hook
from llm import LLMClient
from scheduler.adapter_interface import SchedulerAdapter
from scheduler.adapters import (
    CeleryAdapterConfig,
    CelerySchedulerAdapter,
    CelerySqlAlchemySchedulerClient,
)
from services.database import get_sync_engine
from services.object_store import ObjectStore

LOGGER = logging.getLogger(__name__)


def _create_scheduler_adapter() -> SchedulerAdapter:
    """Create a scheduler adapter instance for commitment scheduling.

    Returns:
        A configured SchedulerAdapter instance
    """
    # Use Celery + SQLAlchemy scheduler (same as used by celery beat)
    broker_url = os.environ.get("CELERY_BROKER_URL", "redis://redis:6379/1")
    beat_dburi = str(get_sync_engine().url)

    client = CelerySqlAlchemySchedulerClient(
        broker_url=broker_url,
        beat_dburi=beat_dburi,
    )

    config = CeleryAdapterConfig(
        callback_task_name="scheduler.execute_callback",
        evaluation_callback_task_name="scheduler.evaluate_predicate",
        queue_name=os.environ.get("CELERY_QUEUE_NAME", "scheduler"),
    )

    return CelerySchedulerAdapter(client=client, config=config)


def _initialize_commitment_hooks(
    session_factory: Callable[[], Session],
    object_store: ObjectStore,
    schedule_adapter: SchedulerAdapter | None = None,
    llm_client: LLMClient | None = None,
) -> None:
    """Register commitment-related hooks with the ingestion pipeline.

    Args:
        session_factory: Factory for creating database sessions
        object_store: Object store for reading artifact content
        schedule_adapter: Optional scheduler adapter (created if not provided)
        llm_client: Optional LLM client for commitment extraction
    """
    LOGGER.info("Initializing commitment hooks...")

    # Create scheduler adapter if not provided
    if schedule_adapter is None:
        LOGGER.info("Creating scheduler adapter for commitment hooks...")
        schedule_adapter = _create_scheduler_adapter()

    # Create commitment extraction hook
    commitment_hook = create_commitment_extraction_hook(
        session_factory=session_factory,
        schedule_adapter=schedule_adapter,
        object_store=object_store,
        llm_client=llm_client,
    )

    # Register hook for 'normalize' stage with text content filters
    hook_id = register_hook(
        stage="normalize",
        callback=commitment_hook,
        filters=HookFilters(
            mime_types=frozenset([
                "text/plain",
                "text/markdown",
            ]),
        ),
    )

    LOGGER.info(
        "Registered commitment extraction hook (id=%s) for ingestion stage 'normalize'",
        hook_id,
    )


def initialize_agent_hooks(
    session_factory: Callable[[], Session],
    object_store: ObjectStore,
    schedule_adapter: SchedulerAdapter | None = None,
    llm_client: LLMClient | None = None,
) -> dict[str, object]:
    """Initialize all agent hooks and services.

    This is the main entrypoint called during agent startup to register
    all necessary hooks with the ingestion pipeline and other subsystems.

    Args:
        session_factory: Factory for creating database sessions
        object_store: Object store for blob storage
        schedule_adapter: Optional scheduler adapter (created if not provided)
        llm_client: Optional LLM client for extraction and analysis

    Returns:
        Dictionary of initialized services/extractors for use by the agent
    """
    LOGGER.info("Initializing agent hooks and services...")

    # Create scheduler adapter if not provided
    if schedule_adapter is None:
        LOGGER.info("Creating scheduler adapter for agent services...")
        schedule_adapter = _create_scheduler_adapter()

    # Initialize commitment tracking hooks for ingestion
    _initialize_commitment_hooks(
        session_factory=session_factory,
        object_store=object_store,
        schedule_adapter=schedule_adapter,
        llm_client=llm_client,
    )

    # Create Signal message commitment extractor
    signal_commitment_extractor = create_signal_commitment_extractor(
        session_factory=session_factory,
        schedule_adapter=schedule_adapter,
        llm_client=llm_client,
    )
    LOGGER.info("Created Signal message commitment extractor")

    # Future: Add other hook initializations here
    # - Skill output commitment extraction
    # - Weekly review scheduling
    # - Daily batch scheduling

    LOGGER.info("Agent hooks and services initialized successfully")

    return {
        "signal_commitment_extractor": signal_commitment_extractor,
    }


__all__ = [
    "initialize_agent_hooks",
]
