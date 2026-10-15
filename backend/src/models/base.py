import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ARRAY, CheckConstraint, DateTime, Enum, MetaData, Text, func, text
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
    """Column type that stores a Python enum as plain text.

    Pair every use with enum_check() in the table's __table_args__, which adds the
    CHECK listing the allowed values. We avoid Postgres's native ENUM type because
    its values can't be removed or reordered later.
    """
    return Enum(
        enum_class,
        native_enum=False,
        # The CHECK comes from enum_check() instead. Letting this type create it
        # makes Alembic write the constraint twice (SQLAlchemy 2.1 / Alembic 1.20).
        create_constraint=False,
        length=ENUM_COLUMN_LENGTH,
        # Store the enum's value ("needs_review"), not its Python name ("NEEDS_REVIEW").
        values_callable=lambda members: [member.value for member in members],
        validate_strings=True,
    )


def enum_check(column_name: str, enum_class: type[enum.Enum]) -> CheckConstraint:
    """CHECK that a text column only holds one of the enum's values.

    Named after the column, e.g. "ck_documents_compliance_status". A NULL value
    passes, so nullable enum columns keep working.
    """
    allowed_values = ", ".join(f"'{member.value}'" for member in enum_class)
    return CheckConstraint(f"{column_name} IN ({allowed_values})", name=column_name)
