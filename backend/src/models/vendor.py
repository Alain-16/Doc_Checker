import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, relationship, mapped_column

from .base import Base


if TYPE_CHECKING:
    from src.models.vendor_file import VendorFile
    
    

class Vendor(Base):

    __tablename__ = "vendors"

    name: Mapped[str] = mapped_column(unique=True)

    normalized_name: Mapped[str] = mapped_column(unique=True)

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
    vendor: Mapped[Vendor] = relationship(back_populates="components")
    vendor_files: Mapped[list["VendorFile"]] = relationship(back_populates="component")
    


