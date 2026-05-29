"""Central logging setup for local dev and Render production."""

import logging
import os
import sys


def configure_logging() -> None:
    """Send logs to stdout so Render log stream captures them."""
    is_debug = os.getenv("FLASK_DEBUG", "").lower() in ("1", "true")
    is_production = os.getenv("FLASK_ENV", "").lower() == "production"
    level = logging.DEBUG if is_debug else logging.INFO

    if logging.getLogger().handlers:
        return

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        stream=sys.stdout,
        force=True,
    )

    if is_production:
        logging.getLogger("werkzeug").setLevel(logging.WARNING)

    logging.getLogger(__name__).info(
        "Logging configured | level=%s production=%s",
        logging.getLevelName(level),
        is_production,
    )
