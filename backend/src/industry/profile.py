"""The industry profile: the words the system speaks for this installation.

Prompts never name an industry themselves; they ask for `current_profile(session)`
and use `context()` and the labels. Presets are starting points an admin picks
and can then edit (PUT /industry-profile).
"""

from dataclasses import asdict, dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models import IndustryProfile


@dataclass(frozen=True)
class Profile:
    industry: str
    description: str
    vendor_label: str
    vendor_label_plural: str
    component_label: str
    component_label_plural: str
    preset: str | None = None

    def context(self) -> str:
        """One line that tells a prompt whose documents these are."""
        return (
            f"Industry: {self.industry}. The organisation: {self.description} "
            f"Its documents come from {self.vendor_label_plural.lower()} "
            f"(called vendors in the data) about {self.component_label_plural.lower()} "
            f"(called components in the data). Use this industry's own terminology."
        )

    def as_dict(self) -> dict[str, str | None]:
        return asdict(self)


PRESETS: dict[str, Profile] = {
    "generic": Profile(
        industry="General",
        description="an organisation that keeps its suppliers' compliance documentation and checks it is complete and current.",
        vendor_label="Supplier", vendor_label_plural="Suppliers",
        component_label="Product", component_label_plural="Products",
        preset="generic",
    ),
    "pharmaceutical": Profile(
        industry="Pharmaceutical",
        description="a pharmaceutical manufacturer's quality assurance team, keeping the vendor documentation "
        "for the components and materials it buys (GMP, 21 CFR Part 11).",
        vendor_label="Vendor", vendor_label_plural="Vendors",
        component_label="Component", component_label_plural="Components",
        preset="pharmaceutical",
    ),
    "logistics": Profile(
        industry="Logistics",
        description="a logistics company's compliance team, keeping the documentation of the carriers, shippers "
        "and suppliers it works with and of the goods it moves (customs, dangerous goods, transport regulations).",
        vendor_label="Partner", vendor_label_plural="Partners",
        component_label="Shipment", component_label_plural="Shipments",
        preset="logistics",
    ),
    "manufacturing": Profile(
        industry="Manufacturing",
        description="a manufacturer's quality team, keeping supplier documentation for the parts and materials "
        "it buys (ISO 9001, material declarations such as RoHS and REACH, certificates of conformity).",
        vendor_label="Supplier", vendor_label_plural="Suppliers",
        component_label="Part", component_label_plural="Parts",
        preset="manufacturing",
    ),
}
DEFAULT_PRESET = "generic"


def profile_of(row: IndustryProfile) -> Profile:
    return Profile(
        industry=row.industry,
        description=row.description,
        vendor_label=row.vendor_label,
        vendor_label_plural=row.vendor_label_plural,
        component_label=row.component_label,
        component_label_plural=row.component_label_plural,
        preset=row.preset,
    )


def current_profile(session: Session) -> Profile:
    """The installation's profile; the generic preset until an admin sets one."""
    row = session.scalars(select(IndustryProfile)).one_or_none()
    return profile_of(row) if row else PRESETS[DEFAULT_PRESET]
