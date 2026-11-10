import logging
import sys

from app.config import get_settings


def configure_logging() -> None:
    """Basic stdlib logging, no extra dependency.

    Deliberately simple for Phase 0 -- a structured/JSON logging library is a
    decision not made anywhere in the approved specs, so it isn't introduced
    here. Revisit if a later phase needs structured log aggregation.
    """
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )
