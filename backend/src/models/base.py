import enum
import re
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ARRAY, DateTime, Enum, MetaData, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Every constraint and index gets a predictable name built from these patterns,
NAMING_CONVENTION = {
    "pk": "pk_%(table_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "ix": "ix_%(column_0_label)s",
}


ENUM_COLUMN_LENGTH = 50


EMPTY_JSONB = text("'{}'::jsonb")
EMPTY_TEXT_ARRAY = text("'{}'::text[]")


class Base(DeclarativeBase):
    """Parent class of every table. Gives each table an id and two timestamps."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    # Tells SQLAlchemy which database type to use for these Python type hints,
    # so models can write Mapped[datetime] instead of repeating the type each time.
    type_annotation_map = {
        datetime: DateTime(timezone=True),
        dict[str, Any]: JSONB,
        list[str]: ARRAY(Text),
    }

    # A random UUID generated in Python. UUIDs (unlike 1, 2, 3...) don't reveal how
    # many records exist and can be created before the row reaches the database.
    # sort_order only controls where the column appears in the table: id first,
    # timestamps last, so tables read naturally in psql.
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4, sort_order=-1)

    # The database fills these in using its own clock, so every row is stamped
    # with server time in UTC, as the Part 11 audit rules require.
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), sort_order=1)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        onupdate=func.now(),
        sort_order=1,
    )


def string_enum(enum_class: type[enum.Enum]) -> Enum:
    """Store a Python enum as a text column with a CHECK listing the allowed values.
    """
    return Enum(
        enum_class,
        # Names the CHECK constraint, e.g. ComplianceStatus -> "compliance_status".
        name=_to_snake_case(enum_class.__name__),
        native_enum=False,
        create_constraint=True,
        length=ENUM_COLUMN_LENGTH,
        # Store the enum's value ("needs_review"), not its Python name ("NEEDS_REVIEW").
        values_callable=lambda members: [member.value for member in members],
        validate_strings=True,
    )


def _to_snake_case(name: str) -> str:
    # Put an underscore before every capital letter except the first, then lowercase.
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()