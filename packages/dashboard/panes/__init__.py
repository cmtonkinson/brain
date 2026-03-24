"""Pane exports for the dashboard workspace."""

from .base import DashboardPane
from .log import LogPane
from .policy import PolicyPane
from .trace import TracePane
from .turn import TurnPane
from .welcome import WelcomePane

__all__ = [
    "DashboardPane",
    "LogPane",
    "PolicyPane",
    "TracePane",
    "TurnPane",
    "WelcomePane",
]
