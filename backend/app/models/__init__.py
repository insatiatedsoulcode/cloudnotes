# Import all models here so SQLAlchemy's metadata knows about every table
# before create_all() runs. Order matters: User before Note/EmailVerification (FK dependency).
from app.models.user import User  # noqa: F401
from app.models.note import Note  # noqa: F401
from app.models.email_verification import EmailVerification  # noqa: F401
