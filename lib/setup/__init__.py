"""Brain setup / installer subsystem.

See ``docs/install.md`` for operator documentation. The installer is
re-runnable, walks an interactive wizard to populate
``~/.config/brain/*.yaml``, and on a fresh install also initializes the
upgrade ledger via :mod:`lib.setup.ledger_init`.
"""

from __future__ import annotations
