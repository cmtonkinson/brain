"""Agent initialization module for registering hooks and services."""

from __future__ import annotations

import logging
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from commitments.daily_batch_scheduler import schedule_daily_batch_reminder
from commitments.ingestion_hook import create_commitment_extraction_hook
from commitments.loop_closure_handler import LoopClosureReplyHandler
from commitments.signal_extraction import create_signal_commitment_extractor
from commitments.weekly_review_scheduler import schedule_weekly_review
from config import settings
from models import Schedule, TaskIntent
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


def _schedule_exists(session: Session, origin_reference: str) -> bool:
    """Check if an active schedule with the given origin_reference already exists.

    Args:
        session: Database session
        origin_reference: Origin reference to check (e.g., "commitments.weekly_review")

    Returns:
        True if an active schedule exists, False otherwise
    """
    stmt = (
        select(Schedule)
        .join(TaskIntent, Schedule.task_intent_id == TaskIntent.id)
        .where(TaskIntent.origin_reference == origin_reference)
        .where(Schedule.state.in_(["active", "paused"]))
    )
    result = session.execute(stmt).first()
    return result is not None


def _create_scheduler_adapter() -> SchedulerAdapter:
    """Create a scheduler adapter instance for commitment scheduling.

    Returns:
        A configured SchedulerAdapter instance
    """
    # Import Celery here to create our own instance
    # (avoid importing scheduler.celery_app which has module-level init issues)
    from celery import Celery

    # Create a minimal Celery app instance for the scheduler client
    # This matches the configuration in scheduler.celery_app but avoids
    # triggering module-level object creation that requires async context
    celery_app = Celery("brain.scheduler")
    celery_app.conf.broker_url = settings.scheduler.celery_broker_url
    celery_app.conf.result_backend = settings.scheduler.celery_result_backend
    celery_app.conf.task_default_queue = settings.scheduler.celery_queue_name

    # Use Celery + SQLAlchemy scheduler (same as used by celery beat)
    db_uri = str(get_sync_engine().url)
    callback_task_name = "scheduler.execute_callback"
    queue_name = settings.scheduler.celery_queue_name

    client = CelerySqlAlchemySchedulerClient(
        celery_app=celery_app,
        callback_task_name=callback_task_name,
        db_uri=db_uri,
        queue_name=queue_name,
    )

    config = CeleryAdapterConfig(
        callback_task_name=callback_task_name,
        evaluation_callback_task_name="scheduler.evaluate_predicate",
        queue_name=queue_name,
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
            mime_types=frozenset(
                [
                    "text/plain",
                    "text/markdown",
                ]
            ),
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

    # Create loop-closure reply handler
    loop_closure_handler = LoopClosureReplyHandler(
        session_factory=session_factory,
        schedule_adapter=schedule_adapter,
    )
    LOGGER.info("Created loop-closure reply handler")

    # Bootstrap recurring commitment schedules (idempotent)
    try:
        with session_factory() as session:
            if _schedule_exists(session, "commitments.weekly_review"):
                LOGGER.info("Weekly commitment review schedule already exists, skipping bootstrap")
            else:
                weekly_result = schedule_weekly_review(
                    session_factory=session_factory,
                    adapter=schedule_adapter,
                )
                LOGGER.info(
                    "Bootstrapped weekly commitment review schedule: %s",
                    weekly_result.schedule_id if weekly_result.success else weekly_result.error,
                )
    except Exception as e:
        LOGGER.warning("Failed to bootstrap weekly review schedule: %s", e, exc_info=True)

    try:
        with session_factory() as session:
            if _schedule_exists(session, "commitments.daily_batch"):
                LOGGER.info("Daily batch reminder schedule already exists, skipping bootstrap")
            else:
                daily_result = schedule_daily_batch_reminder(
                    session_factory=session_factory,
                    adapter=schedule_adapter,
                )
                LOGGER.info(
                    "Bootstrapped daily batch reminder schedule: %s",
                    daily_result.schedule_id if daily_result.success else daily_result.error,
                )
    except Exception as e:
        LOGGER.warning("Failed to bootstrap daily batch reminder schedule: %s", e, exc_info=True)

    # Future: Add other hook initializations here
    # - Skill output commitment extraction

    LOGGER.info("Agent hooks and services initialized successfully")

    return {
        "signal_commitment_extractor": signal_commitment_extractor,
        "loop_closure_handler": loop_closure_handler,
    }


__all__ = [
    "initialize_agent_hooks",
]
