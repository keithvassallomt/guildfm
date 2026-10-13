from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for every table. Alembic reads its metadata to generate migrations."""
