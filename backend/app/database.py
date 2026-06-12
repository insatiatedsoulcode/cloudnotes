from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings
from app.logger import get_logger

log = get_logger("db")

# echo=True tells SQLAlchemy to send every SQL statement to the
# "sqlalchemy.engine" logger — you'll see the exact queries + parameters.
engine = create_engine(settings.DATABASE_URL, echo=True)

# Mask password in logs (url may be postgresql://user:pass@host/db)
_safe_url = str(engine.url).replace(str(engine.url.password or ""), "***")
log.info("Engine created  url=%s", _safe_url)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """
    FastAPI dependency — yields a DB session for one request, then closes it.

    Lifecycle visible in logs:
      [cloudnotes.db] SESSION OPEN
        ... SQLAlchemy queries fire here ...
      [cloudnotes.db] SESSION CLOSE
    """
    log.debug("SESSION OPEN")
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
        log.debug("SESSION CLOSE")
