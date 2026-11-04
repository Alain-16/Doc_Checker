import uuid
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, relationship, mapped_column

from .base import Base, EMPTY_TEXT_ARRAY


if TYPE_CHECKING:
    from src.models.user import User
    from src.models.document import Document
    
    

class Vendor(Base):

    __tablename__ = "vendors"

    name: Mapped[str] = mapped_column(unique=True)

    normalized_name: Mapped[str] = mapped_column(unique=True)

    aliases: Mapped[list[str]] = mapped_column(default=list, server_default=EMPTY_TEXT_ARRAY)

    components: Mapped[list["Component"]] = relationship(back_populates="vendor")


class Component(Base):

    __tablename__ = "components"
    __table_args__ = (
        UniqueConstraint("vendor_id", "name"),
    )

    vendor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vendors.id", ondelete="RESTRICT"))
    name: Mapped[str]
    vendor_part_number: Mapped[str | None]
    internal_part_number: Mapped[str | None]
    description: Mapped[str | None]
    aliases: Mapped[list[str]] = mapped_column(default=list, server_default=EMPTY_TEXT_ARRAY)
    vendor: Mapped[Vendor] = relationship(back_populates="components")
    documents: Mapped[list["Document"]] = relationship(back_populates="component")
    


class OwnerAssignment(Base):
    """A person responsible for a vendor or one component: their alerts go to them first.

    A component's owners take precedence over its vendor's owners; with neither,
    alerts go to everyone with the policy's role (Alerts Phase B). Several owners
    are allowed. Removing an assignment deletes the row; the audit trail keeps it.
    """

    __tablename__ = "owner_assignments"
    __table_args__ = (
        # About exactly one thing: a whole vendor, or one component.
        CheckConstraint("(vendor_id IS NULL) <> (component_id IS NULL)", name="one_subject"),
        # The same person can't be assigned twice to the same thing.
        Index("uq_owner_assignments_user_vendor", "user_id", "vendor_id", unique=True,
              postgresql_where=text("vendor_id IS NOT NULL")),
        Index("uq_owner_assignments_user_component", "user_id", "component_id", unique=True,
              postgresql_where=text("component_id IS NOT NULL")),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vendors.id", ondelete="RESTRICT"), index=True)
    component_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("components.id", ondelete="RESTRICT"), index=True
    )

    user: Mapped["User"] = relationship()

