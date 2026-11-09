"""What a check may look at, and what it concludes. No database, no rule logic."""

import calendar
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict

from src.models.document import ComplianceStatus, DateType
from src.models.review import ReviewItemKind

MONTHS_PER_YEAR = 12


@dataclass(frozen=True)
class DateFact:
    date_type: DateType
    value: date
    page_number: int
    original_text: str
    # False = mentioned by the document ("supersedes Rev. 10 (2019)"), not about it.
    is_document_date: bool


@dataclass(frozen=True)
class AttributeFact:
    """One extracted attribute. No fact at all for an attribute = not extracted yet."""

    name: str
    display_name: str
    value: Any  # None = extraction looked and the document doesn't state it
    page_number: int | None
    required: bool = False
    evidence_snippet: str | None = None


@dataclass(frozen=True)
class ReviewFact:
    kind: ReviewItemKind
    reason: str
    page_number: int | None


@dataclass(frozen=True)
class DocumentFacts:
    document_type: str  # name, e.g. "compliance_bulletin"
    document_type_label: str  # display name, e.g. "Compliance Bulletin"
    dates: list[DateFact]
    attributes: dict[str, AttributeFact]  # by key attribute name
    open_reviews: list[ReviewFact]


@dataclass(frozen=True)
class GroupDocument:
    """A current document of a component or vendor."""

    document_type: str
    document_type_label: str
    status: ComplianceStatus
    title: str | None
    facts: DocumentFacts


@dataclass(frozen=True)
class GroupFacts:
    """Everything known about a component's or a vendor's documents as a whole."""

    name: str
    # Current (not superseded) documents, status already evaluated. A component
    # also counts its vendor's company-level documents: an ISO certificate held
    # by the vendor covers each of its components.
    current_documents: list[GroupDocument]
    # Document type name -> label, for types found only among superseded documents.
    superseded_types: dict[str, str]
    document_type_labels: dict[str, str]  # every known type, for messages


@dataclass
class Outcome:
    """What a check concluded. A check returns None when it has nothing to say."""

    status: ComplianceStatus
    message: str  # one sentence a user can read (Feature 7)
    governing_date: date | None = None
    evidence: dict[str, Any] = field(default_factory=dict)


def label(date_type: DateType) -> str:
    return date_type.value.replace("_", " ")


def add_months(day: date, months: int) -> date:
    """30 Jun 2022 + 36 months = 30 Jun 2025; 31 Jan + 1 month = 28/29 Feb."""
    years, month_index = divmod(day.month - 1 + months, MONTHS_PER_YEAR)
    year, month = day.year + years, month_index + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


class RuleParameters(BaseModel):
    # Unknown keys are refused, so a typo in a rule ("treshold") is an error, not ignored.
    model_config = ConfigDict(extra="forbid")
