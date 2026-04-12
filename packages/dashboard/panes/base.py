"""Base view type for dashboard workspace views."""

from __future__ import annotations

from textual.widget import Widget


class BaseView(Widget):
    """Base class for all dashboard view widgets.

    Subclasses set class-level view_id and view_title and provide their
    own compose method.
    """

    DEFAULT_CSS = """
    BaseView { layout: vertical; height: 1fr; }
    """

    view_id: str = ""
    view_title: str = ""
