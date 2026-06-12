"""
Central logging setup for CloudNotes.

Dataflow through the layers (read top-to-bottom when watching logs):

  Browser fetch()
    → Vite dev proxy  (/api → :8000)
      → FastAPI middleware   [cloudnotes.request] + [cloudnotes.response]
        → Router function    [cloudnotes.notes]
          → get_db()         [cloudnotes.db]
            → SQLAlchemy     [sqlalchemy.engine]   ← actual SQL + params
          ← session close    [cloudnotes.db]
        ← router returns     [cloudnotes.notes]
      ← middleware records   [cloudnotes.response]
    ← HTTP response
  Browser receives JSON

Each logger name appears inside [] in every log line so you can grep
for a specific layer, e.g.:  grep "cloudnotes.db"
"""

import logging
import sys

_FMT = "%(asctime)s  %(levelname)-8s  [%(name)s]  %(message)s"
_DATE = "%H:%M:%S"


def setup_logging(level: str = "DEBUG") -> None:
    logging.basicConfig(
        stream=sys.stdout,
        level=getattr(logging, level.upper(), logging.DEBUG),
        format=_FMT,
        datefmt=_DATE,
        force=True,
    )

    # sqlalchemy.engine logs every SQL statement + bound parameters.
    # Set to INFO to see statements; set to DEBUG to also see result rows.
    logging.getLogger("sqlalchemy.engine").setLevel(logging.INFO)

    # Silence uvicorn's built-in access log — our middleware handles that.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"cloudnotes.{name}")
