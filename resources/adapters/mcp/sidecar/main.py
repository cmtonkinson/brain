"""Entry point for the MCP Adapter sidecar service."""

from __future__ import annotations

import logging
import sys

import uvicorn

from api import create_app
from config import load_config


def main() -> None:
    """Load config and run the sidecar HTTP server."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )
    config = load_config()
    app = create_app(config=config)
    uvicorn.run(app, host=config.host, port=config.port, log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
