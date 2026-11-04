from sqlalchemy import CheckConstraint, Text, true
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class IndustryProfile(Base):
    """The industry this installation serves: one row, edited by an admin.

    It decides the words the system speaks: how prompts describe the
    organisation and its documents, and what vendors and components are called
    ("Carrier" / "Shipment" in logistics). The tables stay vendors/components:
    a vendor is any party that issues documents, a component any item they cover.
    No row = the generic preset (see src/industry/profile.py).
    """

    __tablename__ = "industry_profiles"
    __table_args__ = (
        # One profile per installation: the only allowed value is true, and it is unique.
        CheckConstraint("singleton", name="one_profile"),
    )

    singleton: Mapped[bool] = mapped_column(default=True, server_default=true(), unique=True)
    # The preset it started from, e.g. "logistics"; None if written from scratch.
    preset: Mapped[str | None]
    industry: Mapped[str]  # "Logistics"
    # One sentence for prompts: who the organisation is and what its documents are for.
    description: Mapped[str] = mapped_column(Text)
    vendor_label: Mapped[str]  # "Carrier"
    vendor_label_plural: Mapped[str]  # "Carriers"
    component_label: Mapped[str]  # "Shipment"
    component_label_plural: Mapped[str]  # "Shipments"
