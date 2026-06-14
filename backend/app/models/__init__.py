# Import all models here so SQLAlchemy's metadata knows about every table
# before create_all() runs. Order matters: User before Note/EmailVerification (FK dependency).
from app.models.user import User  # noqa: F401
from app.models.note import Note  # noqa: F401
from app.models.email_verification import EmailVerification  # noqa: F401
from app.models.refresh_token import RefreshToken  # noqa: F401
from app.models.note_share import NoteShare  # noqa: F401
from app.models.share_link import ShareLink  # noqa: F401
from app.models.attachment import Attachment  # noqa: F401
